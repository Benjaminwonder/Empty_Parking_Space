# box: E0 · lane: BD · read BRIDGES.md before editing
"""
The one occupancy event: the form every sensor fills in and every reader reads.

Not a parking stall. A *claim about* a stall, zone or lot: what a sensor saw,
how sure it was, when it saw it, and how long that claim stays good. The stall
itself lives in lot_commuter_north.json; the truth about it lives only in the
simulator's World. This file sits between them.

The simulator writes these today; a camera adapter writes them after the grant.
Nothing downstream should be able to tell which. That is why it lives in
parkfind/ and not in sim.py: the trunk may import this file and must never
import the simulator.

What a sensor claims (its ttl and confidence per cadence) is adapter policy and
stays with the adapter. This file only says what a valid claim looks like, and
refuses anything else, whether it is being written or read.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Literal, get_args

State = Literal["free", "occupied", "reserved", "out_of_service", "unknown"]
Cadence = Literal["continuous", "near_live", "periodic_snapshot", "slow_snapshot", "event_only"]
STATES = get_args(State)
CADENCES = get_args(Cadence)
REQUIRED = ("state", "confidence", "source", "observed_at", "ttl", "cadence_class")

_TTL = re.compile(r"^(\d+)([smh])$")
_TTL_UNIT_S = {"s": 1, "m": 60, "h": 3600}
# Offset or Z is mandatory: a timestamp with no zone is how ages end up silently hours off.
# Fractions only as 3 or 6 digits: the forms Python 3.10's fromisoformat can read.
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3}(\d{3})?)?(Z|[+-]\d{2}:\d{2})$")


class EventShapeError(ValueError):
    """A line or object that is not an OccupancyEvent. Readers count it; nobody repairs it."""


@dataclass
class OccupancyEvent:
    state: State
    confidence: float
    source: str
    observed_at: str          # when the sensor saw it (UTC, ISO 8601), never when we read it
    ttl: str                  # how long the claim stays good: "15s", "8m", "1h"
    cadence_class: Cadence
    stall_id: str | None = None
    zone_id: str | None = None
    lot_id: str | None = None
    free_count: int | None = None    # zone or lot grain only (D2); counts ADA/EV stalls too
    total_count: int | None = None
    note: str | None = None          # for humans; no code may read it or put simulator truth in it

    def __post_init__(self) -> None:
        """why: one validator for writers and readers, so a bad event dies where it was made.
        boundary: checks this object's own fields only; whether a stall_id exists in the layout is the reader's job.
        ugly: a simulator bug that writes counts on a stall claim crashes the sim run, not DI's reader a day later.
        """
        def bad(msg: str) -> EventShapeError:
            return EventShapeError(f"{msg} (source={self.source!r}, observed_at={self.observed_at!r})")

        if self.state not in STATES:
            raise bad(f"state {self.state!r} is not one of {STATES}")
        if self.cadence_class not in CADENCES:
            raise bad(f"cadence_class {self.cadence_class!r} is not one of {CADENCES}")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) \
                or not 0.0 <= self.confidence <= 1.0:
            raise bad(f"confidence {self.confidence!r} must be a number from 0 to 1")
        if not isinstance(self.source, str) or not self.source:
            raise bad("source must be a non-empty string")
        if not isinstance(self.observed_at, str) or not _ISO_UTC.match(self.observed_at):
            raise bad(f"observed_at {self.observed_at!r} must be ISO 8601 with Z or an offset")
        ttl = _TTL.match(self.ttl) if isinstance(self.ttl, str) else None
        if not ttl or int(ttl.group(1)) == 0:
            raise bad(f"ttl {self.ttl!r} must look like 15s, 8m or 1h and be above zero")
        for name in ("stall_id", "zone_id", "lot_id", "note"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise bad(f"{name} must be a string")
        if self.stall_id is None and self.zone_id is None and self.lot_id is None:
            raise bad("a claim must name a stall, a zone or a lot")
        # Counts describe many stalls; on a single-stall claim they could only be invented.
        has_counts = self.free_count is not None or self.total_count is not None
        if has_counts:
            if self.stall_id is not None:
                raise bad("free_count/total_count belong on zone or lot claims, not on a stall claim")
            if self.free_count is None or self.total_count is None:
                raise bad("free_count and total_count come together")
            for name in ("free_count", "total_count"):
                value = getattr(self, name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise bad(f"{name} must be a whole number, zero or more")
            if self.free_count > self.total_count:
                raise bad(f"free_count {self.free_count} is more than total_count {self.total_count}")

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_json(cls, d: dict) -> OccupancyEvent:
        """why: the only door from a feed line into the trunk; what passes it is a real OccupancyEvent.
        boundary: checks keys, then hands the values to the same validator writers use; fills in nothing.
        ugly: an unknown key is refused, not ignored, or a second event shape would slip in one field at a time.
        """
        if not isinstance(d, dict):
            raise EventShapeError(f"expected a JSON object, got {type(d).__name__}")
        known = {f.name for f in fields(cls)}
        extra = sorted(set(d) - known)
        if extra:
            raise EventShapeError(f"unknown field(s) {extra}; the event has exactly {sorted(known)}")
        missing = [k for k in REQUIRED if d.get(k) is None]
        if missing:
            raise EventShapeError(f"missing required field(s) {missing}")
        return cls(**d)

    def ttl_seconds(self) -> int:
        """why: readers age claims in seconds; one parser here means DI and BD never disagree on '8m'.
        boundary: reads ttl only; the validator already guaranteed its shape.
        ugly: none left at this point: '0s' and '8 min' were refused when the event was made.
        """
        number, unit = _TTL.match(self.ttl).groups()
        return int(number) * _TTL_UNIT_S[unit]

    def observed_utc(self) -> datetime:
        """why: age = now - observed_at needs a real timezone-aware datetime, parsed the same way everywhere.
        boundary: converts, never guesses; the validator already refused timestamps without a zone.
        ugly: Python 3.10 cannot parse a trailing Z (3.11 can), and the simulator writes exactly that.
        """
        text = self.observed_at[:-1] + "+00:00" if self.observed_at.endswith("Z") else self.observed_at
        return datetime.fromisoformat(text).astimezone(timezone.utc)
