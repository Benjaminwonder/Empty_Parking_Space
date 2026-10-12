#!/usr/bin/env python3
# box: A1 · lane: BD · read BRIDGES.md before editing
"""
ParkFind vision adapter: photos in, occupancy events out.

This is the first real sensor. It replaces a simulated camera, not the trunk:
it writes the same OccupancyEvent (parkfind/event.py) the simulator writes, so
DI's reader and DK's page cannot tell, and do not need to.

  camera file (cameras/<id>.json)   which lot, image size, one polygon per stall
  frames (data/...)                 photos whose file names carry the capture time
  -> out/<run>/feed.jsonl           one event per stall per photo

The decision "is this stall occupied?" is a baseline for now: a car has edges
(windows, wheels, outlines); empty pavement mostly does not. It is crude on
purpose so the whole chain can run end to end. A trained model replaces
classify() later without touching anything else.

Pillow and NumPy are allowed here and only here. Nothing in parkfind/ imports them.

  python vision.py --camera cameras/pucpr.json --frames "data/pklot/PUCPR/**/*.jpg" --out out/vision
  python vision.py --camera cameras/pucpr.json --frames "data/pklot/PUCPR/**/*.jpg" --scores   (print raw scores)
"""

from __future__ import annotations

import argparse
import json
import re
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from parkfind.event import CADENCES, OccupancyEvent

HERE = Path(__file__).resolve().parent
# PKLot names each photo by its capture time: 2012-09-11_15_16_58.jpg (local time at the lot).
FILENAME_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})_(\d{2})_(\d{2})")


def load_camera(path: Path) -> dict:
    """why: one camera's view of one lot: which lot, what image size, and where each stall sits in the picture.
    boundary: reads the camera file only; stall ids are lot-local (A-01) and become lot:A-01 here.
    ugly: polygons are in pixels of image_size; a photo of any other size would put every stall in the wrong place.
    """
    cam = json.loads(path.read_text(encoding="utf-8"))
    for key in ("camera_id", "lot_id", "image_size", "cadence_class", "ttl", "utc_offset", "spaces"):
        if key not in cam:
            raise SystemExit(f"{path.name}: missing {key!r}")
    if cam["cadence_class"] not in CADENCES:
        raise SystemExit(f"{path.name}: cadence_class {cam['cadence_class']!r} is not one of {CADENCES}")
    stalls = [s["stall"] for s in cam["spaces"]]
    if len(stalls) != len(set(stalls)):
        raise SystemExit(f"{path.name}: a stall id appears twice")
    for s in cam["spaces"]:
        if len(s["polygon"]) < 3:
            raise SystemExit(f"{path.name}: stall {s['stall']} needs at least 3 polygon points")
    return cam


def offset_tz(text: str) -> timezone:
    """why: a photo's file name says local time at the lot; the event needs UTC.
    boundary: parses '+hh:mm' / '-hh:mm' only; no zone names, so no tz database on Windows.
    ugly: a fixed offset ignores daylight saving; Curitiba moved from -03:00 to -02:00 in late October 2012.
    """
    m = re.match(r"^([+-])(\d{2}):(\d{2})$", text)
    if not m:
        raise SystemExit(f"utc_offset {text!r} must look like -03:00")
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def frame_time(path: Path, tz: timezone) -> datetime | None:
    """why: observed_at must be when the photo was taken, never when we happened to process it.
    boundary: reads the file name only; the file's modified time is a download time and is ignored.
    ugly: a name without a timestamp, or a browser copy like '... (1).jpg', still parses; one with no time returns None and is skipped.
    """
    m = FILENAME_TIME.search(path.name)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    return datetime(y, mo, d, h, mi, s, tzinfo=tz).astimezone(timezone.utc)


def stall_masks(cam: dict) -> list[tuple[str, np.ndarray]]:
    """why: turn each stall polygon into a pixel mask once, instead of once per photo.
    boundary: pure geometry from the camera file; never looks at a photo.
    ugly: a polygon drawn partly off the image is clipped, so a stall at the edge measures fewer pixels.
    """
    w, h = cam["image_size"]
    masks = []
    for s in cam["spaces"]:
        canvas = Image.new("L", (w, h), 0)
        ImageDraw.Draw(canvas).polygon([tuple(p) for p in s["polygon"]], fill=1)
        masks.append((s["stall"], np.asarray(canvas, dtype=bool)))
    return masks


def edge_energy(gray: np.ndarray) -> np.ndarray:
    """why: the per-pixel 'how much is going on here' map the baseline decides from.
    boundary: pure arithmetic on one grayscale image.
    ugly: hard shadow lines and painted markings also count as edges; that is this baseline's main source of false 'occupied'.
    """
    gx = np.abs(np.diff(gray, axis=1, append=gray[:, -1:]))
    gy = np.abs(np.diff(gray, axis=0, append=gray[-1:, :]))
    return gx + gy


def classify(score: float, threshold: float, margin: float) -> tuple[str, float]:
    """why: turn one stall's edge score into occupied/free and an honest confidence.
    boundary: numbers in, decision out; the only function a trained model needs to replace.
    ugly: near the threshold the answer is a coin flip, so confidence there is reported near 0.5, never inflated.
    """
    state = "occupied" if score > threshold else "free"
    confidence = 0.5 + 0.45 * min(1.0, abs(score - threshold) / margin)
    return state, round(confidence, 2)


def read_frame(path: Path, cam: dict, masks, tz: timezone, threshold: float, margin: float):
    """why: one photo becomes one event per stall, all stamped with the photo's own time.
    boundary: reads one image; writes nothing; the caller decides where events go.
    ugly: a photo of the wrong size is refused rather than stretched, because stretching moves every stall.
    """
    when = frame_time(path, tz)
    if when is None:
        return None, "no capture time in file name"
    with Image.open(path) as im:
        if list(im.size) != list(cam["image_size"]):
            return None, f"size {im.size} is not the camera's {tuple(cam['image_size'])}"
        gray = np.asarray(im.convert("L"), dtype=np.float32)
    energy = edge_energy(gray)
    observed_at = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    lot = cam["lot_id"]
    events, scores = [], {}
    for stall, mask in masks:
        score = float(energy[mask].mean()) if mask.any() else 0.0
        scores[stall] = round(score, 2)
        state, confidence = classify(score, threshold, margin)
        row = stall.split("-", 1)[0]
        events.append(OccupancyEvent(
            stall_id=f"{lot}:{stall}", zone_id=f"{lot}:{row}", lot_id=lot,
            state=state, confidence=confidence, source=cam["camera_id"],
            observed_at=observed_at, ttl=cam["ttl"], cadence_class=cam["cadence_class"],
        ))
    return (events, scores), None


def main() -> None:
    """why: the command line: one camera, a set of photos, one feed file in time order.
    boundary: reads the camera file and photos; writes only out/<run>/feed.jsonl (or prints scores).
    ugly: photos arrive in any order from a download, so they are sorted by capture time, not by file name.
    """
    p = argparse.ArgumentParser(description="ParkFind vision adapter (baseline)")
    p.add_argument("--camera", required=True, help="camera file, e.g. cameras/pucpr.json")
    p.add_argument("--frames", required=True, help='photo glob under this folder, e.g. "data/pklot/PUCPR/**/*.jpg"')
    p.add_argument("--out", default="out/vision", help="run folder for feed.jsonl")
    p.add_argument("--threshold", type=float, default=None, help="edge score above which a stall is occupied")
    p.add_argument("--margin", type=float, default=None, help="score distance that earns full confidence")
    p.add_argument("--scores", action="store_true", help="print raw scores per stall instead of writing a feed")
    args = p.parse_args()

    cam = load_camera(Path(args.camera))
    threshold = args.threshold if args.threshold is not None else cam.get("threshold", 12.0)
    margin = args.margin if args.margin is not None else cam.get("margin", 6.0)
    tz = offset_tz(cam["utc_offset"])
    masks = stall_masks(cam)
    frames = sorted(HERE.glob(args.frames), key=lambda f: frame_time(f, tz) or datetime.max.replace(tzinfo=timezone.utc))
    if not frames:
        raise SystemExit(f"no photos match {args.frames!r} under {HERE}")

    out_dir = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    feed_path = out_dir / "feed.jsonl"
    written, skipped, seen = 0, 0, set()
    # --scores only prints, so it must not truncate an existing feed.
    with (nullcontext() if args.scores else feed_path.open("w", encoding="utf-8", newline="\n")) as feed:
        for f in frames:
            result, why_not = read_frame(f, cam, masks, tz, threshold, margin)
            if result is None:
                skipped += 1
                print(f"skip  {f.name}: {why_not}")
                continue
            events, scores = result
            key = events[0].observed_at
            if key in seen:  # the same moment downloaded twice ('... (1).jpg')
                skipped += 1
                print(f"skip  {f.name}: duplicate of a photo at {key}")
                continue
            seen.add(key)
            if args.scores:
                print(key, json.dumps(scores))
                continue
            for e in events:
                feed.write(json.dumps(e.to_json()) + "\n")
            written += len(events)
            occ = sum(1 for e in events if e.state == "occupied")
            print(f"{key}  {occ}/{len(events)} occupied   {f.name}")
    if not args.scores:
        print(f"\nphotos={len(frames) - skipped}  skipped={skipped}  events={written}  feed={feed_path}")


if __name__ == "__main__":
    main()
