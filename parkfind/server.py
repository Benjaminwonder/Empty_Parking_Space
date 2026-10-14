# box: T2 · lane: DI · read BRIDGES.md before editing

"""
Expose ParkFind's freshness-aware parking status over HTTP.

SK-VIEW: GET /view?vehicle_class=regular&driver_id=...
"""

import argparse
import bisect
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from parkfind.clock import make_clock
from parkfind import guidance
from parkfind.claims import ClaimBook, ClaimRefused
from parkfind.reports import ReportBook, ReportRefused
from parkfind.demo import DemoBook
from parkfind.forecast import Forecaster, lot_counts
from parkfind.confirmations import LabelLog
from parkfind.lastseen import load_layout, read_feed, status


_FEED_CACHE = {"key": None, "times": [], "events": [], "rejected": 0}
_FEED_LOCK = threading.Lock()
_END_OF_TIME = datetime.max.replace(tzinfo=timezone.utc)


def events_until(feed_path: Path, now):
    """
    why: The page polls every few seconds, often twice at once; re-reading and re-validating a
    full day's feed on every request took about a second. Read it once, reuse it until it changes.
    boundary: Same events read_feed returns, same validation; only the reading is shared.
    ugly: The file can grow while we serve (a camera appending); a new size or modified time
    means a full re-read, never a stale list.
    """
    stat = feed_path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    with _FEED_LOCK:
        if _FEED_CACHE["key"] != key:
            events, rejected = read_feed(feed_path, _END_OF_TIME)
            events.sort(key=lambda e: e.observed_utc())
            _FEED_CACHE.update(key=key, events=events, rejected=rejected,
                               times=[e.observed_utc() for e in events])
        cache = dict(_FEED_CACHE)
    # events are sorted by observed time, so "everything seen by now" is a prefix
    return cache["events"][:bisect.bisect_right(cache["times"], now)], cache["rejected"]


def current_status(run, layout, now, reports=None, demo=None):
    """
    why: One place that turns the feed (and drivers' reports) into status at a moment, shared by views and claims.
    boundary: Reads validated sensor events, live driver reports (same event shape) and SK-LAYOUT, never simulator truth.
    ugly: Claims are not in here; they are laid on top by the claim book. Reports are events, so lastseen treats
          them like any sensor: the newest claim per stall or row wins, and a report never outlives its ttl.
    """
    events, rejected_lines = events_until(run / "feed.jsonl", now)
    if reports is not None:
        events = events + reports.events(now)
    if demo is not None:
        cars, holder = demo
        events = events + cars.events(now, holder)   # demo mode only: the watcher's own car
    snapshot = status(events, layout, now)
    snapshot["rejected_lines"] = rejected_lines
    return snapshot


def build_view(run, layout, clock, book, vehicle_class, driver_id, lot_id=None, reports=None, demo=None,
               forecaster=None, labels=None):
    """
    why: Build the current SK-VIEW response for a frontend request.
    boundary: Sensor status first, then claims on top, then guidance, so guidance never names a held spot.
    ugly: answer is null until the page names a lot (nearest to the driver, or a clicked pin).
    """
    now = clock()
    snapshot = current_status(run, layout, now, reports, demo and (demo[0], book.holder))
    counts = lot_counts(snapshot)   # before claims are laid on: a held spot is not a lot filling up
    claim_news = book.overlay(snapshot, now, driver_id)

    answer = guidance.answer(snapshot, layout, now, vehicle_class, driver_id, lot_id)

    return {
        "as_of": snapshot["as_of"],
        "status": snapshot,
        "answer": answer,
        "my_claim": claim_news["my_claim"],
        "last_release": claim_news["last_release"],
        "demo": {"speed": demo[1]} if demo else None,   # the page offers "Drive there (demo)" only when set
        "forecast": forecaster.forecast(now, counts) if forecaster else {},
        "camera_health": labels.health() if labels else {},   # V-9: drivers contradicting a camera lately
    }


PAGE_ORIGIN = "http://localhost:8085"


def make_handler(run, layout, clock, book, reports=None, demo=None, forecaster=None, labels=None):
    """
    why: Bind the selected feed, layout, clock, claim book and driver reports to each HTTP request.
    boundary: GET /view (SK-VIEW); POST /claim, /release, /parked, /taken (SK-CLAIM); POST /report (SK-REPORT);
              POST /demo/park only when the server was started with --demo (demo = (DemoBook, speed)).
    ugly: a bad vehicle_class or lot_id is a 400, never a guess at what was meant.
    """

    class ParkFindHandler(BaseHTTPRequestHandler):
        def _send_json(self, code, body):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", PAGE_ORIGIN)
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self):
            """
            why: Browsers may ask before a cross-origin POST; answer yes for the page's origin only.
            boundary: Headers only, no body, no state.
            ugly: Our POSTs carry no body or custom headers, so most browsers never ask; this is the fallback.
            """
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", PAGE_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_POST(self):
            """
            why: A driver claims a spot, lets go of one, says they parked or that their spot was taken, or reports a row.
            boundary: Changes only the claim book and the report book (memory); the recorded feed is never written.
            ugly: Two drivers can press Claim at the same instant; the book's lock lets exactly one win, the other gets 409.
            """
            request = urlsplit(self.path)
            params = parse_qs(request.query)
            driver_id = params.get("driver_id", [""])[0]
            now = clock()
            if request.path == "/claim":
                stall_id = params.get("stall_id", [""])[0]
                vehicle_class = params.get("vehicle_class", ["regular"])[0]
                # D4 holds for claims too: a regular car never takes an ADA or EV spot, even by claiming it
                lot = next((l for l in layout["lots"] if stall_id.startswith(l["lot_id"] + ":")), None)
                kind = guidance.stall_types(lot).get(stall_id) if lot else None
                if vehicle_class not in guidance.TIERS:
                    self._send_json(400, {"code": "bad_vehicle", "message": f"Unknown vehicle_class {vehicle_class!r}."})
                    return
                # permits (switched off unless the page sends one): a lot that is not yours is never claimed
                permit = params.get("permit", [""])[0]
                allowed = lot.get("permits", []) if lot else []
                if permit and allowed and "open_permit" not in allowed and permit not in allowed:
                    self._send_json(409, {"code": "wrong_permit",
                                          "message": "Your permit can't park in this lot. Pick a lot for your permit."})
                    return
                if kind is not None and kind not in guidance.TIERS[vehicle_class]:
                    self._send_json(409, {"code": "wrong_type",
                                          "message": f"That is an {kind.upper()} spot. Pick the {kind.upper()} tab if it is for you."})
                    return
                try:
                    # hold_min: the page's estimate of the drive in whole minutes; never a location (CONTRACT)
                    claim = book.claim(stall_id, driver_id, current_status(run, layout, now, reports, demo and (demo[0], book.holder)),
                                       now, params.get("hold_min", [None])[0])
                except ClaimRefused as refused:
                    self._send_json(409, {"code": refused.code, "message": refused.message})
                    return
                self._send_json(200, {"my_claim": claim})
            elif request.path == "/release":
                mine = book.mine(driver_id)
                if mine is not None and mine["phase"] == "arrived" and labels is not None:
                    # "I've left" after a confirmed arrival: the stall should be free on the next photo after now
                    # read with the demo cars in: a demo arrival shows as demo.car here, and leaves no label
                    stall = current_status(run, layout, now, reports, demo and (demo[0], book.holder))["stalls"][mine["stall_id"]]
                    if stall["source"] and stall["source"].startswith("camera."):
                        labels.add(mine["stall_id"], "free", "driver_left", None, after=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
                book.release(driver_id, now)
                self._send_json(200, {"my_claim": None})
            elif request.path == "/parked":
                try:
                    said = book.parked(driver_id, current_status(run, layout, now, reports, demo and (demo[0], book.holder)), now, reports)
                except ClaimRefused as refused:
                    self._send_json(409, {"code": refused.code, "message": refused.message})
                    return
                self._send_json(200, said)
            elif request.path == "/extend":
                try:
                    self._send_json(200, {"my_claim": book.extend(driver_id, params.get("minutes", [None])[0], now)})
                except ClaimRefused as refused:
                    self._send_json(409, {"code": refused.code, "message": refused.message})
            elif request.path == "/taken":
                mine = book.mine(driver_id)
                if mine is not None and labels is not None:
                    stall = current_status(run, layout, now)["stalls"][mine["stall_id"]]
                    if params.get("reason", [""])[0] == "found_car":
                        # "There's a car in it": the driver is there and the camera said free: the camera was wrong
                        labels.add(mine["stall_id"], "occupied", "driver_found_car", stall)
                    elif stall["last_claim"] == "occupied":
                        # "No, not me": a car is there, someone else's; the camera's newest reading saw it
                        labels.add(mine["stall_id"], "occupied", "someone_else", stall)
                book.taken(driver_id, now)
                self._send_json(200, {"my_claim": None})
            elif request.path == "/demo/park" and demo is not None:
                self._send_json(200, demo[0].park(driver_id, book.mine(driver_id),
                                                  current_status(run, layout, now, reports, (demo[0], book.holder))))
            elif request.path == "/report":
                try:
                    free_count = int(params.get("free_count", [""])[0])
                    ev = reports.row_count(driver_id, params.get("zone_id", [""])[0], free_count, layout,
                                           current_status(run, layout, now, reports, demo and (demo[0], book.holder)), now)
                except ValueError:
                    self._send_json(400, {"code": "bad_count", "message": "free_count must be a whole number."})
                    return
                except ReportRefused as refused:
                    self._send_json(409, {"code": refused.code, "message": refused.message})
                    return
                self._send_json(200, {"report": ev.to_json()})
            else:
                self.send_error(404, "Not found")

        def do_GET(self):
            """
            why: Serve a fresh parking snapshot when the frontend requests it.
            boundary: Only /view returns SK-VIEW; other paths return 404.
            ugly: Browser clients require CORS headers from their own origin.
            """
            request = urlsplit(self.path)

            if request.path != "/view":
                self.send_error(404, "Not found")
                return

            params = parse_qs(request.query)
            vehicle_class = params.get("vehicle_class", ["regular"])[0]
            driver_id = params.get("driver_id", [""])[0]
            lot_id = params.get("lot_id", [None])[0]

            try:
                view = build_view(run, layout, clock, book, vehicle_class, driver_id, lot_id, reports, demo, forecaster,
                                  labels)
            except ValueError as problem:  # unknown vehicle_class or lot_id: the caller's mistake, not ours
                self.send_error(400, str(problem))
                return
            self._send_json(200, view)

    return ParkFindHandler


def first_observed(feed_path: Path) -> str:
    """
    why: Give the replay clock a sensible default start: the moment the recording begins.
    boundary: Reads only the observed_at values in the feed; validates nothing else.
    ugly: Lines are in time order but an unreadable first line must not stop the server, so all lines are scanned.
    """
    earliest = None
    with feed_path.open(encoding="utf-8") as feed:
        for line in feed:
            try:
                stamp = json.loads(line)["observed_at"]
            except (ValueError, KeyError, TypeError):
                continue
            if earliest is None or stamp < earliest:
                earliest = stamp
    if earliest is None:
        raise SystemExit(f"{feed_path} has no readable reports")
    return earliest


def main():
    """
    why: Start the DI-4 HTTP server using the selected simulation feed.
    boundary: Reads SK-FEED, SK-LAYOUT and SK-CLOCK only.
    ugly: A frozen replay clock is useful for repeatable frontend testing.
    """
    parser = argparse.ArgumentParser(description="ParkFind SK-VIEW HTTP server")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--now", default=None,
                        help="replay start, e.g. 2026-09-21T08:15:00-04:00 (default: the feed's first report)")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--demo", action="store_true",
                        help="replaying a recording for a demo: allow the watcher's own demo car (POST /demo/park)")
    args = parser.parse_args()

    # campus.json is found next to the package, so the server starts from any folder.
    layout = load_layout()

    # Without --now, replay from the feed's first report. The wall clock would make a
    # recorded morning look hours or days old, so every stall would read unknown.
    start = args.now or first_observed(args.run / "feed.jsonl")
    clock = make_clock(start=start, speed=args.speed)
    print(f"Replay starts at {start}, speed {args.speed}", flush=True)
    # drivers' confirmations, for labels.py and vision.py, and the camera health check (graded levels from vision.py)
    graded = {}
    for g in (args.run.parent / "vision").glob("*.grade.json"):
        try:
            grade = json.loads(g.read_text(encoding="utf-8"))
            graded[grade["lot_id"]] = float(grade.get("named_free_wrong", 0.0))
        except (ValueError, KeyError):
            continue
    labels = LabelLog(args.run / "labels.jsonl", graded)
    handler = make_handler(args.run, layout, clock, ClaimBook(labels), ReportBook(),
                           (DemoBook(), args.speed) if args.demo else None,
                           Forecaster(lambda t: current_status(args.run, layout, t)), labels)

    server = ThreadingHTTPServer(("localhost", args.port), handler)

    print(f"ParkFind server: http://localhost:{args.port}/view", flush=True)
    print(f"Feed: {args.run / 'feed.jsonl'}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ParkFind server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
