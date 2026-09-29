#!/usr/bin/env python3
# box: S1–S7 · lane: BD · read BRIDGES.md before editing
"""
ParkFind Simulator MVP — ground-truth World + cadence Adapters.

Why this exists
---------------
The product is "which empty stall (or smallest honest zone) should this
driver go to right now, given the age of the last observation?"
Cameras are not signed. This file is the first real feed.

Mental model (two layers, do not collapse them)
-----------------------------------------------
  World     = what is actually true in the lot, every tick of the clock.
  Adapter   = what a sensor *would have told us* at its cadence.
              Adapters don mutate the World. They only observe and emit.

The rest of ParkFind only ever sees occupancy events. Same schema a
YOLO adapter, a gate counter, or a 15-minute scrape will write later.

Run (from this folder):
  python3 sim.py
  python3 sim.py --cadence continuous,periodic_5min,hourly,event_only
  python3 sim.py --minutes 180 --tick 30

What this file does NOT do: YOLO, holds, aisle routing, a driver app.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal

# The event shape lives in the trunk package; the simulator is just one writer of it.
from parkfind.event import Cadence, OccupancyEvent, State

HERE = Path(__file__).resolve().parent
DEFAULT_LOT = HERE / "lot_commuter_north.json"
OUT_DIR = HERE / "out"


# TTL is a function of cadence. A 5-minute poll does not get a 4-second TTL.
TTL_BY_CADENCE = {
    "continuous": "15s",
    "near_live": "90s",
    "periodic_snapshot": "8m",
    "slow_snapshot": "75m",
    "event_only": "20m",
}

CONFIDENCE_BY_CADENCE = {
    "continuous": 0.97,
    "near_live": 0.92,
    "periodic_snapshot": 0.80,
    "slow_snapshot": 0.55,
    "event_only": 0.70,
}


# ---------------------------------------------------------------------------
# Lot layout
# ---------------------------------------------------------------------------

@dataclass
class Stall:
    stall_id: str
    zone_id: str
    row_id: str
    constraint: str  # "any" | "ada" | "ev"
    true_state: State = "free"
    occupied_until: datetime | None = None


def load_lot(path: Path) -> tuple[dict, list[Stall]]:
    spec = json.loads(path.read_text())
    special_ada = set(spec.get("special_stalls", {}).get("ada", []))
    special_ev = set(spec.get("special_stalls", {}).get("ev", []))
    stalls: list[Stall] = []
    for zone in spec["zones"]:
        for row in zone["rows"]:
            for n in range(1, zone["stalls_per_row"] + 1):
                sid = f"{row}-{n:02d}"
                if sid in special_ada:
                    constraint = "ada"
                elif sid in special_ev:
                    constraint = "ev"
                else:
                    constraint = "any"
                stalls.append(Stall(sid, zone["zone_id"], row, constraint))
    return spec, stalls


# ---------------------------------------------------------------------------
# World — the only place truth lives
# ---------------------------------------------------------------------------

class World:
    """Discrete-time commuter lot. Prefer nearer zones. Skip ADA/EV for regular cars."""

    def __init__(self, spec: dict, stalls: list[Stall], seed: int = 7):
        self.spec = spec
        self.lot_id = spec["lot_id"]
        self.stalls = {s.stall_id: s for s in stalls}
        self.zone_order = [z["zone_id"] for z in sorted(spec["zones"], key=lambda z: z["fill_priority"])]
        self.rng = random.Random(seed)
        self.arrivals = 0
        self.departures = 0
        # Last tick's flips, so the continuous adapter can emit only changes.
        self.last_flips: list[tuple[str, State, State]] = []

    def free_regular(self) -> list[Stall]:
        out = []
        for zid in self.zone_order:
            for s in self.stalls.values():
                if s.zone_id == zid and s.true_state == "free" and s.constraint == "any":
                    out.append(s)
        return out

    def counts(self) -> dict:
        by_zone: dict[str, dict[str, int]] = {}
        for s in self.stalls.values():
            z = by_zone.setdefault(s.zone_id, {"free": 0, "occupied": 0, "ada_free": 0, "ev_free": 0, "total": 0})
            z["total"] += 1
            z[s.true_state] = z.get(s.true_state, 0) + 1
            if s.true_state == "free" and s.constraint == "ada":
                z["ada_free"] += 1
            if s.true_state == "free" and s.constraint == "ev":
                z["ev_free"] += 1
        occupied = sum(1 for s in self.stalls.values() if s.true_state == "occupied")
        return {
            "lot_id": self.lot_id,
            "total": len(self.stalls),
            "occupied": occupied,
            "free": len(self.stalls) - occupied,
            "zones": by_zone,
        }

    def arrival_rate_per_tick(self, t: datetime, tick_s: int) -> float:
        """Weekday commuter shape: steep 7–9, then taper. Scaled to tick length."""
        hour = t.hour + t.minute / 60.0
        # cars per hour targeting this 120-stall lot
        if hour < 6.5:
            per_hour = 4
        elif hour < 7.0:
            per_hour = 18
        elif hour < 8.0:
            per_hour = 48
        elif hour < 9.0:
            per_hour = 36
        elif hour < 10.0:
            per_hour = 14
        else:
            per_hour = 6
        return per_hour * (tick_s / 3600.0)

    def stay_minutes(self) -> int:
        # Mix of all-day commuters and short class hops so stalls actually flip.
        if self.rng.random() < 0.25:
            return self.rng.randint(50, 110)
        return self.rng.randint(240, 480)

    def step(self, t: datetime, tick_s: int) -> None:
        self.last_flips = []

        # Departures first — a leaving car frees a stall before the next arrival picks.
        for s in self.stalls.values():
            if s.true_state == "occupied" and s.occupied_until is not None and s.occupied_until <= t:
                self.last_flips.append((s.stall_id, "occupied", "free"))
                s.true_state = "free"
                s.occupied_until = None
                self.departures += 1

        expected = self.arrival_rate_per_tick(t, tick_s)
        # Deterministic Poisson-ish: split expected into 0/1/2 arrivals.
        n_arrive = 0
        roll = self.rng.random()
        if roll < min(expected, 0.95):
            n_arrive = 1
            if expected > 1.0 and self.rng.random() < (expected - 1.0):
                n_arrive = 2

        for _ in range(n_arrive):
            candidates = self.free_regular()
            if not candidates:
                break  # lot full of regular stalls; we do not dump regular cars into ADA/EV
            stall = candidates[0]  # nearest-zone first — this is why people circle the near rows
            self.last_flips.append((stall.stall_id, "free", "occupied"))
            stall.true_state = "occupied"
            stall.occupied_until = t + timedelta(minutes=self.stay_minutes())
            self.arrivals += 1


# ---------------------------------------------------------------------------
# Adapters — observe World, emit events, never write back
# ---------------------------------------------------------------------------

class Adapter:
    cadence_class: Cadence
    source: str

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        raise NotImplementedError


class ContinuousAdapter(Adapter):
    """Stall-level. Emits only on flips. This is the 'we have a live lot camera' case."""

    cadence_class: Cadence = "continuous"
    source = "sim.continuous"

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        events = []
        iso = _iso(t)
        for stall_id, _old, new in world.last_flips:
            stall = world.stalls[stall_id]
            events.append(
                OccupancyEvent(
                    stall_id=stall_id,
                    zone_id=stall.zone_id,
                    lot_id=world.lot_id,
                    state=new,
                    confidence=CONFIDENCE_BY_CADENCE[self.cadence_class],
                    source=self.source,
                    observed_at=iso,
                    ttl=TTL_BY_CADENCE[self.cadence_class],
                    cadence_class=self.cadence_class,
                )
            )
        return events


class SnapshotAdapter(Adapter):
    """Poll every N minutes. Emits every stall (5-min) or every zone (hourly)."""

    def __init__(self, every_min: int, grain: Literal["stall", "zone"], cadence_class: Cadence, source: str):
        self.every_min = every_min
        self.grain = grain
        self.cadence_class = cadence_class
        self.source = source
        self._last_fire_minute: int | None = None

    def due(self, t: datetime) -> bool:
        minute_index = t.hour * 60 + t.minute
        bucket = minute_index // self.every_min
        if self._last_fire_minute == bucket:
            return False
        # Fire at the top of a bucket, once.
        if minute_index % self.every_min != 0:
            return False
        self._last_fire_minute = bucket
        return True

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        if not self.due(t):
            return []
        iso = _iso(t)
        ttl = TTL_BY_CADENCE[self.cadence_class]
        conf = CONFIDENCE_BY_CADENCE[self.cadence_class]
        events: list[OccupancyEvent] = []
        if self.grain == "stall":
            for s in world.stalls.values():
                events.append(
                    OccupancyEvent(
                        stall_id=s.stall_id,
                        zone_id=s.zone_id,
                        lot_id=world.lot_id,
                        state=s.true_state,
                        confidence=conf,
                        source=self.source,
                        observed_at=iso,
                        ttl=ttl,
                        cadence_class=self.cadence_class,
                    )
                )
        else:
            counts = world.counts()["zones"]
            for zid, c in counts.items():
                # Zone snapshot: occupied if the zone is mostly full; else free.
                # Honest product rule later: do not pin a stall from this.
                state: State = "occupied" if c.get("free", 0) == 0 else "free"
                events.append(
                    OccupancyEvent(
                        stall_id=None,
                        zone_id=zid,
                        lot_id=world.lot_id,
                        state=state,
                        confidence=conf,
                        source=self.source,
                        observed_at=iso,
                        ttl=ttl,
                        cadence_class=self.cadence_class,
                        note=f"free={c.get('free', 0)} occupied={c.get('occupied', 0)} total={c['total']}",
                    )
                )
        return events


class EventOnlyAdapter(Adapter):
    """Gate counter. +1 / −1 lot movement. Cannot name a stall."""

    cadence_class: Cadence = "event_only"
    source = "sim.gate"

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        events = []
        iso = _iso(t)
        for stall_id, old, new in world.last_flips:
            if old == new:
                continue
            direction = "+1 occupied" if new == "occupied" else "-1 occupied"
            events.append(
                OccupancyEvent(
                    stall_id=None,
                    zone_id=None,
                    lot_id=world.lot_id,
                    state=new,
                    confidence=CONFIDENCE_BY_CADENCE[self.cadence_class],
                    source=self.source,
                    observed_at=iso,
                    ttl=TTL_BY_CADENCE[self.cadence_class],
                    cadence_class=self.cadence_class,
                    note=f"gate {direction}; hidden stall was {stall_id}",
                )
            )
        return events


# ---------------------------------------------------------------------------
# Snapshot the rest of the stack will read (not the World)
# ---------------------------------------------------------------------------

def live_snapshot(events: list[OccupancyEvent], world_counts: dict, t: datetime) -> dict:
    """Last event per stall/zone from the *adapters*, plus a world-truth sidecar for tests."""
    by_key: dict[str, dict] = {}
    for e in events:
        key = e.stall_id or f"zone:{e.zone_id}" if e.zone_id else f"lot:{e.lot_id}"
        by_key[key] = e.to_json()
    return {
        "as_of": _iso(t),
        "world_truth": world_counts,  # test-only. Production snapshot must not include this.
        "last_seen": by_key,
    }


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CADENCE_PRESETS = {
    "continuous": lambda: ContinuousAdapter(),
    "periodic_5min": lambda: SnapshotAdapter(5, "stall", "periodic_snapshot", "sim.snapshot_5min"),
    "periodic_15min": lambda: SnapshotAdapter(15, "stall", "periodic_snapshot", "sim.snapshot_15min"),
    "hourly": lambda: SnapshotAdapter(60, "zone", "slow_snapshot", "sim.hourly_zone"),
    "event_only": lambda: EventOnlyAdapter(),
}


def run(lot_path: Path, start: datetime, minutes: int, tick_s: int, cadence_names: list[str], seed: int) -> dict:
    spec, stalls = load_lot(lot_path)
    world = World(spec, stalls, seed=seed)
    adapters = [CADENCE_PRESETS[name]() for name in cadence_names]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    feed_path = OUT_DIR / "feed.jsonl"
    snap_path = OUT_DIR / "snapshot.json"

    all_events: list[OccupancyEvent] = []
    t = start
    end = start + timedelta(minutes=minutes)
    printed_hhmm: set[str] = set()

    with feed_path.open("w") as feed:
        while t <= end:
            world.step(t, tick_s)
            batch: list[OccupancyEvent] = []
            for ad in adapters:
                batch.extend(ad.emit(world, t))
            for e in batch:
                feed.write(json.dumps(e.to_json()) + "\n")
            all_events.extend(batch)

            hhmm = t.strftime("%H:%M")
            minutes_from_start = int((t - start).total_seconds() // 60)
            if minutes_from_start % 15 == 0 and t.second == 0 and hhmm not in printed_hhmm:
                printed_hhmm.add(hhmm)
                c = world.counts()
                z = c["zones"]
                print(
                    f"{hhmm}  occ {c['occupied']:3d}/{c['total']}   "
                    + "  ".join(f"{zid}:{z[zid].get('occupied', 0)}/{z[zid]['total']}" for zid in world.zone_order)
                    + f"   events_so_far={len(all_events)}"
                )
            t += timedelta(seconds=tick_s)

    snap = live_snapshot(all_events, world.counts(), end)
    snap_path.write_text(json.dumps(snap, indent=2))
    return {
        "feed_path": str(feed_path),
        "snapshot_path": str(snap_path),
        "event_count": len(all_events),
        "arrivals": world.arrivals,
        "departures": world.departures,
        "truth": world.counts(),
        "by_source": _count_by(all_events, "source"),
        "by_cadence": _count_by(all_events, "cadence_class"),
    }


def _count_by(events: Iterable[OccupancyEvent], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in events:
        k = getattr(e, attr)
        out[k] = out.get(k, 0) + 1
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="ParkFind occupancy-event simulator")
    p.add_argument("--lot", default=str(DEFAULT_LOT))
    p.add_argument("--cadence", default="continuous,periodic_5min,hourly,event_only",
                   help="comma list: continuous,periodic_5min,periodic_15min,hourly,event_only")
    p.add_argument("--minutes", type=int, default=180, help="simulated minutes from --start")
    p.add_argument("--tick", type=int, default=30, help="world tick seconds")
    p.add_argument("--start", default="2026-09-21T06:30:00")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    names = [n.strip() for n in args.cadence.split(",") if n.strip()]
    unknown = [n for n in names if n not in CADENCE_PRESETS]
    if unknown:
        raise SystemExit(f"unknown cadence {unknown}. choose from {list(CADENCE_PRESETS)}")

    print(f"lot={args.lot}")
    print(f"window={start.isoformat()} +{args.minutes}m  tick={args.tick}s  seed={args.seed}")
    print(f"cadences={names}")
    print()
    result = run(Path(args.lot), start, args.minutes, args.tick, names, args.seed)
    print()
    print(f"arrivals={result['arrivals']}  departures={result['departures']}  events={result['event_count']}")
    print(f"by_source    {result['by_source']}")
    print(f"by_cadence   {result['by_cadence']}")
    print(f"feed         {result['feed_path']}")
    print(f"snapshot     {result['snapshot_path']}")
    print()
    print("Lesson: open feed.jsonl and compare a continuous flip at 08:12")
    print("with the next 5-min snapshot and the next hourly zone rollup.")
    print("Same World. Four different claims about it.")


if __name__ == "__main__":
    main()
