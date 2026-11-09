#!/usr/bin/env python3
# box: T4 · lane: DI · read BRIDGES.md before editing
"""
S0-DI-3 (was DI-6): unknown is not free. Nothing older than its ttl is ever shown, or named, as free.

    python tests/test_stale.py

Makes two days with sim.py: a quick one (every lot a live camera, out/test_quick) and a slow one
(15-minute snapshots and hourly counts, out/test_slow). At every quarter hour of the morning, and
once an hour after the recording ends, it builds the status the server would serve and checks:

  - every free stall, row and lot claim is younger than its ttl; anything older reads unknown
  - a stall that never reported reads unknown
  - a named stall is free, from a live sensor, inside its ttl; every answer carries an age
  - on the slow day no answer is ever a single stall
  - an hour after the recording ends, nothing at all is free

On out/latest, when run.py built it with the PKLot photo lots, Michigan Ave (its camera failed the
gate) must never be named. Without the photos that check is skipped with a message.
Exits 1 at the first wrong answer.
"""

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from parkfind import guidance                      # noqa: E402
from parkfind.clock import parse_utc               # noqa: E402
from parkfind.lastseen import load_layout          # noqa: E402
from parkfind.server import current_status         # noqa: E402

DAYS = {
    "quick": ("out/test_quick", ["--cadence", "continuous"]),
    "slow": ("out/test_slow", ["--cadence", "periodic_15min,hourly"]),
}
START = parse_utc("2026-09-21T10:30:00Z")         # 06:30 at the lot, where sim.py starts
MOMENTS = [START + timedelta(minutes=15 * k) for k in range(13)]   # 06:30 .. 09:30
AFTER_END = START + timedelta(hours=4)             # 10:30 at the lot: an hour after the last reading


def fail(name: str, detail: str) -> None:
    print(f"FAIL {name}: {detail}")
    sys.exit(1)


def ok(name: str, detail: str = "") -> None:
    print(f"PASS {name}" + (f"  ({detail})" if detail else ""))


def make_day(out: str, args: list[str]) -> Path:
    done = subprocess.run([sys.executable, "sim.py", "--out", out, *args], cwd=HERE, capture_output=True, text=True)
    if done.returncode != 0:
        fail(f"make {out}", done.stderr.strip()[-500:])
    return HERE / out


def check_aged(day: str, status: dict, at: str) -> int:
    """why: the first rule: a reading past its ttl is unknown, never what it last said.
    boundary: stalls, rows and lot claims of one status; reads ages, changes nothing.
    ugly: last_claim keeps what the sensor said, so 'free' there is fine; only state must have moved on.
    """
    checked = 0
    for kind in ("stalls", "zones", "lot_claims"):
        for key, claim in status[kind].items():
            if claim["last_claim"] is None:
                if claim["state"] != "unknown":
                    fail("unknown is not free", f"{day} {at}: {key} never reported but reads {claim['state']}")
                continue
            checked += 1
            stale = claim["age_s"] > claim["ttl_s"]
            if stale and claim["state"] != "unknown":
                fail("unknown is not free", f"{day} {at}: {key} is {claim['age_s']:.0f}s old (ttl {claim['ttl_s']}s) "
                                            f"but reads {claim['state']}")
            if claim["state"] == "free" and stale:
                fail("unknown is not free", f"{day} {at}: {key} shown free past its ttl")
    return checked


def check_answers(day: str, status: dict, layout: dict, now, at: str) -> dict:
    """why: guidance is what a driver acts on; it must only ever name a stall a live sensor saw free in time.
    boundary: every lot x every car type at one moment.
    ugly: grain none carries no age (there is nothing to date); every other grain must.
    """
    grains = {}
    for lot in layout["lots"]:
        for vehicle in guidance.VEHICLE_CLASSES:
            answer = guidance.answer(status, layout, now, vehicle, "stale-test", lot["lot_id"])
            grain = answer["grain"]
            grains[grain] = grains.get(grain, 0) + 1
            where = f"{day} {at} {lot['lot_id']} {vehicle}"
            if grain != "none" and answer["based_on"]["age_s"] is None:
                fail("every answer has an age", f"{where}: {grain} answer with no age")
            if grain == "stall":
                stall = status["stalls"][answer["stall_id"]]
                if stall["state"] != "free" or stall["cadence_class"] not in guidance.LIVE_CADENCES \
                        or stall["age_s"] > stall["ttl_s"]:
                    fail("named stalls are live and free", f"{where}: named {answer['stall_id']} {stall}")
                if day == "slow":
                    fail("slow day never names a stall", f"{where}: named {answer['stall_id']}")
    return grains


def check_michigan_ave(layout: dict) -> None:
    """why: a camera that failed its gate (Michigan Ave, west1) may report rows and counts, never a single spot.
    boundary: out/latest only, and only when run.py merged the photo lots into it.
    ugly: most laptops have no PKLot download, so the check says it skipped rather than passing silently.
    """
    truth = HERE / "out" / "latest" / "truth.json"
    if not truth.exists():
        print("SKIP Michigan Ave never named  (no out/latest: run python run.py once)")
        return
    with truth.open(encoding="utf-8") as f:
        camera_lots = json.load(f).get("camera_lots", [])
    if "west1" not in camera_lots:
        print("SKIP Michigan Ave never named  (out/latest has no photo lots: no PKLot download in data/)")
        return
    run = HERE / "out" / "latest"
    times = [parse_utc(json.loads(line)["observed_at"]) for line in (run / "feed.jsonl").open(encoding="utf-8")]
    first, last = min(times), max(times)
    asked = 0
    now = first
    while now <= last:
        status = current_status(run, layout, now)
        for vehicle in guidance.VEHICLE_CLASSES:
            answer = guidance.answer(status, layout, now, vehicle, "stale-test", "west1")
            asked += 1
            if answer["grain"] == "stall":
                fail("Michigan Ave never named", f"{now.isoformat()} {vehicle}: named {answer['stall_id']}")
        now += timedelta(minutes=10)
    ok("Michigan Ave never named", f"{asked} answers over the replayed day, none a single stall")


def main() -> None:
    layout = load_layout()
    for day, (out, args) in DAYS.items():
        run = make_day(out, args)
        claims = 0
        grains = {}
        for now in MOMENTS + [AFTER_END]:
            at = now.strftime("%H:%MZ")
            status = current_status(run, layout, now)
            claims += check_aged(day, status, at)
            for grain, n in check_answers(day, status, layout, now, at).items():
                grains[grain] = grains.get(grain, 0) + n
        if day == "slow" and grains.get("stall"):
            fail("slow day never names a stall", f"{grains}")
        ok(f"{day} day: unknown is not free", f"{claims} readings aged at {len(MOMENTS) + 1} moments")
        ok(f"{day} day: answers", ", ".join(f"{g} {n}" for g, n in sorted(grains.items())))

        late = current_status(run, layout, AFTER_END)
        free = [k for kind in ("stalls", "zones", "lot_claims") for k, c in late[kind].items() if c["state"] == "free"]
        if free:
            fail("nothing free after the recording ends", f"{day}: {len(free)} still free, e.g. {free[:3]}")
        ok(f"{day} day: nothing free an hour after the last reading")
    check_michigan_ave(layout)
    print("ALL PASS")


if __name__ == "__main__":
    main()
