# box: G2 · lane: BD · read BRIDGES.md before editing
"""
Claims: a driver says "I'm taking this spot", and everyone else stops being sent there.

A claim is a promise from a driver, not something a sensor saw, so it never enters the
feed and never becomes an OccupancyEvent. It lives in the server's memory (a restart
clears it) and is laid over the status just before the view is built.

The life of a claim (rules agreed 2026-10-12):
  held      claimed while the spot was seen free; nobody else is sent there.
  arrived   a sensor saw the spot occupied after the claim was made: the driver's car.
  released  after the arrival window, as soon as the spot is seen empty:
              never arrived  -> "no_show"  (the driver gets "Unresponsive, so spot released")
              arrived, left  -> "left"     (quiet)
            or the sensor went quiet past twice the window -> "no_data"
            or the driver let go / claimed another spot     -> "cancelled" / "switched"

All times are on the replay clock, like everything else the server serves.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from parkfind.clock import parse_utc

ARRIVAL_BASE = timedelta(minutes=8)  # the user's figure; may be corrected later
# Only stall sensors can confirm a car, so only their spots can be claimed (counted lots cannot).
CLAIMABLE = ("continuous", "near_live", "periodic_snapshot", "slow_snapshot")


def sensor_interval(ttl_s: float) -> timedelta:
    """why: slower sensors need longer to notice a car, so the arrival window grows by one reporting interval.
    boundary: reads the claim's ttl, not its cadence_class: the class calls 5- and 15-minute snapshots both
              periodic_snapshot, while their ttls (8m vs 24m) tell them apart.
    ugly: a new sensor with an odd ttl falls into the nearest band; widen the bands here, not in callers.
    """
    if ttl_s <= 120:
        return timedelta(0)            # live camera (ttl 90s): 8 min
    if ttl_s <= 600:
        return timedelta(minutes=5)    # 5-minute camera (ttl 8m): 13 min
    return timedelta(minutes=15)       # 15-minute snapshot (ttl 24m): 23 min


class ClaimRefused(Exception):
    """A claim that cannot be granted. code is for the page; message is for the driver."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Claim:
    stall_id: str
    driver_id: str
    claimed_at: datetime
    window: timedelta
    arrived: bool = False

    def view(self) -> dict:
        return {"stall_id": self.stall_id, "phase": "arrived" if self.arrived else "held",
                "claimed_at": _stamp(self.claimed_at), "deadline": _stamp(self.claimed_at + self.window),
                "window_s": int(self.window.total_seconds())}


def _stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class ClaimBook:
    """Every live claim, one per stall and one per driver. All changes happen under one lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_stall: dict[str, Claim] = {}
        self._by_driver: dict[str, str] = {}
        self._last_release: dict[str, dict] = {}   # driver_id -> the latest release, told to them once
        self._release_seq = 0

    def claim(self, stall_id: str, driver_id: str, status: dict, now: datetime) -> dict:
        """why: first driver wins a spot; the second is refused at once, not sent to the same place.
        boundary: reads the current status (aged by last-seen); changes only this book.
        ugly: only a spot seen free right now can be claimed: unknown, counted-only and occupied spots are refused.
        """
        if not driver_id:
            raise ClaimRefused("no_driver", "Missing driver id.")
        stall = status["stalls"].get(stall_id)
        if stall is None:
            raise ClaimRefused("no_stall", f"{stall_id} is not a spot on this campus.")
        with self._lock:
            self._sweep(status, now)
            mine = self._by_stall.get(stall_id)
            if mine is not None and mine.driver_id == driver_id:
                return mine.view()  # pressing Claim twice changes nothing
            if mine is not None:
                raise ClaimRefused("taken", "Someone just claimed that spot.")
            if stall["state"] != "free" or stall["cadence_class"] not in CLAIMABLE:
                raise ClaimRefused("not_free", "That spot isn't seen free right now, so it can't be claimed.")
            old = self._by_driver.get(driver_id)
            if old is not None:
                self._release(old, "switched", now)
            claim = Claim(stall_id, driver_id, now, ARRIVAL_BASE + sensor_interval(stall["ttl_s"]))
            self._by_stall[stall_id] = claim
            self._by_driver[driver_id] = stall_id
            return claim.view()

    def release(self, driver_id: str, now: datetime) -> None:
        """why: the driver lets go early (changed plans, parked elsewhere).
        boundary: removes only this driver's own claim.
        ugly: releasing with no claim is not an error; the page may send it twice.
        """
        with self._lock:
            stall_id = self._by_driver.get(driver_id)
            if stall_id is not None:
                self._release(stall_id, "cancelled", now)

    def overlay(self, status: dict, now: datetime, driver_id: str) -> dict:
        """why: put claims on top of what the sensors say, so pins, guidance and the page treat a held spot as taken.
        boundary: edits the status it is given (stall state and lot counts) and returns this driver's own claim news.
        ugly: a held spot a sensor still sees free becomes "reserved"; one it sees occupied stays occupied (that car is
              the driver's). Other drivers learn only that a spot is held, never by whom.
        """
        with self._lock:
            self._sweep(status, now)
            for stall_id, claim in self._by_stall.items():
                stall = status["stalls"].get(stall_id)
                if stall is None:
                    continue
                stall["held"] = True
                if stall["state"] == "free":
                    stall["state"] = "reserved"
                    lot = status["lots"].get(stall_id.split(":", 1)[0])
                    if lot is not None:
                        lot["free"] -= 1
                        lot["held"] = lot.get("held", 0) + 1
            mine = self._by_driver.get(driver_id)
            return {"my_claim": self._by_stall[mine].view() if mine else None,
                    "last_release": self._last_release.get(driver_id)}

    def _sweep(self, status: dict, now: datetime) -> None:
        """why: move every claim along its life: notice arrivals, release when the rules say so.
        boundary: reads stall states from the status; caller holds the lock.
        ugly: a sensor that goes quiet (unknown) cannot say the car left; such a claim ends at twice its window.
        """
        for stall_id in list(self._by_stall):
            claim = self._by_stall[stall_id]
            stall = status["stalls"].get(stall_id, {})
            seen = stall.get("observed_at")
            if seen and stall.get("last_claim") == "occupied" and parse_utc(seen) > claim.claimed_at:
                claim.arrived = True
            if now < claim.claimed_at + claim.window:
                continue
            if stall.get("state") == "free":
                self._release(stall_id, "left" if claim.arrived else "no_show", now)
            elif stall.get("state") == "unknown" and now >= claim.claimed_at + 2 * claim.window:
                self._release(stall_id, "no_data", now)

    def _release(self, stall_id: str, outcome: str, now: datetime) -> None:
        claim = self._by_stall.pop(stall_id)
        self._by_driver.pop(claim.driver_id, None)
        self._release_seq += 1
        self._last_release[claim.driver_id] = {"id": self._release_seq, "stall_id": stall_id,
                                               "outcome": outcome, "at": _stamp(now)}
