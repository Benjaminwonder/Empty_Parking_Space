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