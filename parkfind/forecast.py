# box: G5 · lane: BD · read BRIDGES.md before editing
"""
Arrival-time forecast: how many spots a lot will likely have when you get there, not now.

What the data supports today (decided 2026-10-13 on validation days, simulator seeds 11, 13, 17,
never the replayed day): the best guess for "free when you arrive" is "free now". A straight line
through the last 20 minutes was 15-25% worse on average at 5 and 10 minutes; half-strength and
falling-only versions only tied. What we can say is how much a lot moves in that time: about one
spot per 10 minutes (DRIFT_PER_MIN), so a lot with fewer free spots than its likely drift by your
arrival is flagged "may be gone" and the page prefers one with margin.

The trend is still computed and sent (per_min), and tests/score_day.py still grades it against
"stays", so the day it starts winning (more real days, real cameras) the numbers say so.

When weeks of history exist, a typical-day profile per lot and weekday belongs here too; with one
recorded day it would only be the answer key.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

LOOKBACK_MIN = (20, 10)   # past points besides now
HORIZON_MAX_MIN = 15      # beyond this a straight line says more than we know
DRIFT_PER_MIN = 0.1       # spots a lot typically moves per minute (validation days: 0.83-1.06 spots in 10 min)


def lot_counts(status: dict) -> dict[str, tuple[int, int] | None]:
    """why: the one free count per lot the forecast starts from: the same order of trust as the pins.
    boundary: reads SK-STATUS lots only: stall reads when most stalls are known, else a fresh count, else nothing.
    ugly: a lot we can't count right now gets None, never a guess; the forecast then says nothing for it.
    """
    out = {}
    for lot_id, lot in status["lots"].items():
        if lot["total"] and lot["unknown"] <= lot["total"] / 2:
            out[lot_id] = (lot["free"], lot["total"])
        elif lot.get("last_count") and lot["last_count"]["state"] == "fresh":
            c = lot["last_count"]
            out[lot_id] = (c["free_count"], c["total_count"])
        else:
            out[lot_id] = None
    return out


def trend(points: list[tuple[float, int]]) -> float:
    """Least-squares slope (spots per minute) through (minutes, free) points."""
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    return 0.0 if sxx == 0 else sum((x - mx) * (y - my) for x, y in points) / sxx


class Forecaster:
    """Counts per lot at past whole minutes, cached, so a view costs one extra status per minute at most."""

    def __init__(self, status_at) -> None:
        self._status_at = status_at          # t -> SK-STATUS from the sensors alone (no claims, reports or demo cars)
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _counts_at(self, t: datetime) -> dict:
        key = t.strftime("%Y-%m-%dT%H:%M")
        with self._lock:
            hit = self._cache.get(key)
        if hit is None:
            hit = lot_counts(self._status_at(t.replace(second=0, microsecond=0)))
            with self._lock:
                if len(self._cache) > 240:   # a few hours of minutes; older ones are never asked for again
                    self._cache.clear()
                self._cache[key] = hit
        return hit

    def forecast(self, now: datetime, current: dict) -> dict:
        """why: per lot, what the page needs to project free spots to a driver's arrival: free now, the trend, the total.
        boundary: current = lot_counts of the status being served; the past comes from the sensors alone.
        ugly: a lot unknown at any of the three moments gets no forecast: a line through a gap is a guess.
        """
        past = {m: self._counts_at(now - timedelta(minutes=m)) for m in LOOKBACK_MIN}
        out = {}
        for lot_id, cur in current.items():
            pts = [(-m, past[m].get(lot_id)) for m in LOOKBACK_MIN] + [(0, cur)]
            if any(c is None for _, c in pts):
                continue
            out[lot_id] = {"free_now": cur[0], "total": cur[1],
                           "per_min": round(trend([(x, c[0]) for x, c in pts]), 3),   # graded, not used: see top
                           "drift_per_min": DRIFT_PER_MIN, "horizon_min": HORIZON_MAX_MIN}
        return out


def project(f: dict, minutes: float) -> int:
    """Free spots expected `minutes` from now (the page does the same sum): clamped to the lot, horizon capped."""
    m = max(0.0, min(HORIZON_MAX_MIN, minutes))
    return max(0, min(f["total"], round(f["free_now"] + f["per_min"] * m)))
