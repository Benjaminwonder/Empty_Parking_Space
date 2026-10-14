#!/usr/bin/env python3
# box: T5 · lane: DI · read BRIDGES.md before editing   (written by BD, 2026-10-13; DI owns it from here)
"""
Score a played day: what the page would have said, against what was really parked there.

The trunk (lastseen -> guidance) never sees truth. This file is the one place both meet:
it rebuilds the status the server would have served at each moment, asks guidance the
driver's question, and checks the answer against truth.json. Simulated lots are checked
against the simulator's World; photo lots against the people's labels on each photo.

    python tests/score_day.py                  # out/latest, every 5 campus minutes
    python tests/score_day.py --every 1        # every minute (slower)

Exit code 1 when any lot names a single spot that is really taken more than 5% of the
time (the D4 promise); 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from parkfind import guidance                      # noqa: E402
from parkfind.lastseen import load_layout, status  # noqa: E402
from parkfind.server import events_until           # noqa: E402  the server's own reading, not a copy
from parkfind.forecast import LOOKBACK_MIN, lot_counts, project, trend   # noqa: E402

NAMED_WRONG_LIMIT = 0.05   # D4: a named spot may be really taken at most 1 time in 20


def served_count(lot: dict) -> int | None:
    """why: the number a driver reads on the pin, so a count can be scored like a named spot.
    boundary: reads one lot of SK-STATUS; same order of trust as the page (stall reads, then a fresh count).
    ugly: a lot that is mostly unknown with no fresh count shows no number, so there is nothing to score.
    """
    if lot["unknown"] == 0:
        return lot["free"]
    c = lot.get("last_count")
    if c and c["state"] == "fresh":
        return c["free_count"]
    return None


def score(run: Path, every_min: int) -> dict:
    """why: one pass over the day, per lot: coverage, stall reads, named spots, and the count on the pin.
    boundary: reads run/feed.jsonl through the server's reader and run/truth.json; writes nothing.
    ugly: a lot with no truth at a moment (a photo lot after its last photo) is skipped there, never assumed free.
    """
    layout = load_layout()
    truth = json.loads((run / "truth.json").read_text(encoding="utf-8"))
    step = max(1, round(every_min * 60 / truth["tick_s"]))
    sign = -1 if truth["utc_offset"].startswith("-") else 1
    hh, mm = truth["utc_offset"][1:].split(":")
    local = timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
    rows = {l["lot_id"]: {"name": l["name"], "source": truth.get("truth_sources", {}).get(l["lot_id"], "simulator"),
                          "moments": 0, "stall_reads": 0, "known": 0, "right": 0, "said_free": 0, "free_wrong": 0,
                          "named": 0, "named_wrong": 0, "counts": 0, "count_off": 0, "by_hour": {}}
            for l in layout["lots"]}
    counts_at, free_at = {}, {}   # per sample time: the served counts, and the truth (for the forecast grade)
    for tick in truth["ticks"][::step]:
        now = datetime.fromisoformat(tick["t"].replace("Z", "+00:00"))
        events, _ = events_until(run / "feed.jsonl", now)
        st = status(events, layout, now)
        counts_at[now] = lot_counts(st)
        free_at[now] = {lot_id: real["free"] for lot_id, real in tick["lots"].items()}
        for lot_id, real in tick["lots"].items():
            r = rows.get(lot_id)
            if r is None:
                continue
            r["moments"] += 1
            for sid, real_state in real["stalls"].items():
                said = st["stalls"][sid]["state"]
                r["stall_reads"] += 1
                if said == "unknown":
                    continue
                r["known"] += 1
                r["right"] += said == real_state
                if said == "free":
                    r["said_free"] += 1
                    r["free_wrong"] += real_state == "occupied"
            ans = guidance.answer(st, layout, now, "regular", "score", lot_id)
            if ans and ans["grain"] == "stall":
                taken = real["stalls"][ans["stall_id"]] == "occupied"
                r["named"] += 1
                r["named_wrong"] += taken
                hour = r["by_hour"].setdefault(now.astimezone(local).hour, [0, 0])
                hour[0] += 1
                hour[1] += taken
            shown = served_count(st["lots"][lot_id])
            if shown is not None:
                r["counts"] += 1
                r["count_off"] += abs(shown - real["free"])
    rows["_forecast"] = grade_forecast(counts_at, free_at)
    return rows


def grade_forecast(counts_at: dict, free_at: dict) -> dict:
    """why: a forecast earns its place only if it beats "it stays as it is now"; grade both on the same moments.
    boundary: the served counts at t, t-10, t-20 (forecast.py's model, unchanged) against the truth 5 and 10 minutes on.
    ugly: "promised room, found full" is the error a driver feels: we said 2 or more free on arrival, and there were 0.
    """
    from datetime import timedelta
    out = {}
    for h in (5, 10):
        g = {"n": 0, "trend_err": 0, "same_err": 0, "trend_full": 0, "same_full": 0}
        for t, cur in counts_at.items():
            later = free_at.get(t + timedelta(minutes=h))
            past = [counts_at.get(t - timedelta(minutes=m)) for m in LOOKBACK_MIN]
            if later is None or any(p is None for p in past):
                continue
            for lot_id, c in cur.items():
                pts = [p.get(lot_id) for p in past] + [c]
                if any(x is None for x in pts) or lot_id not in later:
                    continue
                f = {"free_now": c[0], "total": c[1],
                     "per_min": trend([(-m, x[0]) for m, x in zip(LOOKBACK_MIN, pts[:-1])] + [(0, c[0])])}
                guess, real = project(f, h), later[lot_id]
                g["n"] += 1
                g["trend_err"] += abs(guess - real)
                g["same_err"] += abs(c[0] - real)
                g["trend_full"] += guess >= 2 and real == 0
                g["same_full"] += c[0] >= 2 and real == 0
        out[h] = g
    return out


def worst_hour(by_hour: dict) -> str:
    """why: a day's average hides the rush; the hour with the most taken named spots is where drivers get hurt.
    boundary: formats the score's per-hour tallies; reads nothing else.
    ugly: an hour with fewer than 3 named spots says too little to rank, so it is skipped.
    """
    ranked = [(wrong / n, h, wrong, n) for h, (n, wrong) in by_hour.items() if n >= 3]
    if not ranked:
        return "-"
    rate, h, wrong, n = max(ranked)
    return f"{h:02d}h {wrong}/{n}" if wrong else "none"


def main() -> None:
    """why: one command, one table, one exit code a teammate can run before pushing.
    boundary: prints to the terminal; touches no file.
    ugly: an empty run folder stops with a plain message instead of a traceback.
    """
    ap = argparse.ArgumentParser(description="Score a played day against its truth")
    ap.add_argument("--run", default="out/latest", help="run folder with feed.jsonl and truth.json")
    ap.add_argument("--every", type=int, default=5, help="campus minutes between checks (default 5)")
    args = ap.parse_args()
    run = Path(args.run) if Path(args.run).is_absolute() else HERE / args.run
    if not (run / "truth.json").exists():
        raise SystemExit(f"{run / 'truth.json'} not found: run  python run.py --fresh  first.")

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:5.1f}%" if b else "    -"

    rows = score(run, args.every)
    fc = rows.pop("_forecast")
    print(f"{'lot':24s} {'truth':22s} {'seen':>6s} {'right':>6s} {'free?':>6s} {'named':>6s} {'wrong':>6s} {'count±':>7s}  {'worst hr':>9s}")
    failed = []
    for lot_id, r in rows.items():
        named_wrong = r["named_wrong"] / r["named"] if r["named"] else 0.0
        if named_wrong > NAMED_WRONG_LIMIT:
            failed.append(r["name"])
        print(f"{r['name'][:24]:24s} {r['source'][:22]:22s} {pct(r['known'], r['stall_reads'])} "
              f"{pct(r['right'], r['known'])} {pct(r['free_wrong'], r['said_free'])} {r['named']:6d} "
              f"{pct(r['named_wrong'], r['named'])} "
              + (f"{r['count_off'] / r['counts']:7.1f}" if r["counts"] else "      -")
              + f"  {worst_hour(r['by_hour']):>9s}")
    print("\nseen = stall reads not unknown · right = of those, matched truth · free? = said free but taken\n"
          "named = single spots guidance named · wrong = of those, really taken · count± = pin number off by, on average\n"
          "worst hr = the campus hour whose named spots were most often taken (taken/named)")
    print("\nForecast for arrival (all lots): trend line vs \"it stays as it is now\"")
    for h, g in fc.items():
        if g["n"]:
            print(f"  {h:2d} min ahead: off by {g['trend_err'] / g['n']:.2f} spots on average vs {g['same_err'] / g['n']:.2f}; "
                  f"promised room, found full: {g['trend_full']} vs {g['same_full']} times (of {g['n']})")
        else:
            print(f"  {h:2d} min ahead: not graded (use --every 5 or 10 so the past points line up)")
    if failed:
        print(f"\nFAIL: named spots taken more than {100 * NAMED_WRONG_LIMIT:.0f}% of the time in: {', '.join(failed)}")
        sys.exit(1)
    print(f"\nPASS: every lot's named spots were free at least {100 * (1 - NAMED_WRONG_LIMIT):.0f}% of the time.")


if __name__ == "__main__":
    main()
