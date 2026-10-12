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
from parkfind.lastseen import read_feed, status


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


def main():
    """
    why: Start the DI-4 HTTP server using the selected simulation feed.
    boundary: Reads SK-FEED, SK-LAYOUT and SK-CLOCK only.
    ugly: A frozen replay clock is useful for repeatable frontend testing.
    """
    parser = argparse.ArgumentParser(description="ParkFind SK-VIEW HTTP server")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--now", default=None)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    with Path("lot_commuter_north.json").open(encoding="utf-8") as file:
        layout = json.load(file)

    clock = make_clock(start=args.now, speed=args.speed)
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
