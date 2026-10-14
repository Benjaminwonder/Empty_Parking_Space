#!/usr/bin/env python3
# box: A3 · lane: BD · read BRIDGES.md before editing
"""
Drivers' confirmations -> labelled camera photos that vision.py can learn from.

    python labels.py collect                 # out/latest/labels.jsonl (the server's log) -> out/labels/<lot>.json
    python labels.py simulate --p 0.3        # synthetic drivers, for the experiment (clearly marked as such)
    python vision.py --camera cameras/west1.json --model per_light --with-labels out/labels/west1.json

A confirmation is about one stall on one photo: "I've parked" agreed by the camera and "No, not me" say
a car is there (occupied); "I've left" says the stall is empty on the first photo after (free). Disputed
taps ("I've parked", never seen) are kept out unless --include-disputed. Every label file is graded
against the people's PKLot labels, so we know how often drivers are right before trusting them.

simulate: at every real arrival on the replayed day a driver confirms with probability p (occupied), at
every departure taps "I've left" with probability p (free). Real drivers only ever speak about the
moments they arrive and leave; so do these.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "labels"
JOIN_AFTER = timedelta(minutes=10)   # "I've left" counts on the first photo within 10 minutes after


def cameras() -> dict[str, dict]:
    """lot_id -> camera file contents, for every camera file on this machine."""
    return {c["lot_id"]: c for c in (json.loads(p.read_text(encoding="utf-8")) for p in sorted((HERE / "cameras").glob("*.json")))}


def photo_times(cam: dict) -> list[tuple[datetime, dict]]:
    """why: the replayed photos in time order, stamped exactly as vision.py stamps their readings.
    boundary: reuses vision.observed_at, so a label and the reading it is about always share one clock.
    ugly: imports vision (NumPy, Pillow): this tool runs where vision.py runs.
    """
    from vision import observed_at
    return sorted(((datetime.fromisoformat(observed_at(cam, ph).replace("Z", "+00:00")), ph) for ph in cam["replay"]),
                  key=lambda x: x[0])


def entry(ph: dict, labels: dict) -> dict:
    return {"file": ph["file"], "local_time": ph["local_time"], "weather": ph.get("weather"), "labels": labels}


def write(cam: dict, photos: dict[str, dict], source: str) -> None:
    """why: one file per camera: the labelled photos and how often the labels agree with the people's.
    boundary: writes out/labels/<lot>.json only.
    ugly: agreement is measured against PKLot's human labels, which a real campus will not have; there, the
          same number would come from spot checks.
    """
    rows = list(photos.values())
    n = sum(len(r["labels"]) for r in rows)
    agree = sum(r["labels"][sid] == truth for r in rows for sid, truth in r["truth"].items())
    for r in rows:
        r.pop("truth")
    occ = sum(v for r in rows for v in r["labels"].values())
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{cam['lot_id']}.json"
    out.write_text(json.dumps({"camera_id": cam["camera_id"], "lot_id": cam["lot_id"], "source": source,
                               "labels": n, "agree_with_people": round(agree / max(1, n), 4), "photos": rows},
                              indent=1), encoding="utf-8")
    print(f"{out.relative_to(HERE)}  {n} labels ({occ} occupied, {n - occ} free) on {len(rows)} photos; "
          f"agree with the people's labels {100 * agree / max(1, n):.1f}%")


def add(photos: dict, ph: dict, sid: str, value: int) -> None:
    row = photos.setdefault(ph["file"], dict(entry(ph, {}), truth={}))
    row["labels"][sid] = value
    row["truth"][sid] = ph["labels"][sid]


def collect(include_disputed: bool, log: Path) -> None:
    """why: turn the server's log of real confirmations into labelled photos.
    boundary: reads out/latest/labels.jsonl and the camera files; skips rows not tied to a camera lot here.
    ugly: an "I've left" with no photo within 10 minutes after is dropped, never stretched to a later photo.
    """
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    for lot_id, cam in cameras().items():
        times = photo_times(cam)
        by_time = {t: ph for t, ph in times}
        space = {f"{lot_id}:{s['stall']}": str(s["space_id"]) for s in cam["spaces"]}
        photos: dict = {}
        for r in rows:
            sid = space.get(r["stall_id"])
            if sid is None or (r["evidence"] == "disputed_not_seen" and not include_disputed):
                continue
            if r["label"] == "occupied" and r.get("observed_at"):
                ph = by_time.get(datetime.fromisoformat(r["observed_at"].replace("Z", "+00:00")))
            else:
                after = datetime.fromisoformat(r["after"].replace("Z", "+00:00"))
                ph = next((p for t, p in times if after < t <= after + JOIN_AFTER), None)
            if ph is not None:
                add(photos, ph, sid, 1 if r["label"] == "occupied" else 0)
        if photos:
            write(cam, photos, "drivers")
        else:
            print(f"{lot_id}: no confirmations on its camera yet")


def simulate(p: float, seed: int) -> None:
    """why: what a season of real drivers would give, to test whether learning from them helps at all.
    boundary: reads the replayed day's people's labels (the stand-in for what really happened); writes label files.
    ugly: a synthetic driver is never wrong; real ones sometimes are, so collect's agreement number matters too.
    """
    rng = random.Random(seed)
    for lot_id, cam in cameras().items():
        times = photo_times(cam)
        photos: dict = {}
        for s in cam["spaces"]:
            sid = str(s["space_id"])
            for (_, before), (_, ph) in zip(times, times[1:]):
                was, now = before["labels"][sid], ph["labels"][sid]
                if was != now and rng.random() < p:     # an arrival (0 -> 1) or a departure (1 -> 0)
                    add(photos, ph, sid, now)
        write(cam, photos, f"synthetic drivers p={p} seed={seed}")


def main() -> None:
    """why: one tool for the two ways labels arrive: real taps (collect) and the experiment (simulate).
    boundary: writes out/labels/ only; vision.py decides whether to learn from them (--with-labels).
    ugly: simulate overwrites collect's files for the same lots; they are kept apart only by their "source".
    """
    ap = argparse.ArgumentParser(description="Drivers' confirmations -> labelled camera photos")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--include-disputed", action="store_true")
    c.add_argument("--log", default=str(HERE / "out" / "latest" / "labels.jsonl"), help="the server's confirmations log")
    s = sub.add_parser("simulate")
    s.add_argument("--p", type=float, default=0.3)
    s.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    if args.cmd == "collect":
        collect(args.include_disputed, Path(args.log))
    else:
        simulate(args.p, args.seed)


if __name__ == "__main__":
    main()
