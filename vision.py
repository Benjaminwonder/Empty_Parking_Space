#!/usr/bin/env python3
# box: A1 · lane: BD · read BRIDGES.md before editing
"""
ParkFind vision adapter: photos in, occupancy events out.

This is the first real sensor. It replaces a simulated camera, not the trunk: it writes the same
OccupancyEvent (parkfind/event.py) the simulator writes, so DI's reader and DK's page cannot
tell, and do not need to.

  camera file (cameras/<lot>.json)   which lot, the photos, one polygon per Stetson stall
                                      (made from PKLot by pklot_cameras.py)
  -> out/cameras/<lot>.<model>.npz   what it learned: each stall's empty look + the car/no-car line
  -> out/vision/<lot>.jsonl          one event per stall per photo, stamped with the photo's time

How a stall is read: we keep a picture of each stall when it is empty (built from the tuning
photos, where people labelled it empty), and measure how different the current photo looks,
plus how much edge detail it has (cars have windows, wheels, outlines). One small model per
camera turns those two numbers into "occupied" or "free", and it leans to "occupied" when
unsure: telling a driver a taken spot is free is the expensive mistake.

Tuning uses other days than the one drivers see, and every run is graded against the people's
labels for the replayed day; the grade is printed, not hidden.

Two gates decide which stalls may be named to a driver (CONTRACT D4). Stall by stall, on the
tuning days: a stall the camera misreads (the far edge, glare) reports rows only, because once
the rest of the lot fills, guidance would name exactly that stall. Camera-wide, on the replayed
day: if the trusted stalls still fail, the whole camera reports rows only.

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
from parkfind.guidance import stall_types, walk_order

HERE = Path(__file__).resolve().parent
WRONG_FREE_LIMIT = 0.05   # at most 1 in 20 "free" calls may be wrong, measured across the tuning days
MIN_FREE_CALLS = 20       # a stall said "free" fewer times than this on the tuning days has no record to trust


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
    boundary: arithmetic on patches; refs[k] is a list of stall k's empty looks (one, or one per kind of light).
    ugly: with several empty looks, the nearest one counts: an empty stall under clouds should be compared with
          the stall empty under clouds, not with the sunny one.
    """
    return np.array([[min(float(np.abs(z - r)[s[5]].mean()) for r in rs), e]
                     for (z, e), rs, s in zip(patches, refs, shapes)])


MODELS = ("median", "per_light")   # one empty look per stall, or one per kind of light (sunny / cloudy / rainy)


def train(cam: dict, shapes, model_path: Path, model: str, extra: list | None = None) -> None:
    """why: learn each stall's empty look(s) and the car/no-car line from the tuning photos and their labels,
            plus drivers' confirmations when given (extra: photos where only the confirmed stalls are labelled).
    boundary: reads tuning photos (and extra); writes model_path. Validation and exam days are never used here.
    ugly: a stall never labelled empty has no empty look; training stops and says which. per_light keeps a look
          only for light seen empty at least 3 times. Confirmations count as their own "day" in the cross-day test.
    """
    sids = [str(s["space_id"]) for s in cam["spaces"]]
    seen, days, light = [], [], []
    for photo in cam["tuning"] + (extra or []):
        p = crops(HERE / photo["file"], cam, shapes)
        if p is not None:
            seen.append((p, [photo["labels"].get(sid) for sid in sids]))   # None: nobody said, for this stall
            days.append(photo.get("day", Path(photo["file"]).name[:10]))
            light.append(photo.get("weather", "unknown"))
    refs = np.empty(len(shapes), dtype=object)
    for k, (stall, *_rest) in enumerate(shapes):
        empty = [(p[k][0], w) for (p, labels), w in zip(seen, light) if labels[k] == 0]
        if len(empty) < 3:
            raise SystemExit(f"{cam['lot_id']}:{stall} was never seen empty on the tuning days; pick other days")
        looks = [np.median(np.stack([z for z, _ in empty]), axis=0)]
        if model == "per_light":
            by_light = [[z for z, w in empty if w == kind] for kind in sorted({w for _, w in empty})]
            looks = [np.median(np.stack(zs), axis=0) for zs in by_light if len(zs) >= 3] or looks
        refs[k] = looks
    feats = [features(p, refs, shapes) for p, _ in seen]
    known = [(i, k) for i, (_, labels) in enumerate(seen) for k in range(len(sids)) if labels[k] is not None]
    X = np.array([feats[i][k] for i, k in known])
    y = np.array([seen[i][1][k] for i, k in known], dtype=float)
    day = np.array([days[i] for i, _ in known])

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
    # The same test, stall by stall. A camera-wide average hides a stall the camera always misreads (glare,
    # a tree, the far edge of the picture), and guidance names exactly that stall once the rest fill up.
    stall_of = np.array([k for _, k in known])
    trusted = []
    for k in range(len(sids)):
        said_free = (stall_of == k) & (probs <= caution)
        n = int(said_free.sum())
        trusted.append(n >= MIN_FREE_CALLS and (y[said_free] == 1).mean() <= WRONG_FREE_LIMIT)
    w, mu, sd = fit_line(X, y, raw=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(model_path, w=w, mu=mu, sd=sd, caution=caution, refs=refs,
                        trusted=np.array(trusted), model=model)
    print(f"  learned from {len(seen)} photos{' (with drivers confirmations)' if extra else ''} ({int(y.sum())} occupied / {int(len(y) - y.sum())} free stall views); "
          f"says occupied above {caution:.2f}; {sum(trusted)} of {len(sids)} stalls trusted to be named")


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


def grade(cam: dict, shapes, readings, trusted) -> dict:
    """why: one way to grade any labelled day (validation, replayed, exam), so their numbers compare.
    boundary: reads the people's labels; decides nothing. "named" is the stall guidance would name per photo:
              the nearest trusted free regular stall (guidance.walk_order), which is what a driver is told.
    ugly: errors bunch where the lot fills, which is exactly where guidance names; so "named" is the number that
          gates, not the average over every reading.
    """
    lot = cam["lot_id"]
    sids = [str(s["space_id"]) for s in cam["spaces"]]
    campus = json.loads((HERE / "campus.json").read_text(encoding="utf-8"))
    types = stall_types(next(l for l in campus["lots"] if l["lot_id"] == lot))
    right = total = said_free = wrong_free = said_occ = wrong_occ = trusted_free = trusted_wrong = 0
    named = named_wrong = 0
    for photo, calls in readings:
        free_here = []
        for (stall, *_rest), (state, _), sid, ok in zip(shapes, calls, sids, trusted):
            truth = photo["labels"][sid]
            total += 1
            right += (state == "occupied") == (truth == 1)
            if state == "free":
                said_free += 1
                wrong_free += truth == 1
                trusted_free += ok
                trusted_wrong += ok and truth == 1
                if ok and types[f"{lot}:{stall}"] == "regular":
                    free_here.append((f"{lot}:{stall}", sid))
            else:
                said_occ += 1
                wrong_occ += truth == 0
        if free_here:
            _, sid = min(free_here, key=lambda f: walk_order(f[0]))
            named += 1
            named_wrong += photo["labels"][sid] == 1
    return {"photos": len(readings), "right": round(right / max(1, total), 4),
            "free_wrong": round(wrong_free / max(1, said_free), 4),
            "occupied_wrong": round(wrong_occ / max(1, said_occ), 4),
            "trusted_free_wrong": round(trusted_wrong / max(1, trusted_free), 4),
            "named": named, "named_wrong": named_wrong, "named_free_wrong": round(named_wrong / max(1, named), 4)}


def say(day: str, g: dict) -> str:
    return (f"  {day}: {100 * g['right']:.1f}% right; 'free' wrong {100 * g['free_wrong']:.1f}%; "
            f"named spot really taken {g['named_wrong']} of {g['named']} photos ({100 * g['named_free_wrong']:.1f}%)")


def main() -> None:
    """why: one camera: learn if needed, read the photos of one day, then grade, gate and write its events.
    boundary: reads the camera file and photos; writes out/cameras/<lot>.<model>.npz and out/vision/<lot>.*
              (--validate writes nothing; --exam writes only <lot>.exam.json).
    ugly: labels on the validation, replayed and exam days are used ONLY to grade (and gate), never for a state.
          Choose models with --validate; run --exam once per final model, or the exam stops being one.
    """
    ap = argparse.ArgumentParser(description="ParkFind vision adapter")
    ap.add_argument("--camera", required=True, help="camera file, e.g. cameras/sage.json")
    ap.add_argument("--out", default="out/vision", help="folder for <lot>.jsonl")
    ap.add_argument("--retrain", action="store_true", help="learn again from the tuning photos")
    ap.add_argument("--model", choices=MODELS, help="override the camera file's model (for --validate)")
    ap.add_argument("--validate", action="store_true", help="grade the validation day only; writes nothing")
    ap.add_argument("--exam", action="store_true", help="grade the exam day once; writes <lot>.exam.json")
    ap.add_argument("--with-labels", help="drivers' confirmations to learn from too (labels.py output, out/labels/<lot>.json)")
    args = ap.parse_args()

    cam_path = Path(args.camera)
    cam_path = cam_path if cam_path.is_absolute() else HERE / cam_path
    cam = load_camera(cam_path)
    model = args.model or cam.get("model", "median")
    shapes = stall_shapes(cam)
    lot = cam["lot_id"]
    extra = None
    if args.with_labels:
        given = json.loads(Path(args.with_labels).read_text(encoding="utf-8"))
        extra = [dict(ph, day="drivers") for ph in given["photos"]]
    model_path = HERE / "out" / "cameras" / f"{lot}.{model}{'.drivers' if extra else ''}.npz"
    print(f"{cam['camera_id']} -> {lot} ({len(shapes)} stalls, model {model}"
          + (f", + {sum(len(p['labels']) for p in extra)} confirmations from {given['source']})" if extra else ")"))
    if args.retrain or extra or not model_path.exists() or model_path.stat().st_mtime < cam_path.stat().st_mtime:
        train(cam, shapes, model_path, model, extra)
    m = np.load(model_path, allow_pickle=True)
    w, mu, sd, refs, caution = m["w"], m["mu"], m["sd"], list(m["refs"]), float(m["caution"])
    trusted = [bool(t) for t in m["trusted"]]

    def read(photos: list[dict]) -> list[tuple[dict, list[tuple[str, float]]]]:
        readings = []
        for photo in photos:
            patches = crops(HERE / photo["file"], cam, shapes)
            if patches is not None:
                X = (features(patches, refs, shapes) - mu) / sd
                probs = 1 / (1 + np.exp(-(np.c_[X, np.ones(len(X))] @ w)))
                readings.append((photo, [classify(float(p), caution) for p in probs]))
        return readings

    out_dir = Path(args.out) if Path(args.out).is_absolute() else HERE / args.out
    if args.validate or args.exam:
        day = "validation" if args.validate else "exam"
        g = grade(cam, shapes, read(cam.get(day, [])), trusted)
        print(say(f"{day} day", g) + f"  [{sum(trusted)} of {len(trusted)} stalls trusted]")
        if args.exam:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{lot}.exam.json").write_text(json.dumps({"camera_id": cam["camera_id"], "lot_id": lot,
                                                                  "model": model, **g}, indent=1), encoding="utf-8")
        return

    # the replayed day: read, grade, gate, write the events drivers see
    readings = read(cam["replay"])
    g = grade(cam, shapes, readings, trusted)
    if extra:
        # confirmations are labels from the replayed day itself: grading the gate there would grade the answers
        # the model was just shown, so the gate moves to the validation day (never trained on)
        g = grade(cam, shapes, read(cam["validation"]), trusted)
        print("  confirmations come from the replayed day, so the gate is graded on the validation day")
    # Two gates (D4). Per stall, from the tuning days (trusted, in training): only a stall whose "free" held up
    # there may be named. Per camera, on this unseen day: the spot guidance would name must be really free 19
    # times in 20. A stall that fails either still reports, as periodic_snapshot: counted in its row, never named.
    cadence = cam["cadence_class"] if g["named"] and g["named_free_wrong"] <= WRONG_FREE_LIMIT else "periodic_snapshot"
    out_dir.mkdir(parents=True, exist_ok=True)
    feed_path = out_dir / f"{lot}.jsonl"
    with feed_path.open("w", encoding="utf-8", newline="\n") as feed:
        for photo, calls in readings:
            when = observed_at(cam, photo)
            for (stall, *_rest), (state, confidence), ok in zip(shapes, calls, trusted):
                ev = OccupancyEvent(stall_id=f"{lot}:{stall}", zone_id=f"{lot}:{stall.split('-')[0]}", lot_id=lot,
                                    state=state, confidence=confidence, source=cam["camera_id"],
                                    observed_at=when, ttl=cam["ttl"],
                                    cadence_class=cadence if ok else "periodic_snapshot")
                feed.write(json.dumps(ev.to_json()) + "\n")
    untrusted = [stall for (stall, *_rest), ok in zip(shapes, trusted) if not ok]
    print(f"  {len(readings)} photos -> {feed_path.relative_to(HERE)}")
    print(say("validation day (gate)" if extra else "replayed day", g))
    print(f"  stall gate (tuning days): {sum(trusted)} of {len(trusted)} trusted"
          + (f"; rows only: {', '.join(untrusted)}" if untrusted else ""))
    print("  camera gate (replayed day): " + ("passed, names those stalls (near_live)" if cadence == cam["cadence_class"]
          else f"failed (limit {100 * WRONG_FREE_LIMIT:.0f}%), rows and counts only (periodic_snapshot)"))
    (out_dir / f"{lot}.grade.json").write_text(json.dumps({
        "camera_id": cam["camera_id"], "lot_id": lot, "model": model, "gate_day": "validation" if extra else "replay",
        "confirmations": given["source"] if extra else None, **g, "trusted": sum(trusted),
        "stalls": len(trusted), "untrusted": untrusted, "cadence": cadence, "caution": caution}, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    main()
