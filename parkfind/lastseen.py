# box: T1–T2 · lane: DI · read BRIDGES.md before editing

"""
Read occupancy events from the ParkFind feed and build the latest known
parking state.

This file belongs to the trunk/backend. It may read the canonical event feed,
but it must never read simulator truth.
"""

import json
from pathlib import Path
from datetime import datetime

from parkfind.event import OccupancyEvent, EventShapeError


def read_feed(path: str | Path, now: datetime) -> tuple[list[OccupancyEvent], int]:
    """
    why: Read sensor claims from feed.jsonl so downstream code only receives
    valid ParkFind occupancy events that have happened by `now`.

    boundary: Reads SK-FEED and validates each line through SK-EVENT. It does
    not repair malformed events, infer missing data, or read simulator truth.

    ugly: A replay feed can contain valid events later than `now`; those lines
    are skipped rather than rejected because they have simply not happened yet.
    """
    events = []
    rejected_lines = 0

    path = Path(path)

    with path.open("r", encoding="utf-8") as feed:
        for line in feed:
            try:
                data = json.loads(line)
                event = OccupancyEvent.from_json(data)
            except (json.JSONDecodeError, EventShapeError):
                rejected_lines += 1
                continue

            if event.observed_utc() > now:
                continue

            events.append(event)

    return events, rejected_lines

def _claim_status(event: OccupancyEvent, now: datetime) -> dict:
    """
    why: Turn one sensor claim into its current trustworthy status by comparing
    its age with its own ttl.

    boundary: Uses only the OccupancyEvent and the supplied now. It does not
    inspect simulator truth or infer a newer state.

    ugly: An expired claim keeps its original value in last_claim, but its
    current state becomes unknown.
    """
    age_s = (now - event.observed_utc()).total_seconds()
    ttl_s = event.ttl_seconds()

    current_state = event.state

    if age_s > ttl_s:
        current_state = "unknown"

    result = {
        "state": current_state,
        "last_claim": event.state,
        "observed_at": event.observed_at,
        "age_s": age_s,
        "ttl_s": ttl_s,
        "source": event.source,
        "cadence_class": event.cadence_class,
        "confidence": event.confidence,
    }

    if event.free_count is not None:
        result["free_count"] = event.free_count
        result["total_count"] = event.total_count

    return result


def status(events: list[OccupancyEvent], layout: dict, now: datetime) -> dict:
    """
    why: Build ParkFind's latest known state from occupancy events so the rest
    of the system sees one current, freshness-aware view of the lot.

    boundary: Reads only validated OccupancyEvents and the lot layout. It keeps
    stall, zone, and lot claims at their original grain and never reads
    simulator truth.

    ugly: Many stalls may never have emitted an event, especially with the
    continuous adapter. Those stalls must still appear and remain unknown.
    """
    latest_stalls = {}
    latest_zones = {}
    latest_lot = None

    # Keep the newest claim by observed_at, not by file order.
    for event in events:
        event_time = event.observed_utc()

        if event.stall_id is not None:
            old = latest_stalls.get(event.stall_id)

            if old is None or event_time > old.observed_utc():
                latest_stalls[event.stall_id] = event

        elif event.zone_id is not None:
            old = latest_zones.get(event.zone_id)

            if old is None or event_time > old.observed_utc():
                latest_zones[event.zone_id] = event

        elif event.lot_id is not None:
            if latest_lot is None or event_time > latest_lot.observed_utc():
                latest_lot = event

    stalls = {}

    # The layout, not the feed, defines which stalls exist.
    for zone in layout["zones"]:
        zone_id = zone["zone_id"]

        for row_id in zone["rows"]:
            for number in range(1, zone["stalls_per_row"] + 1):
                stall_id = f"{row_id}-{number:02d}"

                event = latest_stalls.get(stall_id)

                if event is None:
                    stalls[stall_id] = {
                        "state": "unknown",
                        "last_claim": None,
                        "observed_at": None,
                        "age_s": None,
                        "ttl_s": None,
                        "source": None,
                        "cadence_class": None,
                        "confidence": None,
                    }
                else:
                    stalls[stall_id] = _claim_status(event, now)

    zones = {
        zone_id: _claim_status(event, now)
        for zone_id, event in latest_zones.items()
    }

    lot = None

    if latest_lot is not None:
        lot = _claim_status(latest_lot, now)

    return {
        "as_of": now.isoformat(),
        "stalls": stalls,
        "zones": zones,
        "lot": lot,
    }