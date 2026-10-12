# box: T2 · lane: DI · read BRIDGES.md before editing

"""
Expose ParkFind's freshness-aware parking status over HTTP.

SK-VIEW: GET /view?vehicle_class=regular&driver_id=...
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from parkfind.clock import make_clock
from parkfind.lastseen import load_layout, read_feed, status


def build_view(run, layout, clock, vehicle_class, driver_id):
    """
    why: Build the current SK-VIEW response for a frontend request.
    boundary: Reads validated sensor events and SK-LAYOUT, never simulator truth.
    ugly: Guidance may not exist yet, so answer remains null until BD-8 lands.
    """
    now = clock()
    events, rejected_lines = read_feed(run / "feed.jsonl", now)

    current_status = status(events, layout, now)
    current_status["rejected_lines"] = rejected_lines

    answer = None

    # BD owns guidance.py. Integrate it when its SK-ANSWER contract lands.

    return {
        "as_of": current_status["as_of"],
        "status": current_status,
        "answer": answer,
    }


def make_handler(run, layout, clock):
    """
    why: Bind the selected feed, layout and clock to each HTTP request.
    boundary: Exposes only SK-VIEW through GET /view.
    ugly: Browser requests may include query parameters before guidance exists.
    """

    class ParkFindHandler(BaseHTTPRequestHandler):
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

            view = build_view(run, layout, clock, vehicle_class, driver_id)
            payload = json.dumps(view).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "http://localhost:8085")
            self.end_headers()
            self.wfile.write(payload)

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
    handler = make_handler(args.run, layout, clock)

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
