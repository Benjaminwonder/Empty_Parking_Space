#!/usr/bin/env python3
# box: A2 · lane: BD · read BRIDGES.md before editing
"""
PKLot labels -> camera files: which photos, which spaces, which Stetson stall each space becomes.

PKLot (CC BY 4.0) is three real parking lots photographed every 5 minutes, every space labelled
by people. We play one weekday from each camera on the Stetson map, so three lots run on real
photos while the simulator covers the rest:

  UFPR05 (40 spaces)  -> sage  · Sage · Lot 33          (32 stalls)
  UFPR04 (28 spaces)  -> west1 · Michigan Ave · Lot 42  (24 stalls)
  PUCPR  (100 spaces) -> libn  · Flagler · Lot 25       (20 stalls)

Each camera file lists two sets of photos: the TUNING days (vision.py learns each stall's empty
look and its car/no-car line from these, with their labels) and the REPLAYED day (what drivers
see; its labels are kept only to grade vision.py, never to decide a stall's state).

Standard library only: this reads JSON and writes JSON. The image work is vision.py's.

    python pklot_cameras.py                 # writes cameras/sage.json, cameras/west1.json, cameras/libn.json
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKLOT = HERE / "data" / "data" / "pklot"
CAMERAS = HERE / "cameras"

# camera -> where it goes, which day drivers see, which days it learns from (busy weekday + lighter day,
# in the kinds of light the replayed day has); chosen without looking at the replayed day's labels
PLAN = {
    "ufpr05": {"lot_id": "sage", "replay": "2013-02-22", "tuning": ["2013-03-11", "2013-03-02"]},
    # tuning covers sunny and cloudy light: tuned on sunny days only, this camera misread a cloudy day
    "ufpr04": {"lot_id": "west1", "replay": "2013-01-22", "tuning": ["2013-01-21", "2013-01-17", "2012-12-14"]},
    "pucpr": {"lot_id": "libn", "replay": "2012-11-08", "tuning": ["2012-10-29", "2012-10-16"]},
}
REPLAY_DATE = "2026-09-21"   # the simulator's day; photos keep their clock time on this date
IMAGE_SIZE = [1280, 720]


def lot_stalls(campus: dict, lot_id: str) -> list[str]:
    """why: the Stetson stall ids a camera must fill, in row order (A-01, A-02, ... B-01, ...).
    boundary: reads campus.json; the camera never invents a stall.
    ugly: a lot larger than its camera's dataset would be left partly empty; refused here instead.
    """
    lot = next(l for l in campus["lots"] if l["lot_id"] == lot_id)
    return [f"{row}-{n:02d}" for row in lot["rows"] for n in range(1, lot["stalls_per_row"] + 1)]


def choose_spaces(tuning_rows: list[dict], count: int) -> list[int]:
    """why: a camera sees more spaces than its Stetson lot has stalls; keep the ones that actually
            change during the day, so the lot looks alive, chosen from the TUNING days only.
    boundary: counts label changes on tuning photos; never looks at the replayed day.
    ugly: ties go to the lower space id, so the choice is the same on every machine.
    """
    changes: dict[int, int] = {}
    last: dict[int, str] = {}
    for x in tuning_rows:
        for p in x["parking_spaces"]["polylines"]:
            sid, state = p["space_id"], p["occupancy_status"]
            if sid in last and last[sid] != state:
                changes[sid] = changes.get(sid, 0) + 1
            changes.setdefault(sid, 0)
            last[sid] = state
    ranked = sorted(changes, key=lambda sid: (-changes[sid], sid))[:count]
    return sorted(ranked)   # dataset numbering runs along the rows, so this keeps neighbours together


def photo_entry(x: dict, spaces: list[int]) -> dict:
    """why: one photo as vision.py needs it: the file, its clock time, and the people's labels.
    boundary: copies from samples.json; labels are 1 for occupied, 0 for free.
    ugly: PKLot marks times with Z, but they are local time at the lot; we keep only the clock time.
    """
    labels = {str(p["space_id"]): 1 if p["occupancy_status"] == "occupied" else 0
              for p in x["parking_spaces"]["polylines"] if p["space_id"] in spaces}
    return {"file": str(Path("data/data/pklot") / x["filepath"]).replace("\\", "/"),
            "local_time": x["parking_timestamp"]["$date"][11:19], "labels": labels}


def main() -> None:
    """why: write the three camera files vision.py and run.py read.
    boundary: reads data/data/pklot/samples.json and campus.json; writes cameras/*.json only.
    ugly: without the PKLot download this stops with a clear message; nothing else depends on it.
    """
    samples = PKLOT / "samples.json"
    if not samples.exists():
        raise SystemExit(f"{samples.relative_to(HERE)} not found: download PKLot first (README, Data credits).")
    rows = json.loads(samples.read_text(encoding="utf-8"))["samples"]
    campus = json.loads((HERE / "campus.json").read_text(encoding="utf-8"))
    CAMERAS.mkdir(exist_ok=True)
    for source, plan in PLAN.items():
        def day(d: str) -> list[dict]:
            return sorted((x for x in rows if x["source"] == source and x["parking_timestamp"]["$date"][:10] == d),
                          key=lambda x: x["parking_timestamp"]["$date"])
        stalls = lot_stalls(campus, plan["lot_id"])
        tuning = [x for d in plan["tuning"] for x in day(d)]
        replay = day(plan["replay"])
        spaces = choose_spaces(tuning, len(stalls))
        if len(spaces) < len(stalls):
            raise SystemExit(f"{source} has {len(spaces)} spaces, {plan['lot_id']} needs {len(stalls)}")
        geometry = {p["space_id"]: p["points"][0] for p in replay[0]["parking_spaces"]["polylines"]}
        camera = {
            "camera_id": f"camera.{source}",
            "lot_id": plan["lot_id"],
            "about": f"PKLot {source.upper()} (CC BY 4.0), replaying {plan['replay']} on {REPLAY_DATE}; "
                     f"tuned on {', '.join(plan['tuning'])}. Space ids are PKLot's; stalls are Stetson's.",
            "image_size": IMAGE_SIZE,
            "cadence_class": "near_live",   # a photo every 5 minutes (CONTRACT D4)
            "ttl": "8m",
            "utc_offset": campus["utc_offset"],
            "replay_date": REPLAY_DATE,
            "spaces": [{"stall": stall, "space_id": sid,
                        "polygon": [[round(a * IMAGE_SIZE[0], 1), round(b * IMAGE_SIZE[1], 1)] for a, b in geometry[sid]]}
                       for stall, sid in zip(stalls, spaces)],
            "tuning": [photo_entry(x, spaces) for x in tuning],
            "replay": [photo_entry(x, spaces) for x in replay],
        }
        out = CAMERAS / f"{plan['lot_id']}.json"
        out.write_text(json.dumps(camera, indent=1), encoding="utf-8")
        print(f"{out.relative_to(HERE)}  {source} -> {plan['lot_id']}: {len(stalls)} stalls, "
              f"{len(camera['tuning'])} tuning photos, {len(camera['replay'])} replayed photos")


if __name__ == "__main__":
    main()
