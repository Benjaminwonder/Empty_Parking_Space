# box: G2 · lane: BD · read BRIDGES.md before editing
"""
Claims: a driver says "I'm taking this spot", and everyone else stops being sent there.

A claim is a promise from a driver, not something a sensor saw, so it never enters the
feed and never becomes an OccupancyEvent. It lives in the server's memory (a restart
clears it) and is laid over the status just before the view is built.

The life of a claim (rules agreed 2026-10-12, arrival rules 2026-10-13):
  held      claimed while the spot was seen free; nobody else is sent there.
  car_seen  a sensor saw a car in the spot after the claim was made. A camera cannot tell whose car:
            the page decides with the driver's location (which never reaches us), or asks "Was that you?".
  arrived   confirmed: the driver said "I've parked" and the camera agrees (it wins if it does not), or,
            on a slow-sensor stall nobody can check soon, the driver's own report (reports.py).
  released  after the arrival window, as soon as the spot is seen empty:
              no car ever seen          -> "no_show"   (the driver gets "Unresponsive, so spot released")
              said parked, never seen   -> "not_seen"  ("We never saw your car at A-05")
              a car came and went       -> "left"      (quiet)
            or the sensor went quiet past twice the window -> "no_data"
            or the driver let go / claimed another spot     -> "cancelled" / "switched"
            or the car seen was someone else's (the page)   -> "taken"     (the page finds the next spot)

All times are on the replay clock, like everything else the server serves.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from parkfind.clock import parse_utc

ARRIVAL_BASE = timedelta(minutes=8)  # used when the page doesn't say how long the drive is
HOLD_MIN, HOLD_MAX = 4, 15            # minutes a page may ask for: never a blink, never an afternoon
EXTEND_MIN, EXTEND_MAX = 2, 5         # one extension per claim, for a driver visibly on the way


def hold_window(hold_min) -> timedelta:
    """why: a spot should be held about as long as the drive to it takes, not a flat 8 minutes for everyone:
            hoarding is shorter for someone next door, and nobody across campus loses theirs on the way.
    boundary: takes the page's ask in whole minutes (it knows the route; we never learn where the driver is) and clamps it.
    ugly: a missing or unreadable ask falls back to ARRIVAL_BASE; a greedy ask is capped at HOLD_MAX.
    """
    try:
        minutes = int(hold_min)
    except (TypeError, ValueError):
        return ARRIVAL_BASE
    return timedelta(minutes=max(HOLD_MIN, min(HOLD_MAX, minutes)))
# Only stall sensors can confirm a car, so only their spots can be claimed (counted lots cannot).
CLAIMABLE = ("continuous", "near_live", "periodic_snapshot", "slow_snapshot")
LIVE = ("continuous", "near_live")   # cameras quick enough to check an "I've parked" within the window


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
    car_seen: bool = False       # a sensor saw a car here after the claim (anyone's car)
    confirmed: bool = False      # it is this driver's: their "I've parked" agreed with the camera, or their report
    said_parked: bool = False    # the driver pressed "I've parked"
    extended: bool = False       # the one extension has been used

    def view(self) -> dict:
        phase = "arrived" if self.confirmed else ("car_seen" if self.car_seen else "held")
        return {"stall_id": self.stall_id, "phase": phase, "said_parked": self.said_parked, "extended": self.extended,
                "claimed_at": _stamp(self.claimed_at), "deadline": _stamp(self.claimed_at + self.window),
                "window_s": int(self.window.total_seconds())}


def _stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class ClaimBook:
    """Every live claim, one per stall and one per driver. All changes happen under one lock."""

    def __init__(self, labels=None) -> None:
        self._lock = threading.Lock()
        self._labels = labels   # confirmations.LabelLog or None: drivers' confirmations become camera labels
        self._by_stall: dict[str, Claim] = {}
        self._by_driver: dict[str, str] = {}
        self._last_release: dict[str, dict] = {}   # driver_id -> the latest release, told to them once
        self._release_seq = 0

    def claim(self, stall_id: str, driver_id: str, status: dict, now: datetime, hold_min=None) -> dict:
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
            claim = Claim(stall_id, driver_id, now, hold_window(hold_min) + sensor_interval(stall["ttl_s"]))
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

    def parked(self, driver_id: str, status: dict, now: datetime, reports) -> dict:
        """why: the driver says "I've parked"; we believe the camera, and the driver only where no camera can check.
        boundary: reads the status (before claims are laid on); changes this driver's claim; may add one report.
        ugly: a 5-minute camera may not have taken its next picture yet, so "not seen yet" is not a refusal: the
              claim remembers the tap and confirms itself the moment the camera sees the car.
        """
        with self._lock:
            self._sweep(status, now)
            stall_id = self._by_driver.get(driver_id)
            if stall_id is None:
                raise ClaimRefused("no_claim", "You have no spot claimed.")
            claim = self._by_stall[stall_id]
            claim.said_parked = True
            short = stall_id.split(":", 1)[1]
            if status["stalls"][stall_id]["cadence_class"] in LIVE:
                if claim.car_seen:
                    claim.confirmed = True
                    self._label(stall_id, "occupied", "driver_and_camera", status["stalls"][stall_id])
                    return {"result": "confirmed", "message": f"Confirmed: the camera sees your car at {short}.",
                            "my_claim": claim.view()}
                return {"result": "not_seen", "message": f"The camera doesn't see a car at {short} yet. "
                        "We'll confirm as soon as it does.", "my_claim": claim.view()}
            reports.parked(driver_id, stall_id, now)
            claim.car_seen = claim.confirmed = True
            return {"result": "recorded", "message": f"Thanks: {short} is marked taken. This lot's sensor is slow, "
                    "so your word counts until it checks.", "my_claim": claim.view()}

    def extend(self, driver_id: str, minutes, now: datetime) -> dict:
        """why: someone stuck behind a bus should not lose the spot they are visibly driving to.
        boundary: this driver's own held claim, once, before its deadline; 2-5 minutes (the page asks only when the
                  driver got closer since claiming: it holds the location, we never see it).
        ugly: a claim a car already reached, or one past its deadline, is not extended: the rules for those already ran.
        """
        with self._lock:
            stall_id = self._by_driver.get(driver_id)
            if stall_id is None:
                raise ClaimRefused("no_claim", "You have no spot claimed.")
            claim = self._by_stall[stall_id]
            if claim.extended:
                raise ClaimRefused("already_extended", "This hold was already extended once.")
            if claim.car_seen or now >= claim.claimed_at + claim.window:
                raise ClaimRefused("too_late", "This hold can't be extended any more.")
            try:
                add = max(EXTEND_MIN, min(EXTEND_MAX, int(minutes)))
            except (TypeError, ValueError):
                add = EXTEND_MIN
            claim.window += timedelta(minutes=add)
            claim.extended = True
            return claim.view()

    def taken(self, driver_id: str, now: datetime) -> None:
        """why: the car the camera saw was not this driver's (they are still far away): free them to get another spot.
        boundary: releases only this driver's claim, with outcome "taken"; the page claims the next spot itself.
        ugly: sent twice (two tabs) it is harmless: the second finds no claim.
        """
        with self._lock:
            stall_id = self._by_driver.get(driver_id)
            if stall_id is not None:
                self._release(stall_id, "taken", now)

    def holder(self, stall_id: str) -> str | None:
        """Which driver holds this stall right now (for demo cars, which live only as long as the claim)."""
        with self._lock:
            claim = self._by_stall.get(stall_id)
            return claim.driver_id if claim else None

    def mine(self, driver_id: str) -> dict | None:
        """This driver's live claim, or None."""
        with self._lock:
            stall_id = self._by_driver.get(driver_id)
            return self._by_stall[stall_id].view() if stall_id else None

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
                if claim.said_parked and not claim.confirmed:
                    claim.confirmed = True   # they said they parked, and now the camera sees a car: theirs
                    self._label(stall_id, "occupied", "driver_and_camera", stall)
                claim.car_seen = True
            if now < claim.claimed_at + claim.window:
                continue
            if stall.get("state") == "free":
                if claim.said_parked and not claim.car_seen:
                    self._label(stall_id, "occupied", "disputed_not_seen", stall)   # the camera may have missed a car
                self._release(stall_id, "left" if claim.car_seen else ("not_seen" if claim.said_parked else "no_show"), now)
            elif stall.get("state") == "unknown" and now >= claim.claimed_at + 2 * claim.window:
                self._release(stall_id, "no_data", now)

    def _label(self, stall_id: str, label: str, evidence: str, stall: dict) -> None:
        if self._labels is not None:
            self._labels.add(stall_id, label, evidence, stall)

    def _release(self, stall_id: str, outcome: str, now: datetime) -> None:
        claim = self._by_stall.pop(stall_id)
        self._by_driver.pop(claim.driver_id, None)
        self._release_seq += 1
        self._last_release[claim.driver_id] = {"id": self._release_seq, "stall_id": stall_id,
                                               "outcome": outcome, "at": _stamp(now)}
