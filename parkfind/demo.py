# box: G4 · lane: BD · read BRIDGES.md before editing
"""
Demo cars: the one thing a recorded day cannot contain is the person watching it.

When a demo driver's dot reaches their claimed spot, the camera there "sees" their car: we
write the reading the camera would have written (same OccupancyEvent shape, source demo.car),
stamped at the current replay moment on every read, so it stays the newest word on that stall
until the driver leaves. Everything downstream is unchanged: the claim notices a car, the page
decides from location that it is yours, and "I've parked" is confirmed by the camera.

Only a server started with --demo takes demo cars (run.py does: it always replays a recording).
They live in memory, die with the claim, and never reach the feed, truth.json or the scorer.
A slow-sensor stall gets no demo reading: its sensor would not have looked yet, so the driver
taps "I've parked" there, exactly as a real driver would.
"""

from __future__ import annotations

import threading
from datetime import datetime

from parkfind.event import OccupancyEvent

SOURCE = "demo.car"
LIVE = ("continuous", "near_live")


class DemoBook:
    """Demo cars parked right now: driver_id -> (stall_id, the camera's cadence and ttl)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cars: dict[str, tuple[str, str, str]] = {}

    def park(self, driver_id: str, claim: dict | None, status: dict) -> dict:
        """why: the demo drive has arrived; put the driver's car where the camera can see it.
        boundary: needs the driver's own live claim; reads the stall's sensor kind from the status; stores one car.
        ugly: on a slow-sensor stall nothing is written (that sensor has not looked yet): the page asks for "I've parked".
              A stall a car reached first is refused ("occupied"): the page treats it as taken and drives on.
        """
        if claim is None:
            return {"result": "no_claim", "message": "You have no spot claimed."}
        stall_id = claim["stall_id"]
        stall = status["stalls"][stall_id]
        if claim["phase"] == "car_seen" and not claim["said_parked"]:
            # a car got there first (seen before we arrived): two cars never share a stall, so the spot is taken
            return {"result": "occupied", "message": f"Someone is already parked in {stall_id.split(':', 1)[1]}."}
        if stall["cadence_class"] not in LIVE:
            return {"result": "slow", "message": "This lot's sensor is slow, so it won't see your car for a while: "
                    "tap \"I've parked\"."}
        ttl = f"{max(1, int(stall['ttl_s'] or 90))}s"
        with self._lock:
            self._cars[driver_id] = (stall_id, stall["cadence_class"], ttl)
        return {"result": "parked", "message": "Parked. The camera will see your car on its next look."}

    def events(self, now: datetime, holder) -> list[OccupancyEvent]:
        """why: each demo car as the camera's newest reading of its stall, stamped now, so the recording can't undo it.
        boundary: holder(stall_id) says which driver holds a stall; a car whose claim has ended is removed here.
        ugly: this is the only place a reading is stamped with the read time instead of the time it was seen;
              that is honest only because the car really is there for as long as the claim lasts.
        """
        # to the millisecond: a sensor reporting on the whole second would otherwise tie with us, and ties go to the older
        stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        with self._lock:
            keep, out = {}, []
            for driver_id, (stall_id, cadence, ttl) in self._cars.items():
                if holder(stall_id) != driver_id:
                    continue                       # released, left, taken or switched: the car is gone
                keep[driver_id] = (stall_id, cadence, ttl)
                out.append(OccupancyEvent(state="occupied", confidence=0.99, source=SOURCE, observed_at=stamp,
                                          ttl=ttl, cadence_class=cadence, stall_id=stall_id,
                                          zone_id=stall_id.rsplit("-", 1)[0], lot_id=stall_id.split(":", 1)[0]))
            self._cars = keep
            return out
