#!/usr/bin/env python3
# box: T3 · lane: DI · read BRIDGES.md before editing
"""
S0-DI-2 (was DI-5): two drivers are never sent to, or given, the same spot.

Tests the functions, not the browser: a fixed simulated day, a fixed moment, then ClaimBook and
guidance called directly. One check goes through the real HTTP handler, because the ADA/EV rule
for claims lives in server.py today (it moves to claims.py in S2, S2-DI-2).

    python tests/test_contention.py

Makes its own day with sim.py in out/test (never out/latest). Prints one PASS line per check and
exits 1 at the first wrong answer, so a script or an LLM can tell pass from fail.
"""

import copy
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from parkfind import guidance                                          # noqa: E402
from parkfind.claims import ClaimBook, ClaimRefused, CLAIMABLE          # noqa: E402
from parkfind.clock import make_clock, parse_utc                        # noqa: E402
from parkfind.lastseen import load_layout                               # noqa: E402
from parkfind.reports import ReportBook                                 # noqa: E402
from parkfind.server import current_status, make_handler                # noqa: E402

RUN = HERE / "out" / "test"
NOW_TEXT = "2026-09-21T12:15:00Z"      # 08:15 at the lot: the morning is busy, live lots still have room
NOW = parse_utc(NOW_TEXT)
RACE_ROUNDS = 200


def fail(name: str, detail: str) -> None:
    print(f"FAIL {name}: {detail}")
    sys.exit(1)


def ok(name: str, detail: str = "") -> None:
    print(f"PASS {name}" + (f"  ({detail})" if detail else ""))


def make_day() -> None:
    """why: every run tests the same day, made fresh, so a stale out/test can never hide a change in sim.py.
    boundary: writes out/test only; run.py's out/latest is never touched.
    ugly: sim.py's default seed makes the day identical every time; that is what makes the moment below repeatable.
    """
    done = subprocess.run([sys.executable, "sim.py", "--out", "out/test"], cwd=HERE,
                          capture_output=True, text=True)
    if done.returncode != 0:
        fail("make day", done.stderr.strip()[-500:])


def free_live_stalls(status: dict, layout: dict, lot_id: str) -> list[str]:
    """Regular stalls in one lot seen free by a live sensor, nearest first (the order guidance names them)."""
    lot = next(l for l in layout["lots"] if l["lot_id"] == lot_id)
    types = guidance.stall_types(lot)
    return sorted((sid for sid, t in types.items() if t == "regular"
                   and status["stalls"][sid]["state"] == "free"
                   and status["stalls"][sid]["cadence_class"] in guidance.LIVE_CADENCES),
                  key=guidance.walk_order)


def check_second_claim_refused(status, layout):
    free = free_live_stalls(status, layout, "sage")
    if not free:
        fail("second claim refused", "no free live stall in sage at the test moment; pick another NOW")
    stall = free[0]
    book = ClaimBook()
    first = book.claim(stall, "driver-a", status, NOW)
    again = book.claim(stall, "driver-a", status, NOW)        # pressing Claim twice changes nothing
    if again != first:
        fail("second claim refused", "the same driver claiming twice changed the claim")
    try:
        book.claim(stall, "driver-b", status, NOW)
    except ClaimRefused as refused:
        if refused.code != "taken":
            fail("second claim refused", f"expected code taken, got {refused.code}")
        ok("second claim refused", f"{stall}: driver-a holds it, driver-b gets 'taken'")
        return
    fail("second claim refused", f"driver-b was also given {stall}")


def check_race(status, layout):
    """why: the book's lock is the only thing between two phones pressing Claim at once; prove it, many times.
    boundary: real threads on one ClaimBook, released together by a barrier each round.
    ugly: a race that passes once proves little; 200 rounds make a missing lock fail almost surely.
    """
    stall = free_live_stalls(status, layout, "sage")[0]
    for round_no in range(RACE_ROUNDS):
        book = ClaimBook()
        start = threading.Barrier(2)
        results = []
        results_lock = threading.Lock()

        def press(driver):
            start.wait()
            try:
                book.claim(stall, driver, status, NOW)
                outcome = "won"
            except ClaimRefused as refused:
                outcome = refused.code
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=press, args=(d,)) for d in ("racer-1", "racer-2")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if sorted(results) != ["taken", "won"]:
            fail("race", f"round {round_no + 1}: expected one 'won' and one 'taken', got {results}")
    ok("race", f"{RACE_ROUNDS} rounds of two threads on {stall}: exactly one winner every round")


def check_guidance_skips_held(status, layout):
    """why: the DI-5 promise: two stall answers never share a stall_id, for any lot or car type.
    boundary: one driver after another asks guidance (claims laid on top, as the server does) and claims what it names.
    ugly: overlay edits the status it is given, so each driver gets a fresh copy, exactly like one request.
    """
    lots_with_stalls = 0
    named_total = 0
    for lot in layout["lots"]:
        types = guidance.stall_types(lot)
        for vehicle in guidance.VEHICLE_CLASSES:
            book = ClaimBook()
            named = set()
            for i in range(len(types) + 1):
                driver = f"{lot['lot_id']}-{vehicle}-{i}"
                view = copy.deepcopy(status)
                book.overlay(view, NOW, driver)
                answer = guidance.answer(view, layout, NOW, vehicle, driver, lot["lot_id"])
                if answer["grain"] != "stall":
                    break
                stall = answer["stall_id"]
                if stall in named:
                    fail("guidance skips held spots", f"{lot['lot_id']} {vehicle}: {stall} named to two drivers")
                if types[stall] not in guidance.TIERS[vehicle]:
                    fail("guidance skips held spots", f"{vehicle} car sent to {types[stall]} stall {stall}")
                named.add(stall)
                book.claim(stall, driver, status, NOW)
            else:
                fail("guidance skips held spots", f"{lot['lot_id']} {vehicle}: still naming stalls after every stall was held")
            if named and vehicle == "regular":
                lots_with_stalls += 1
            named_total += len(named)
    if lots_with_stalls == 0:
        fail("guidance skips held spots", "no lot named any stall at the test moment, so nothing was tested")
    ok("guidance skips held spots", f"{named_total} stall answers in {lots_with_stalls} live lots, no stall twice, "
                                    "no regular car on ADA/EV")


def check_switch(status, layout):
    free = free_live_stalls(status, layout, "sage")
    if len(free) < 2:
        fail("claiming again switches", "need two free live stalls in sage")
    first, second = free[0], free[1]
    book = ClaimBook()
    book.claim(first, "switcher", status, NOW)
    book.claim(second, "switcher", status, NOW)
    news = book.overlay(copy.deepcopy(status), NOW, "switcher")
    if book.holder(first) is not None:
        fail("claiming again switches", f"{first} is still held after the driver claimed {second}")
    if book.holder(second) != "switcher":
        fail("claiming again switches", f"{second} is not held by the driver")
    release = news["last_release"]
    if not release or release["stall_id"] != first or release["outcome"] != "switched":
        fail("claiming again switches", f"expected release of {first} as 'switched', got {release}")
    ok("claiming again switches", f"{first} -> {second}, old spot released as 'switched'")


def check_counted_lots(status, layout):
    """why: a lot that only counts cars (hourly row counts, a gate) cannot see a car arrive, so no spot there is claimable.
    boundary: every stall of every lot where no stall has a claimable sensor reading.
    ugly: such stalls read unknown; the refusal is not_free, never a silent hold on a spot nobody watches.
    """
    counted = [lot["lot_id"] for lot in layout["lots"]
               if all(status["stalls"][sid]["cadence_class"] not in CLAIMABLE
                      for sid in guidance.stall_types(lot))]
    if not counted:
        fail("counted lots refuse claims", "no counted-only lot in the test day")
    book = ClaimBook()
    tried = 0
    for lot in layout["lots"]:
        if lot["lot_id"] not in counted:
            continue
        for sid in guidance.stall_types(lot):
            tried += 1
            try:
                book.claim(sid, "counter", status, NOW)
            except ClaimRefused as refused:
                if refused.code != "not_free":
                    fail("counted lots refuse claims", f"{sid}: expected not_free, got {refused.code}")
                continue
            fail("counted lots refuse claims", f"{sid} in counted lot {lot['lot_id']} was claimed")
    ok("counted lots refuse claims", f"{tried} stalls in {', '.join(counted)}: all refused not_free")


def check_wrong_type(layout):
    """why: a regular car must never hold an ADA or EV spot, even by pressing Claim on it directly.
    boundary: through the real HTTP handler, on a frozen clock, on a port the OS picks.
    ugly: this rule is checked in server.py, not claims.py, so calling ClaimBook alone would miss it (moves in S2).
    """
    clock = make_clock(start=NOW_TEXT, speed=0)
    handler = make_handler(RUN, layout, clock, ClaimBook(), ReportBook())

    class Quiet(handler):
        def log_message(self, *args):   # keep the PASS lines readable
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        specials = []
        for lot in layout["lots"]:
            for sid, kind in guidance.stall_types(lot).items():
                if kind != "regular":
                    specials.append((sid, kind))
        for sid, kind in specials:
            request = urllib.request.Request(f"{base}/claim?stall_id={sid}&driver_id=regular-car&vehicle_class=regular",
                                             data=b"", method="POST")
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as err:
                body = json.loads(err.read())
                if err.code != 409 or body.get("code") != "wrong_type":
                    fail("regular car refused ADA/EV", f"{sid} ({kind}): got {err.code} {body}")
                continue
            fail("regular car refused ADA/EV", f"a regular car claimed {kind} stall {sid}")
    finally:
        server.shutdown()
        server.server_close()
    ok("regular car refused ADA/EV", f"{len(specials)} ADA/EV stalls, every one 409 wrong_type")


def main() -> None:
    make_day()
    layout = load_layout()
    status = current_status(RUN, layout, NOW)
    print(f"day: out/test · moment: {NOW_TEXT} (08:15 at the lot)")
    check_second_claim_refused(status, layout)
    check_race(status, layout)
    check_guidance_skips_held(status, layout)
    check_switch(status, layout)
    check_counted_lots(status, layout)
    check_wrong_type(layout)
    print("ALL PASS")


if __name__ == "__main__":
    main()
