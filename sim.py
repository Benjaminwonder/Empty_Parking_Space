#!/usr/bin/env python3
# box: S1–S7 · lane: BD · read BRIDGES.md before editing
"""
ParkFind simulator: a fake campus of lots (one World each) plus fake sensors (Adapters).

Why this exists
---------------
The product is "which empty stall (or smallest honest zone) should this
driver go to right now, given the age of the last observation?"
Cameras are not signed. This file is the first feed.

Mental model (two layers, do not collapse them)
-----------------------------------------------
  World     = what is actually true in the lot, every tick of the clock.
  Adapter   = what a sensor *would have told us* at its cadence.
              Adapters never change the World. They only observe and emit.

The rest of ParkFind only ever sees occupancy events (parkfind/event.py),
the same shape a camera, a gate counter or a 15-minute scrape will write later.

The campus layout (campus.json) lists nine lots, 200 stalls. Each lot names the
sensors it has, so one morning mixes live cameras, slow snapshots and a gate counter.

Each run writes one folder:
  out/<run>/feed.jsonl   the events, one per line: what the trunk reads
  out/<run>/truth.json   what was really true each tick: tests only, never the trunk

Run (from this folder):
  python sim.py
  python sim.py --cadence continuous --out out/quick          (every lot gets a live camera)
  python sim.py --cadence periodic_15min,hourly --out out/slow (every lot gets slow feeds)
  python sim.py --start 2026-09-21T06:30:00 --minutes 180 --tick 30

Without --cadence, each lot uses its own sensors from campus.json.
Times: --start is lot-local time (the layout's utc_offset). Events are stamped in UTC.

What this file does NOT do: YOLO, holds, aisle routing, a driver app.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Iterable, Literal

# The event shape and the timestamp reader live in the trunk package; the simulator is
# just one writer. The arrow only points this way: parkfind never imports sim.py.
from parkfind.clock import parse_utc
from parkfind.event import Cadence, OccupancyEvent, State

HERE = Path(__file__).resolve().parent
DEFAULT_CAMPUS = HERE / "campus.json"


# TTL is a function of cadence. A 5-minute poll does not get a 4-second TTL.
# These are simulated-sensor policy; a real adapter sets its own.
TTL_BY_CADENCE = {
    "continuous": "90s",   # a live camera re-reports every stall each minute; 90s survives one missed beat
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


def load_campus(path: Path) -> tuple[dict, list[tuple[dict, list[Stall]]]]:
    """why: turn the one campus layout (L0) into each lot's stalls, with ids no two lots can share.
    boundary: reads the layout only; invents no stalls, sensors or defaults for missing keys.
    ugly: a special stall, sensor or lot id that does not fit is a typo in L0 and stops the run.
    """
    campus = json.loads(path.read_text(encoding="utf-8"))
    lots: list[tuple[dict, list[Stall]]] = []
    seen_ids: set[str] = set()
    for lot in campus["lots"]:
        lid = lot["lot_id"]
        if lid in seen_ids or ":" in lid:
            raise SystemExit(f"{path.name}: lot_id {lid!r} is repeated or contains ':'")
        seen_ids.add(lid)
        bad = [x for x in lot["sensors"] if x not in CADENCE_PRESETS]
        if bad:
            raise SystemExit(f"{path.name}: lot {lid} has unknown sensors {bad}; choose from {list(CADENCE_PRESETS)}")
        special_ada = set(lot["special_stalls"].get("ada", []))
        special_ev = set(lot["special_stalls"].get("ev", []))
        stalls: list[Stall] = []
        for row in lot["rows"]:
            for n in range(1, lot["stalls_per_row"] + 1):
                local = f"{row}-{n:02d}"
                constraint = "ada" if local in special_ada else "ev" if local in special_ev else "any"
                # Each row is a zone, so guidance can say "row B at the Sage lot".
                stalls.append(Stall(f"{lid}:{local}", f"{lid}:{row}", row, constraint))
        unknown = (special_ada | special_ev) - {s.stall_id.split(":", 1)[1] for s in stalls}
        if unknown:
            raise SystemExit(f"{path.name}: lot {lid} special_stalls not in the lot: {sorted(unknown)}")
        lots.append((lot, stalls))
    return campus, lots


def lot_tz(spec: dict) -> tzinfo:
    """why: the commuter morning is a lot-local idea; 06:30 has to mean 06:30 at the lot.
    boundary: reads utc_offset from the layout; refuses rather than quietly assuming UTC.
    ugly: a fixed offset ignores daylight saving; Florida is -04:00 until early November, -05:00 after.
    """
    text = spec.get("utc_offset")
    m = re.match(r"^([+-])(\d{2}):(\d{2})$", text or "")
    if not m:
        raise SystemExit(f"layout utc_offset {text!r} must look like -04:00")
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


# ---------------------------------------------------------------------------
# World — the only place truth lives
# ---------------------------------------------------------------------------

class World:
    """Discrete-time commuter lot, one per lot. Prefer rows nearer the entrance. Skip ADA/EV for regular cars."""

    def __init__(self, lot: dict, stalls: list[Stall], seed: int = 7):
        self.lot = lot
        self.lot_id = lot["lot_id"]
        self.stalls = {s.stall_id: s for s in stalls}
        # Row order in the layout is distance from the entrance: row A fills first.
        self.zone_order = [f"{self.lot_id}:{row}" for row in lot["rows"]]
        # Arrivals were tuned for a 120-stall lot; scale by size and by how popular this lot is.
        self.demand_scale = len(stalls) / 120.0 * float(lot.get("demand", 1.0))
        self.rng = random.Random(seed)
        self.arrivals = 0
        self.departures = 0
        # Last tick's flips, so the continuous adapter can emit only changes.
        self.last_flips: list[tuple[str, State, State]] = []

    def free_regular(self) -> list[Stall]:
        """why: the stalls a regular arriving car may take, nearest zone first.
        boundary: reads World state only; never returns ADA or EV stalls.
        ugly: the World has no ADA/EV drivers yet, so those stalls stay free all run (a known gap).
        """
        out = []
        for zid in self.zone_order:
            for s in self.stalls.values():
                if s.zone_id == zid and s.true_state == "free" and s.constraint == "any":
                    out.append(s)
        return out

    def counts(self) -> dict:
        """why: true free/occupied totals per zone and for the lot, for truth.json and the hourly rollup.
        boundary: reads World state; callers outside the simulator get these numbers only through an adapter's event.
        ugly: 'free' here includes ADA and EV stalls, so a free zone count is not all space a regular car can use.
        """
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
        """why: a weekday commuter shape (steep 7–9, then taper), scaled to the tick length.
        boundary: pure function of the lot-local hour; touches no state.
        ugly: t must be lot-local; a UTC time here would put the morning rush four hours late.
        Scaled by lot size and demand, so a 14-stall lot does not get a 120-stall lot's traffic.
        """
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
        return per_hour * self.demand_scale * (tick_s / 3600.0)

    def stay_minutes(self) -> int:
        """why: a mix of all-day commuters and short class hops, so stalls actually flip back to free.
        boundary: draws from the World's seeded random generator only, so a seed replays the same morning.
        ugly: none of these leave before 50 minutes, so a 3-hour run sees few departures early on.
        """
        if self.rng.random() < 0.25:
            return self.rng.randint(50, 110)
        return self.rng.randint(240, 480)

    def step(self, t: datetime, tick_s: int) -> None:
        """why: advance the true lot by one tick: departures, then arrivals.
        boundary: the only method that changes World state; adapters only read last_flips afterwards.
        ugly: when no regular stall is free the arriving car is dropped, never parked in ADA/EV.
        """
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
    """Stall-level. Reports changes the moment they happen, plus every stall once a minute. The live-camera case."""

    cadence_class: Cadence = "continuous"
    source = "sim.continuous"
    HEARTBEAT_S = 60

    def __init__(self) -> None:
        self._last_beat: datetime | None = None

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        """why: a live camera sees every stall all the time, so its claims must stay fresh, not just its changes.
        boundary: reads last_flips and stall states; writes nothing back to the World.
        ugly: reporting changes only (the old way) let an unchanged stall expire to unknown 15s later,
        so the most certain lots looked the least certain. A heartbeat tick reports every stall, which already includes the flips.
        """
        beat = self._last_beat is None or (t - self._last_beat).total_seconds() >= self.HEARTBEAT_S
        if beat:
            self._last_beat = t
            reported = [(s.stall_id, s.true_state) for s in world.stalls.values()]
        else:
            reported = [(stall_id, new) for stall_id, _old, new in world.last_flips]
        iso = _iso(t)
        return [
            OccupancyEvent(
                stall_id=stall_id,
                zone_id=world.stalls[stall_id].zone_id,
                lot_id=world.lot_id,
                state=state,
                confidence=CONFIDENCE_BY_CADENCE[self.cadence_class],
                source=self.source,
                observed_at=iso,
                ttl=TTL_BY_CADENCE[self.cadence_class],
                cadence_class=self.cadence_class,
            )
            for stall_id, state in reported
        ]


class SnapshotAdapter(Adapter):
    """Poll every N minutes. Emits every stall (5/15-min) or every zone (hourly)."""

    def __init__(self, every_min: int, grain: Literal["stall", "zone"], cadence_class: Cadence, source: str,
                 ttl: str | None = None):
        self.every_min = every_min
        # A claim must outlive the wait for the next poll, or the lot goes unknown between polls.
        self.ttl = ttl or TTL_BY_CADENCE[cadence_class]
        self.grain = grain
        self.cadence_class = cadence_class
        self.source = source
        self._last_fire_minute: int | None = None

    def due(self, t: datetime) -> bool:
        """why: fire once at the top of each N-minute bucket, like a scheduled poll.
        boundary: reads the time and its own last-fire memory; nothing else.
        ugly: with a tick that does not land on the bucket's first minute the poll is skipped, not late.
        """
        minute_index = t.hour * 60 + t.minute
        bucket = minute_index // self.every_min
        if self._last_fire_minute == bucket:
            return False
        if minute_index % self.every_min != 0:
            return False
        self._last_fire_minute = bucket
        return True

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        """why: the slow-feed cases: every stall at a poll, or only zone counts every hour.
        boundary: reads World state at the poll moment; zone claims carry counts, never stall ids.
        ugly: a zone with one free stall is reported 'free'; free_count is what a reader must trust (D2).
        """
        if not self.due(t):
            return []
        iso = _iso(t)
        ttl = self.ttl
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
            for zid, c in world.counts()["zones"].items():
                events.append(
                    OccupancyEvent(
                        stall_id=None,
                        zone_id=zid,
                        lot_id=world.lot_id,
                        state="occupied" if c["free"] == 0 else "free",
                        confidence=conf,
                        source=self.source,
                        observed_at=iso,
                        ttl=ttl,
                        cadence_class=self.cadence_class,
                        free_count=c["free"],
                        total_count=c["total"],
                    )
                )
        return events


class EventOnlyAdapter(Adapter):
    """Gate counter. Counts cars in and out, so it knows how many are inside. Cannot name a stall."""

    cadence_class: Cadence = "event_only"
    source = "sim.gate"
    COUNT_EVERY_S = 300

    def __init__(self) -> None:
        self._inside = 0          # the gate's own running count since the lot opened (empty)
        self._last_count: datetime | None = None

    def emit(self, world: World, t: datetime) -> list[OccupancyEvent]:
        """why: the cheapest sensor: a gate that only sees cars pass, yet can still say how many are inside.
        boundary: lot-grain only; the count is the gate's own in-minus-out, never read from the World's stalls.
        ugly: the World knows which stall changed; writing it here would leak truth into the feed (X2).
        A real gate drifts (missed cars); this one is perfect, so its count is kinder than reality.
        """
        events = []
        iso = _iso(t)
        total = len(world.stalls)
        moved = False
        for _stall_id, old, new in world.last_flips:
            if old == new:
                continue
            moved = True
            self._inside += 1 if new == "occupied" else -1
            events.append(self._event(world, iso, total, "gate +1 car in" if new == "occupied" else "gate -1 car out"))
        # Report the count every few minutes even when nobody moves, so the claim does not just expire.
        if not moved and (self._last_count is None or (t - self._last_count).total_seconds() >= self.COUNT_EVERY_S):
            events.append(self._event(world, iso, total, "gate count"))
        if events:
            self._last_count = t
        return events

    def _event(self, world: World, iso: str, total: int, note: str) -> OccupancyEvent:
        free = max(0, total - self._inside)
        return OccupancyEvent(
            stall_id=None,
            zone_id=None,
            lot_id=world.lot_id,
            state="free" if free > 0 else "occupied",
            confidence=CONFIDENCE_BY_CADENCE[self.cadence_class],
            source=self.source,
            observed_at=iso,
            ttl=TTL_BY_CADENCE[self.cadence_class],
            cadence_class=self.cadence_class,
            free_count=free,
            total_count=total,
            note=note,
        )


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CADENCE_PRESETS = {
    "continuous": lambda: ContinuousAdapter(),
    "periodic_5min": lambda: SnapshotAdapter(5, "stall", "periodic_snapshot", "sim.snapshot_5min"),
    "periodic_15min": lambda: SnapshotAdapter(15, "stall", "periodic_snapshot", "sim.snapshot_15min", ttl="24m"),
    "hourly": lambda: SnapshotAdapter(60, "zone", "slow_snapshot", "sim.hourly_zone"),
    "event_only": lambda: EventOnlyAdapter(),
}


def truth_row(worlds: list[World], t: datetime) -> dict:
    """why: one tick of what was really true in every lot, so tests can check an answer against reality.
    boundary: goes only to truth.json; nothing here is ever written into the feed.
    ugly: the trunk must never open truth.json; tests are the only readers.
    """
    lots = {}
    for w in worlds:
        c = w.counts()
        lots[w.lot_id] = {
            "free": c["free"],
            "total": c["total"],
            "stalls": {sid: s.true_state for sid, s in w.stalls.items()},
            "zones": {zid: {"free": z["free"], "occupied": z["occupied"], "total": z["total"]}
                      for zid, z in c["zones"].items()},
        }
    return {"t": _iso(t), "lots": lots}


def run(campus_path: Path, out_dir: Path, start: datetime, minutes: int, tick_s: int,
        cadence_override: list[str] | None, seed: int) -> dict:
    """why: play one simulated morning across every lot and write its two files: the feed and the truth.
    boundary: writes only inside out_dir; the feed gets adapter events, the truth file gets World state.
    ugly: each lot gets its own seed (seed + position), so adding a lot changes no other lot's morning.
    """
    campus, lots = load_campus(campus_path)
    worlds: list[World] = []
    adapters: list[tuple[World, Adapter]] = []
    for i, (lot, stalls) in enumerate(lots):
        w = World(lot, stalls, seed=seed + i)
        worlds.append(w)
        # One adapter instance per lot and sensor: snapshot adapters remember when they last fired.
        for name in cadence_override or lot["sensors"]:
            adapters.append((w, CADENCE_PRESETS[name]()))

    out_dir.mkdir(parents=True, exist_ok=True)
    feed_path = out_dir / "feed.jsonl"
    truth_path = out_dir / "truth.json"

    all_events: list[OccupancyEvent] = []
    truth_ticks: list[dict] = []
    t = start
    end = start + timedelta(minutes=minutes)

    with feed_path.open("w", encoding="utf-8", newline="\n") as feed:
        while t <= end:
            for w in worlds:
                w.step(t, tick_s)
            batch: list[OccupancyEvent] = []
            for w, ad in adapters:
                batch.extend(ad.emit(w, t))
            for e in batch:
                feed.write(json.dumps(e.to_json()) + "\n")
            all_events.extend(batch)
            truth_ticks.append(truth_row(worlds, t))

            minutes_from_start = int((t - start).total_seconds() // 60)
            if minutes_from_start % 30 == 0 and t.second == 0:
                occ = sum(w.counts()["occupied"] for w in worlds)
                total = sum(len(w.stalls) for w in worlds)
                print(f"{t.strftime('%H:%M')}  occ {occ:3d}/{total}   "
                      + " ".join(f"{w.lot_id}:{w.counts()['occupied']}/{len(w.stalls)}" for w in worlds))
            t += timedelta(seconds=tick_s)

    truth = {"campus_id": campus["campus_id"], "tick_s": tick_s, "utc_offset": campus["utc_offset"], "ticks": truth_ticks}
    truth_path.write_text(json.dumps(truth, separators=(",", ":")), encoding="utf-8")
    return {
        "feed_path": str(feed_path),
        "truth_path": str(truth_path),
        "event_count": len(all_events),
        "lots": len(worlds),
        "stalls": sum(len(w.stalls) for w in worlds),
        "arrivals": sum(w.arrivals for w in worlds),
        "departures": sum(w.departures for w in worlds),
        "by_source": _count_by(all_events, "source"),
        "by_cadence": _count_by(all_events, "cadence_class"),
    }


def _count_by(events: Iterable[OccupancyEvent], attr: str) -> dict[str, int]:
    """why: the end-of-run tally per source and cadence, the quickest check that a run did what was asked.
    boundary: counts the events it is given; reads nothing else.
    ugly: an adapter that fired zero times is simply absent from the tally, not listed as 0.
    """
    out: dict[str, int] = {}
    for e in events:
        k = getattr(e, attr)
        out[k] = out.get(k, 0) + 1
    return out


def parse_start(text: str, tz: tzinfo) -> datetime:
    """why: --start is typed as lot-local time, the way anyone at the lot would say it.
    boundary: a time with no zone is read as lot-local; a time with Z or an offset is honoured and converted.
    ugly: '06:30' with no zone used to be read as 06:30 UTC, which is 2:30 a.m. in Florida.
    """
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", text):
        return datetime.fromisoformat(text).replace(tzinfo=tz)
    return parse_utc(text).astimezone(tz)


def main() -> None:
    """why: the command line: pick a lot, cadences, a window and an output folder, then run one morning.
    boundary: parses arguments and prints; the work lives in run().
    ugly: a relative --out is placed under this repo folder, so a run from another directory still lands in out/.
    """
    p = argparse.ArgumentParser(description="ParkFind occupancy-event simulator")
    p.add_argument("--campus", default=str(DEFAULT_CAMPUS))
    p.add_argument("--cadence", default=None,
                   help="override every lot's sensors, comma list: continuous,periodic_5min,periodic_15min,hourly,event_only")
    p.add_argument("--out", default="out/latest", help="run folder for feed.jsonl and truth.json (default out/latest)")
    p.add_argument("--minutes", type=int, default=180, help="simulated minutes from --start")
    p.add_argument("--tick", type=int, default=30, help="world tick seconds")
    p.add_argument("--start", default="2026-09-21T06:30:00", help="lot-local time, e.g. 2026-09-21T06:30:00")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    names = [n.strip() for n in args.cadence.split(",") if n.strip()] if args.cadence else None
    unknown = [n for n in names or [] if n not in CADENCE_PRESETS]
    if unknown:
        raise SystemExit(f"unknown cadence {unknown}. choose from {list(CADENCE_PRESETS)}")
    campus_path = Path(args.campus)
    campus, _ = load_campus(campus_path)
    start = parse_start(args.start, lot_tz(campus))
    out_dir = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out

    print(f"campus={campus_path.name}  out={out_dir.relative_to(HERE) if out_dir.is_relative_to(HERE) else out_dir}")
    print(f"window={start.isoformat()} (= {_iso(start)}) +{args.minutes}m  tick={args.tick}s  seed={args.seed}")
    print(f"sensors={'every lot: ' + ','.join(names) if names else 'per lot, from ' + campus_path.name}")
    print()
    result = run(campus_path, out_dir, start, args.minutes, args.tick, names, args.seed)
    print()
    print(f"lots={result['lots']}  stalls={result['stalls']}  arrivals={result['arrivals']}  departures={result['departures']}  events={result['event_count']}")
    print(f"by_source    {result['by_source']}")
    print(f"by_cadence   {result['by_cadence']}")
    print(f"feed         {result['feed_path']}")
    print(f"truth        {result['truth_path']}   (tests only)")


if __name__ == "__main__":
    main()
