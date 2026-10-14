# box: G6 · lane: BD · read BRIDGES.md before editing
"""
Confirmations: what drivers' taps tell us about a camera's photos, kept as labels to learn from.

  "I've parked" and the camera agrees        -> occupied, on the photo that saw the car
  "No, not me" / taken (someone else's car)  -> occupied, on the photo that saw it
  "I've left" after a confirmed arrival      -> free, on the first photo after leaving (joined by labels.py)
  "I've parked" the camera never confirms    -> disputed: kept for review, not trained on
  "There's a car in it" (camera said free)   -> occupied: the camera was wrong, the error drivers feel most

The same rows feed a health check per camera (TeamVote V-9): over its last 50 confirmations, how often
drivers contradicted it. Rising disagreement means a camera drifting (moved mount, new tree, glare) days
before there would be enough labels to retrain it.

Only readings from real cameras (source camera.*) become labels. A demo car (demo.car) is our own
invention: a label from it would teach the camera what we made up. Appended to out/<run>/labels.jsonl,
never read by the server again; labels.py joins them to photos for vision.py.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path

AGREE = ("driver_and_camera", "someone_else")            # a driver saw what the camera saw
DISAGREE = ("driver_found_car", "disputed_not_seen")     # a driver contradicted the camera
HEALTH_WINDOW = 50       # the last 50 confirmations per camera
HEALTH_MIN = 10          # fewer than this says nothing yet
HEALTH_MIN_BAD = 2       # and one contradiction alone is never "drift": one driver can be wrong
HEALTH_FLOOR = 0.10      # flag at 10% disagreement, or twice the camera's graded error if that is higher


def from_camera(stall: dict) -> bool:
    """True for a stall whose newest reading came from a real camera (not a simulator, a driver or a demo car)."""
    return str(stall.get("source") or "").startswith("camera.")


class LabelLog:
    """Append-only log of drivers' confirmations (one JSON object per line)."""

    def __init__(self, path: Path | None, graded: dict[str, float] | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._graded = graded or {}                       # lot_id -> the camera's graded named-spot error
        self._recent: dict[str, deque] = {}               # lot_id -> last HEALTH_WINDOW agree (True) / disagree (False)
        if path is not None and path.exists():            # a restart keeps the history: the log is the memory
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                self._count(row["stall_id"], row["evidence"])

    def add(self, stall_id: str, label: str, evidence: str, stall: dict | None = None, after: str | None = None) -> None:
        """why: one confirmation, with the photo it is about (the camera reading's time) or the time to look after.
        boundary: writes one line to the log file; refuses anything not tied to a real camera reading.
        ugly: a missing log path (tests) makes this a no-op, never an error in the driver's request.
        """
        if self._path is None:
            return
        if stall is not None and not from_camera(stall):
            return
        row = {"stall_id": stall_id, "label": label, "evidence": evidence,
               "observed_at": stall.get("observed_at") if stall else None, "after": after,
               "camera": stall.get("source") if stall else None}
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        self._count(stall_id, evidence)

    def _count(self, stall_id: str, evidence: str) -> None:
        if evidence in AGREE or evidence in DISAGREE:
            with self._lock:
                self._recent.setdefault(stall_id.split(":", 1)[0], deque(maxlen=HEALTH_WINDOW)).append(evidence in AGREE)

    def health(self) -> dict[str, dict]:
        """why: per camera lot, how often drivers lately contradicted the camera, and whether that is a warning.
        boundary: reads only what this log has seen; the threshold is max(10%, twice the camera's graded error).
        ugly: under HEALTH_MIN confirmations, or with a single contradiction, a camera is never flagged.
        """
        out = {}
        with self._lock:
            for lot_id, recent in self._recent.items():
                n, bad = len(recent), sum(1 for ok in recent if not ok)
                limit = max(HEALTH_FLOOR, 2 * self._graded.get(lot_id, 0.0))
                out[lot_id] = {"confirmations": n, "disagree": bad, "rate": round(bad / n, 3) if n else 0.0,
                               "limit": round(limit, 3),
                               "flag": n >= HEALTH_MIN and bad >= HEALTH_MIN_BAD and bad / n >= limit}
        return out
