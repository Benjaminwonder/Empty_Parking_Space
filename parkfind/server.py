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


def current_status(run, layout, now, reports=None):
    """
    why: One place that turns the feed (and drivers' reports) into status at a moment, shared by views and claims.
    boundary: Reads validated sensor events, live driver reports (same event shape) and SK-LAYOUT, never simulator truth.
    ugly: Claims are not in here; they are laid on top by the claim book. Reports are events, so lastseen treats
          them like any sensor: the newest claim per stall or row wins, and a report never outlives its ttl.
    """
    events, rejected_lines = events_until(run / "feed.jsonl", now)
    if reports is not None:
        events = events + reports.events(now)
    snapshot = status(events, layout, now)
    snapshot["rejected_lines"] = rejected_lines
    return snapshot


def build_view(run, layout, clock, book, vehicle_class, driver_id, lot_id=None, reports=None):
    """
    why: Build the current SK-VIEW response for a frontend request.
    boundary: Sensor status first, then claims on top, then guidance, so guidance never names a held spot.
    ugly: answer is null until the page names a lot (nearest to the driver, or a clicked pin).
    """
    now = clock()
    snapshot = current_status(run, layout, now, reports)
    claim_news = book.overlay(snapshot, now, driver_id)

    answer = guidance.answer(snapshot, layout, now, vehicle_class, driver_id, lot_id)

    return {
        "as_of": snapshot["as_of"],
        "status": snapshot,
        "answer": answer,
        "my_claim": claim_news["my_claim"],
        "last_release": claim_news["last_release"],
    }


PAGE_ORIGIN = "http://localhost:8085"


def make_handler(run, layout, clock, book, reports=None):
    """
    why: Bind the selected feed, layout, clock, claim book and driver reports to each HTTP request.
    boundary: GET /view (SK-VIEW); POST /claim, /release, /parked, /taken (SK-CLAIM); POST /report (SK-REPORT).
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
                if kind is not None and kind not in guidance.TIERS[vehicle_class]:
                    self._send_json(409, {"code": "wrong_type",
                                          "message": f"That is an {kind.upper()} spot. Pick the {kind.upper()} tab if it is for you."})
                    return
                try:
                    claim = book.claim(stall_id, driver_id, current_status(run, layout, now, reports), now)
                except ClaimRefused as refused:
                    self._send_json(409, {"code": refused.code, "message": refused.message})
                    return
                self._send_json(200, {"my_claim": claim})
            elif request.path == "/release":
                book.release(driver_id, now)
                self._send_json(200, {"my_claim": None})
            elif request.path == "/parked":
                try:
                    said = book.parked(driver_id, current_status(run, layout, now, reports), now, reports)
                except ClaimRefused as refused:
                    self._send_json(409, {"code": refused.code, "message": refused.message})
                    return
                self._send_json(200, said)
            elif request.path == "/taken":
                book.taken(driver_id, now)
                self._send_json(200, {"my_claim": None})
            elif request.path == "/report":
                try:
                    free_count = int(params.get("free_count", [""])[0])
                    ev = reports.row_count(driver_id, params.get("zone_id", [""])[0], free_count, layout,
                                           current_status(run, layout, now, reports), now)
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
                view = build_view(run, layout, clock, book, vehicle_class, driver_id, lot_id, reports)
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
    args = parser.parse_args()

    # campus.json is found next to the package, so the server starts from any folder.
    layout = load_layout()

    # Without --now, replay from the feed's first report. The wall clock would make a
    # recorded morning look hours or days old, so every stall would read unknown.
    start = args.now or first_observed(args.run / "feed.jsonl")
    clock = make_clock(start=start, speed=args.speed)
    print(f"Replay starts at {start}, speed {args.speed}", flush=True)
    handler = make_handler(args.run, layout, clock, ClaimBook(), ReportBook())

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
