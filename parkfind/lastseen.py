
# box: T1–T3 · lane: DI · read BRIDGES.md before editing

"""
Read occupancy events from the ParkFind feed and build the latest known
parking state.

This file belongs to the trunk/backend. It may read the canonical event feed,
but it must never read simulator truth.

DI-1: Read and validate occupancy events.
DI-2: Build freshness-aware stall, zone, and lot status.
DI-3: Generate status.json using the shared replay clock.
Campus (2026-10-12, edited by BD at the lead's request): the layout is campus.json,
nine lots; stall ids are lot:row-NN and status carries a per-lot summary for map pins.
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

from parkfind.event import OccupancyEvent, EventShapeError
from parkfind.clock import make_clock, parse_utc

# The one layout file the trunk reads, found next to the package, not the current directory.
LAYOUT_PATH = Path(__file__).resolve().parent.parent / "campus.json"


def layout_stalls(layout: dict) -> list[tuple[str, str]]:
    """
    why: List every stall the layout says exists, as (lot_id, stall_id), so a stall
    that never reported still shows up as unknown instead of disappearing.

    boundary: Reads only the layout; the feed never decides which stalls exist.

    ugly: Ids must be built exactly like the simulator and camera build them
    (lot:row-NN); one character of difference and every stall reads unknown.
    """
    found = []
    for lot in layout["lots"]:
        for row in lot["rows"]:
            for number in range(1, lot["stalls_per_row"] + 1):
                found.append((lot["lot_id"], f"{lot['lot_id']}:{row}-{number:02d}"))
    return found


def load_layout(path: Path = LAYOUT_PATH) -> dict:
    """
    why: One loader for the campus layout, shared by the CLI and the server.
    boundary: Reads campus.json only.
    ugly: A missing file stops with its full path, so a wrong working directory is obvious.
    """
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


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
    of the system sees one current, freshness-aware view of every lot.

    boundary: Reads only validated OccupancyEvents and the campus layout. It keeps
    stall, zone, and lot claims at their original grain and never reads
    simulator truth.

    ugly: A lot whose sensor only counts (hourly zone counts, a gate) has every
    stall unknown; its pin must show the count and its age instead of nothing.
    """
    latest_stalls = {}
    latest_zones = {}
    latest_lots = {}

    # Keep the newest claim by observed_at, not by file order.
    for event in events:
        if event.stall_id is not None:
            bucket, key = latest_stalls, event.stall_id
        elif event.zone_id is not None:
            bucket, key = latest_zones, event.zone_id
        elif event.lot_id is not None:
            bucket, key = latest_lots, event.lot_id
        else:
            continue
        old = bucket.get(key)
        if old is None or event.observed_utc() > old.observed_utc():
            bucket[key] = event

    stalls = {}
    lots = {}
    for lot in layout["lots"]:
        lots[lot["lot_id"]] = {"name": lot["name"], "total": 0, "free": 0,
                               "occupied": 0, "unknown": 0, "last_count": None}

    # The layout, not the feed, defines which stalls exist.
    for lot_id, stall_id in layout_stalls(layout):
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
        summary = lots[lot_id]
        summary["total"] += 1
        state = stalls[stall_id]["state"]
        summary[state if state in ("free", "occupied") else "unknown"] += 1

    zones = {
        zone_id: _claim_status(event, now)
        for zone_id, event in latest_zones.items()
    }
    lot_claims = {
        lot_id: _claim_status(event, now)
        for lot_id, event in latest_lots.items()
    }

    # A count for each pin: the lot's own count if it has one, else its rows' counts added up.
    for lot_id, summary in lots.items():
        claim = lot_claims.get(lot_id)
        if claim is not None and "free_count" in claim:
            summary["last_count"] = {k: claim[k] for k in ("free_count", "total_count", "observed_at", "age_s")}
            summary["last_count"]["state"] = "expired" if claim["state"] == "unknown" else "fresh"
            continue
        row_claims = [z for zid, z in zones.items() if zid.startswith(lot_id + ":") and "free_count" in z]
        if row_claims:
            oldest = max(row_claims, key=lambda z: z["age_s"])
            summary["last_count"] = {
                "free_count": sum(z["free_count"] for z in row_claims),
                "total_count": sum(z["total_count"] for z in row_claims),
                "observed_at": oldest["observed_at"],
                "age_s": oldest["age_s"],
                "state": "expired" if any(z["state"] == "unknown" for z in row_claims) else "fresh",
            }

    return {
        "as_of": now.isoformat(),
        "stalls": stalls,
        "zones": zones,
        "lot_claims": lot_claims,
        "lots": lots,
    }


def main() -> None:
    """
    why: Generate a reproducible SK-STATUS JSON snapshot from an occupancy feed.

    boundary: Reads SK-FEED and SK-LAYOUT using SK-CLOCK. Writes only the
    status.json output. Never reads simulator truth or changes event shapes.

    ugly: Invalid feed lines are counted rather than repaired. Future events
    are skipped so replay snapshots never contain observations from later.
    """
    parser = argparse.ArgumentParser(
        description="Generate the latest known ParkFind parking status."
    )

    parser.add_argument(
        "--run",
        required=True,
        help="Run directory containing feed.jsonl"
    )

    parser.add_argument(
        "--now",
        default=None,
        help="Replay start time in ISO 8601 format with timezone"
    )

    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Replay clock speed; 0 freezes time"
    )

    args = parser.parse_args()

    run_dir = Path(args.run)

    layout = load_layout()

    clock = make_clock(start=args.now, speed=args.speed)
    now = clock()

    events, rejected_lines = read_feed(
        run_dir / "feed.jsonl",
        now
    )

    snapshot = status(events, layout, now)
    snapshot["rejected_lines"] = rejected_lines

    output_path = run_dir / "status.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(snapshot, file, indent=2)
        file.write("\n")

    print(f"Status written to {output_path}")
    print(f"Total stalls: {len(snapshot['stalls'])}")
    print(f"Rejected lines: {rejected_lines}")


if __name__ == "__main__":
    main()
