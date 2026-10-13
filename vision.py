#!/usr/bin/env python3
# box: A1 · lane: BD · read BRIDGES.md before editing
"""
ParkFind vision adapter: photos in, occupancy events out.

This is the first real sensor. It replaces a simulated camera, not the trunk: it writes the same
OccupancyEvent (parkfind/event.py) the simulator writes, so DI's reader and DK's page cannot
tell, and do not need to.

  camera file (cameras/<lot>.json)   which lot, the photos, one polygon per Stetson stall
                                      (made from PKLot by pklot_cameras.py)
  -> out/cameras/<lot>.npz           what it learned: each stall's empty look + the car/no-car line
  -> out/vision/<lot>.jsonl          one event per stall per photo, stamped with the photo's time

How a stall is read: we keep a picture of each stall when it is empty (built from the tuning
photos, where people labelled it empty), and measure how different the current photo looks,
plus how much edge detail it has (cars have windows, wheels, outlines). One small model per
camera turns those two numbers into "occupied" or "free", and it leans to "occupied" when
unsure: telling a driver a taken spot is free is the expensive mistake.

Tuning uses other days than the one drivers see, and every run is graded against the people's
labels for the replayed day; the grade is printed, not hidden.

Pillow and NumPy are allowed here and only here. Nothing in parkfind/ imports them.

  python vision.py --camera cameras/sage.json            # learn if needed, then read the replayed day
  python vision.py --camera cameras/sage.json --retrain  # learn again from the tuning photos
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from parkfind.event import CADENCES, OccupancyEvent

HERE = Path(__file__).resolve().parent
WRONG_FREE_LIMIT = 0.05   # at most 1 in 20 "free" calls may be wrong, measured across the tuning days


def load_camera(path: Path) -> dict:
    """why: one camera's view of one lot: which lot, the photos, and where each stall sits in the picture.
    boundary: reads the camera file only; stall ids are lot-local (A-01) and become lot:A-01 in events.
    ugly: polygons are in pixels of image_size; a photo of any other size would put every stall in the wrong place.
    """
    cam = json.loads(path.read_text(encoding="utf-8"))
    for key in ("camera_id", "lot_id", "image_size", "cadence_class", "ttl", "utc_offset", "spaces",
                "replay_date", "tuning", "replay"):
        if key not in cam:
            raise SystemExit(f"{path.name}: missing {key!r}")
    if cam["cadence_class"] not in CADENCES:
        raise SystemExit(f"{path.name}: cadence_class {cam['cadence_class']!r} is not one of {CADENCES}")
    stalls = [s["stall"] for s in cam["spaces"]]
    if len(stalls) != len(set(stalls)):
        raise SystemExit(f"{path.name}: a stall id appears twice")
    return cam


def offset_tz(text: str) -> timezone:
    """why: the replay day is in the lot's local time; events need UTC.
    boundary: parses '+hh:mm' / '-hh:mm' only; no zone names, so no tz database on Windows.
    ugly: a fixed offset ignores daylight saving, like the rest of the trunk.
    """
    m = re.match(r"^([+-])(\d{2}):(\d{2})$", text)
    if not m:
        raise SystemExit(f"utc_offset {text!r} must look like -04:00")
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def observed_at(cam: dict, photo: dict) -> str:
    """why: observed_at must be when the photo was taken, moved onto the replay day at the same clock time.
    boundary: reads the photo's local clock time and the camera's replay date and offset.
    ugly: a 2013 photo at 08:25 becomes 08:25 on the replay day; the date is the only thing that changes.
    """
    local = datetime.fromisoformat(f"{cam['replay_date']}T{photo['local_time']}").replace(tzinfo=offset_tz(cam["utc_offset"]))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stall_shapes(cam: dict) -> list[tuple[str, int, int, int, int, np.ndarray]]:
    """why: each stall's box in the picture and its exact shape inside the box, worked out once.
    boundary: pure geometry from the camera file; never looks at a photo.
    ugly: a polygon partly off the picture is clipped to it.
    """
    w, h = cam["image_size"]
    out = []
    for s in cam["spaces"]:
        xs = [p[0] for p in s["polygon"]]
        ys = [p[1] for p in s["polygon"]]
        x0, y0 = max(0, int(min(xs))), max(0, int(min(ys)))
        x1, y1 = min(w, int(max(xs)) + 1), min(h, int(max(ys)) + 1)
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in s["polygon"]], fill=1)
        out.append((s["stall"], x0, y0, x1, y1, np.asarray(mask, dtype=bool)))
    return out


def crops(path: Path, cam: dict, shapes) -> list[tuple[np.ndarray, float]] | None:
    """why: each stall's patch of one photo, brightness-normalised, plus its edge detail.
    boundary: reads one image; returns None for a photo of the wrong size instead of stretching it.
    ugly: normalising brightness makes a cloud passing over count as nothing, which is the point.
    """
    with Image.open(path) as im:
        if list(im.size) != list(cam["image_size"]):
            return None
        gray = np.asarray(im.convert("L"), dtype=np.float32)
    out = []
    for _, x0, y0, x1, y1, m in shapes:
        c = gray[y0:y1, x0:x1]
        e = np.abs(np.diff(c, axis=1, append=c[:, -1:])) + np.abs(np.diff(c, axis=0, append=c[-1:, :]))
        v = c[m]
        out.append(((c - v.mean()) / (v.std() + 1e-6), float(e[m].mean())))
    return out


def features(patches, refs, shapes) -> np.ndarray:
    """why: the two numbers the model reads per stall: how unlike its empty self it looks, and its edge detail.
    boundary: arithmetic on patches; refs are the stalls' empty looks from training.
    """
    return np.array([[float(np.abs(z - r)[s[5]].mean()), e] for (z, e), r, s in zip(patches, refs, shapes)])


def train(cam: dict, shapes, model_path: Path) -> None:
    """why: learn each stall's empty look and the car/no-car line from the tuning photos and their labels.
    boundary: reads tuning photos only; writes model_path. The replayed day is never used here.
    ugly: a stall never labelled empty on the tuning days has no empty look; training stops and says which.
    """
    sids = [str(s["space_id"]) for s in cam["spaces"]]
    seen, days = [], []
    for photo in cam["tuning"]:
        p = crops(HERE / photo["file"], cam, shapes)
        if p is not None:
            seen.append((p, [photo["labels"][sid] for sid in sids]))
            days.append(photo.get("day", Path(photo["file"]).name[:10]))
    refs = []
    for k, (stall, *_rest) in enumerate(shapes):
        empty = [p[k][0] for p, labels in seen if labels[k] == 0]
        if len(empty) < 3:
            raise SystemExit(f"{cam['lot_id']}:{stall} was never seen empty on the tuning days; pick other days")
        refs.append(np.median(np.stack(empty), axis=0))
    X = np.concatenate([features(p, refs, shapes) for p, _ in seen])
    y = np.concatenate([np.array(labels) for _, labels in seen]).astype(float)
    day = np.concatenate([np.full(len(sids), d) for (_, _), d in zip(seen, days)])

    # How cautious this camera must be, decided on the tuning days alone: learn on one day, read the
    # other, and take the lowest "occupied" line that keeps wrong "free" calls under the limit.
    probs = np.zeros(len(y))
    for d in set(days):
        fit = fit_line(X[day != d], y[day != d])
        probs[day == d] = fit(X[day == d])
    caution = 0.05   # if no line meets the limit, be as cautious as the model allows
    for t in np.arange(0.05, 0.51, 0.01):
        free = probs <= t
        if free.sum() and (y[free] == 1).mean() <= WRONG_FREE_LIMIT:
            caution = float(t)   # the highest line that still meets the limit: as many honest "free" as possible
    w, mu, sd = fit_line(X, y, raw=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(model_path, w=w, mu=mu, sd=sd, caution=caution, refs=np.array(refs, dtype=object))
    print(f"  learned from {len(seen)} tuning photos ({int(y.sum())} occupied / {int(len(y) - y.sum())} free stall views); "
          f"says occupied above {caution:.2f}")


def fit_line(X: np.ndarray, y: np.ndarray, raw: bool = False):
    """why: the car/no-car line: logistic regression on the two numbers, plain gradient descent, no library.
    boundary: numbers in; returns either a predictor or (with raw) the weights and scaling to save.
    """
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = np.c_[(X - mu) / sd, np.ones(len(X))]
    w = np.zeros(3)
    for _ in range(800):
        q = 1 / (1 + np.exp(-Z @ w))
        w -= 0.5 * Z.T @ (q - y) / len(y)
    if raw:
        return w, mu, sd
    return lambda Xb: 1 / (1 + np.exp(-(np.c_[(Xb - mu) / sd, np.ones(len(Xb))] @ w)))


def classify(prob: float, caution: float) -> tuple[str, float]:
    """why: turn the model's 'probably a car' into a state and an honest confidence.
    boundary: numbers in, decision out; the only function a better model needs to replace.
    ugly: the line sits at the camera's own caution (below 0.5): when unsure we say occupied.
    """
    state = "occupied" if prob > caution else "free"
    confidence = prob if state == "occupied" else 1 - prob
    return state, round(min(0.99, max(0.5, confidence)), 2)


def main() -> None:
    """why: one camera: learn if needed, read every replayed photo, write its events, grade it.
    boundary: reads the camera file and photos; writes out/cameras/<lot>.npz and out/vision/<lot>.jsonl.
    ugly: the people's labels for the replayed day are used ONLY for the grade (and the gate), never for a state.
    """
    ap = argparse.ArgumentParser(description="ParkFind vision adapter")
    ap.add_argument("--camera", required=True, help="camera file, e.g. cameras/sage.json")
    ap.add_argument("--out", default="out/vision", help="folder for <lot>.jsonl")
    ap.add_argument("--retrain", action="store_true", help="learn again from the tuning photos")
    args = ap.parse_args()

    cam_path = Path(args.camera)
    cam = load_camera(cam_path if cam_path.is_absolute() else HERE / cam_path)
    shapes = stall_shapes(cam)
    model_path = HERE / "out" / "cameras" / f"{cam['lot_id']}.npz"
    print(f"{cam['camera_id']} -> {cam['lot_id']} ({len(shapes)} stalls)")
    if args.retrain or not model_path.exists() or model_path.stat().st_mtime < (HERE / cam_path).stat().st_mtime:
        train(cam, shapes, model_path)
    m = np.load(model_path, allow_pickle=True)
    w, mu, sd, refs, caution = m["w"], m["mu"], m["sd"], list(m["refs"]), float(m["caution"])

    out_dir = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    feed_path = out_dir / f"{cam['lot_id']}.jsonl"
    sids = [str(s["space_id"]) for s in cam["spaces"]]
    lot = cam["lot_id"]

    # 1. read every replayed photo
    readings, skipped = [], 0
    for photo in cam["replay"]:
        patches = crops(HERE / photo["file"], cam, shapes)
        if patches is None:
            skipped += 1
            continue
        X = (features(patches, refs, shapes) - mu) / sd
        probs = 1 / (1 + np.exp(-(np.c_[X, np.ones(len(X))] @ w)))
        readings.append((photo, [classify(float(p), caution) for p in probs]))

    # 2. grade against the people's labels (used for the grade only, never for a stall's state)
    right = wrong_free = wrong_occ = said_free = said_occ = 0
    for photo, calls in readings:
        for (state, _), sid in zip(calls, sids):
            truth = photo["labels"][sid]
            if state == "free":
                said_free += 1
                wrong_free += truth == 1
            else:
                said_occ += 1
                wrong_occ += truth == 0
            right += (state == "occupied") == (truth == 1)
    total = said_free + said_occ
    free_wrong = wrong_free / max(1, said_free)

    # 3. the gate: a camera may promise single spots (near_live) only if its "free" is right 19 times in 20
    #    on a day it never learned from; otherwise it reports like a slow sensor (rows and counts, D4)
    cadence = cam["cadence_class"] if free_wrong <= WRONG_FREE_LIMIT else "periodic_snapshot"
    with feed_path.open("w", encoding="utf-8", newline="\n") as feed:
        for photo, calls in readings:
            when = observed_at(cam, photo)
            for (stall, *_rest), (state, confidence) in zip(shapes, calls):
                ev = OccupancyEvent(stall_id=f"{lot}:{stall}", zone_id=f"{lot}:{stall.split('-')[0]}", lot_id=lot,
                                    state=state, confidence=confidence, source=cam["camera_id"],
                                    observed_at=when, ttl=cam["ttl"], cadence_class=cadence)
                feed.write(json.dumps(ev.to_json()) + "\n")
    print(f"  {len(readings)} photos -> {feed_path.relative_to(HERE)} ({total} stall readings)")
    print(f"  grade vs people's labels: {100 * right / total:.1f}% right; "
          f"'free' wrong {100 * free_wrong:.1f}% of the time; 'occupied' wrong {100 * wrong_occ / max(1, said_occ):.1f}%")
    print("  gate: " + ("passed, names single spots (near_live)" if cadence == cam["cadence_class"] else
                       f"failed ('free' must be wrong at most {100 * WRONG_FREE_LIMIT:.0f}% of the time), "
                       "reports rows and counts only (periodic_snapshot)"))
    (out_dir / f"{lot}.grade.json").write_text(json.dumps({
        "camera_id": cam["camera_id"], "lot_id": lot, "right": round(right / total, 4),
        "free_wrong": round(free_wrong, 4), "occupied_wrong": round(wrong_occ / max(1, said_occ), 4),
        "cadence": cadence, "caution": caution}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
