# box: G3 · lane: BD · read BRIDGES.md before editing
"""
Driver reports: what a person on the ground tells us where sensors see little.

A report is an OccupancyEvent like any sensor's (one event shape), with source "driver.report"
and cadence "event_only", so guidance can use it for rows and counts but never names a single
stall from it (only continuous / near_live do that, D4). Reports live in the server's memory,
like claims; a restart clears them, and they never enter the recorded feed or truth.json.

Two kinds (agreed 2026-10-13):
  row count   "about 3 free in row B": zone grain, free_count/total_count, good for 10 minutes.
              Only for rows no live camera watches: where a camera can see, the camera answers.
  parked      "I've parked at LBC A-04" on a slow-sensor stall: the stall reads occupied until the
              lot's next sensor reading (newer) replaces it.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from parkfind.event import OccupancyEvent

SOURCE = "driver.report"
ROW_TTL = "10m"      # a row count from a driver goes stale fast: cars come and go
PARKED_TTL = "1h"    # long enough to outlast the slowest sensor's next reading, which replaces it
LIVE = ("continuous", "near_live")


class ReportRefused(Exception):
    """A report we will not take. code is for the page; message is for the driver."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class ReportBook:
    """Every live driver report, one per driver per row (or stall). All changes happen under one lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reports: dict[tuple[str, str], OccupancyEvent] = {}   # (driver_id, zone or stall) -> latest

    def row_count(self, driver_id: str, zone_id: str, free_count: int, layout: dict, status: dict,
                  now: datetime) -> OccupancyEvent:
        """why: a driver in a lot sensors barely see says roughly how many spots are free in a row.
        boundary: checks the row exists and that no live camera watches it; stores one event; writes no file.
        ugly: a second report from the same driver for the same row replaces the first, so nobody can stack votes.
        """
        if not driver_id:
            raise ReportRefused("no_driver", "Missing driver id.")
        lot_id, _, row = zone_id.partition(":")
        lot = next((l for l in layout["lots"] if l["lot_id"] == lot_id), None)
        if lot is None or row not in lot["rows"]:
            raise ReportRefused("no_zone", f"{zone_id} is not a row on this campus.")
        ids = [f"{zone_id}-{n:02d}" for n in range(1, lot["stalls_per_row"] + 1)]
        if any(status["stalls"][s]["cadence_class"] in LIVE and status["stalls"][s]["state"] != "unknown" for s in ids):
            raise ReportRefused("watched", "A live camera already watches this row, so it reports the free spots itself.")
        if not 0 <= free_count <= len(ids):
            raise ReportRefused("bad_count", f"Row {row} has {len(ids)} spots.")
        ev = OccupancyEvent(state="free" if free_count else "occupied", confidence=0.6, source=SOURCE,
                            observed_at=_stamp(now), ttl=ROW_TTL, cadence_class="event_only",
                            zone_id=zone_id, lot_id=lot_id, free_count=free_count, total_count=len(ids))
        with self._lock:
            self._reports[(driver_id, zone_id)] = ev
        return ev

    def parked(self, driver_id: str, stall_id: str, now: datetime) -> OccupancyEvent:
        """why: on a slow-sensor stall nobody can see the car arrive soon; the driver's word is what we have.
        boundary: called by the claim flow only after it decided the stall's sensor is too slow to check.
        ugly: the next sensor reading wins (it is newer), even if it disagrees: the driver's word never overrules a sensor.
        """
        ev = OccupancyEvent(state="occupied", confidence=0.6, source=SOURCE, observed_at=_stamp(now), ttl=PARKED_TTL,
                            cadence_class="event_only", stall_id=stall_id, zone_id=stall_id.rsplit("-", 1)[0],
                            lot_id=stall_id.split(":", 1)[0])
        with self._lock:
            self._reports[(driver_id, stall_id)] = ev
        return ev

    def events(self, now: datetime) -> list[OccupancyEvent]:
        """why: the reports still worth hearing, for current_status to read alongside the feed.
        boundary: returns copies of nothing; just the events whose time has come and has not run out.
        ugly: an expired report is dropped, not aged to unknown: a stale "3 free" must not hide an older,
              still-valid sensor count for that row. Reports "from the future" (the replay day looped) are dropped too.
        """
        with self._lock:
            keep = {}
            for key, ev in self._reports.items():
                seen = ev.observed_utc()
                if seen <= now < seen + timedelta(seconds=ev.ttl_seconds()):
                    keep[key] = ev
            self._reports = keep
            return list(keep.values())
