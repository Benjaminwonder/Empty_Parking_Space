# box: K0 · lane: BD · read BRIDGES.md before editing
"""
The clock: the one answer to "what time is it?" for the whole trunk.

Every age in ParkFind is now minus observed_at. If each function read the wall
clock itself, replaying the simulator's 06:30 morning at 22:00 would make every
claim hours old, and no test could pin a moment. So only the entry points build
a clock here, and they pass the time it gives down as an argument.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

# A zone (Z or +hh:mm) is mandatory. Fractions only as 3 or 6 digits: what Python 3.10 can read.
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3}(\d{3})?)?(Z|[+-]\d{2}:\d{2})$")


def parse_utc(text: str) -> datetime:
    """why: the only place in ParkFind that turns a timestamp string into a time.
    boundary: converts, never guesses; a string without a zone is refused, not assumed to be UTC.
    ugly: Python 3.10 cannot read a trailing Z (3.11 can), and the simulator writes exactly that.
    """
    if not isinstance(text, str) or not _ISO_UTC.match(text):
        raise ValueError(f"{text!r} is not a time with Z or an offset, e.g. 2026-09-21T08:15:00Z")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def make_clock(start: str | None = None, speed: float = 1.0) -> Callable[[], datetime]:
    """why: build the one "what time is it?" an entry point hands down: the real time, or a replay of a recorded morning.
    boundary: returns a function and keeps no global state, so two clocks in one program never interfere.
    ugly: elapsed time comes from time.monotonic, so a laptop clock change mid-demo cannot make a replay jump.
    """
    if speed < 0:
        raise ValueError(f"speed {speed} must be 0 (frozen) or more; a clock running backwards makes claims younger")
    if start is None:
        if speed != 1.0:
            raise ValueError("speed only applies to a replay; give a start time too")
        return lambda: datetime.now(timezone.utc)
    origin = parse_utc(start)
    began = time.monotonic()

    def now() -> datetime:
        return origin + timedelta(seconds=(time.monotonic() - began) * speed)

    return now
