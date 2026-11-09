#!/usr/bin/env python3
# box: T4 · lane: DI · read BRIDGES.md before editing
"""
S0-DI-3: start the real server and knock on every door once.

    python tests/test_server_smoke.py

Makes a day in out/test_smoke, starts `python -m parkfind.server` as a child process on a spare
port with a frozen clock (08:15 at the lot, --speed 0, --demo), calls every endpoint with urllib
and checks status codes and shapes: SK-VIEW keys, a bad vehicle_class or lot_id is a 400, two
drivers never get one spot, a driver never sees another driver's id, and no key or text named
"truth" appears in any response. Then stops the server. Exits 1 at the first wrong answer.
The server's own log goes to out/test_smoke/server.log.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RUN = "out/test_smoke"
NOW = "2026-09-21T08:15:00-04:00"
VIEW_KEYS = {"as_of", "status", "answer", "my_claim", "last_release", "demo", "forecast", "camera_health"}
A, B, C = "smoke-driver-A", "smoke-driver-B", "smoke-driver-C"

seen_bodies = []   # every response body, checked at the end for truth and for leaked driver ids


def fail(name: str, detail: str) -> None:
    print(f"FAIL {name}: {detail}")
    sys.exit(1)


def ok(name: str, detail: str = "") -> None:
    print(f"PASS {name}" + (f"  ({detail})" if detail else ""))


def spare_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base: str, method: str, path: str) -> tuple[int, object]:
    """One request; returns (status code, parsed JSON or raw text). Never raises on 4xx/5xx."""
    request = urllib.request.Request(base + path, data=b"" if method == "POST" else None, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            code, raw = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        code, raw = err.code, err.read().decode("utf-8", "replace")
    seen_bodies.append((method, path, raw))
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


def expect(name: str, got: tuple[int, object], http: int, **fields) -> object:
    status, body = got
    if status != http:
        fail(name, f"expected {http}, got {status}: {str(body)[:300]}")
    for key, want in fields.items():
        if not isinstance(body, dict) or body.get(key) != want:
            fail(name, f"expected {key}={want!r}, got {body!r}"[:400])
    ok(name, f"{http}")
    return body


def keys_anywhere(value) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for v in value.values():
            found |= keys_anywhere(v)
        return found
    if isinstance(value, list):
        return set().union(*(keys_anywhere(v) for v in value)) if value else set()
    return set()


def start_server(port: int, log: Path) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "parkfind.server", "--run", RUN, "--now", NOW, "--speed", "0",
                             "--port", str(port), "--demo"],
                            cwd=HERE, stdout=log.open("w"), stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            fail("server starts", f"exited with {proc.returncode}; see {log}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/view", timeout=1).read()
            return proc
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    fail("server starts", f"no answer on port {port} within 15 s; see {log}")


def run_checks(base: str) -> None:
    view = expect("GET /view", call(base, "GET", f"/view?vehicle_class=regular&driver_id={A}"), 200)
    if set(view) != VIEW_KEYS:
        fail("SK-VIEW keys", f"expected {sorted(VIEW_KEYS)}, got {sorted(view)}")
    if view["answer"] is not None:
        fail("no lot, no answer", f"answer without a lot_id: {view['answer']}")
    ok("SK-VIEW keys", f"{len(view['status']['stalls'])} stalls; answer null without a lot")

    view = expect("GET /view?lot_id=sage", call(base, "GET", f"/view?vehicle_class=regular&driver_id={A}&lot_id=sage"), 200)
    answer = view["answer"]
    if not answer or answer["grain"] != "stall":
        fail("live lot names a stall", f"sage at 08:15 should name a stall, got {answer}")
    spot = answer["stall_id"]

    expect("bad vehicle_class is 400", call(base, "GET", f"/view?vehicle_class=truck&driver_id={A}"), 400)
    expect("bad lot_id is 400", call(base, "GET", f"/view?vehicle_class=regular&driver_id={A}&lot_id=nowhere"), 400)
    expect("unknown GET is 404", call(base, "GET", "/nothing"), 404)
    expect("unknown POST is 404", call(base, "POST", "/nothing"), 404)

    body = expect("POST /claim", call(base, "POST", f"/claim?stall_id={spot}&driver_id={A}&vehicle_class=regular&hold_min=6"), 200)
    if body["my_claim"]["stall_id"] != spot or body["my_claim"]["phase"] != "held":
        fail("POST /claim", f"unexpected claim {body}")
    expect("second driver on the same spot is 409 taken",
           call(base, "POST", f"/claim?stall_id={spot}&driver_id={B}&vehicle_class=regular"), 409, code="taken")

    view = expect("GET /view as driver B", call(base, "GET", f"/view?vehicle_class=regular&driver_id={B}&lot_id=sage"), 200)
    held = view["status"]["stalls"][spot]
    if view["my_claim"] is not None or not held.get("held") or held["state"] != "reserved":
        fail("held spot shows as held to others", f"my_claim={view['my_claim']} stall={held}")
    if view["answer"].get("stall_id") == spot:
        fail("held spot shows as held to others", f"{spot} named to driver B while A holds it")
    ok("held spot shows as held to others", f"{spot} reserved; B is sent to {view['answer'].get('stall_id')}")

    body = expect("POST /extend", call(base, "POST", f"/extend?driver_id={A}&minutes=3"), 200)
    if not body["my_claim"]["extended"]:
        fail("POST /extend", f"claim not marked extended: {body}")
    expect("second extend is 409", call(base, "POST", f"/extend?driver_id={A}&minutes=3"), 409, code="already_extended")

    body = expect("POST /parked", call(base, "POST", f"/parked?driver_id={A}"), 200)
    if body.get("result") not in ("confirmed", "not_seen", "recorded"):
        fail("POST /parked", f"unexpected result {body}")
    expect("POST /parked with no claim is 409", call(base, "POST", f"/parked?driver_id={C}"), 409, code="no_claim")

    expect("POST /demo/park with no claim", call(base, "POST", f"/demo/park?driver_id={B}"), 200, result="no_claim")

    body = expect("POST /report on a counted row", call(base, "POST", f"/report?driver_id={C}&zone_id=rinker:A&free_count=2"), 200)
    if body["report"].get("source") != "driver.report" or "stall_id" in body["report"]:
        fail("POST /report on a counted row", f"unexpected report {body}")
    expect("report on a live-camera row is 409", call(base, "POST", f"/report?driver_id={C}&zone_id=sage:A&free_count=2"),
           409, code="watched")
    expect("report with a bad count is 400", call(base, "POST", f"/report?driver_id={C}&zone_id=rinker:A&free_count=lots"),
           400, code="bad_count")

    expect("POST /taken", call(base, "POST", f"/taken?driver_id={A}"), 200, my_claim=None)
    expect("POST /release", call(base, "POST", f"/release?driver_id={B}"), 200, my_claim=None)


def check_leaks() -> None:
    """why: SK-VIEW's last line: no truth, no simulator state, never another driver's id.
    boundary: every body this run received, as parsed keys and as raw text.
    ugly: a driver's own id may come back to them (none does today); it must never reach a different driver.
    """
    for method, path, raw in seen_bodies:
        if "truth" in raw.lower():
            fail("no truth in any response", f"{method} {path} mentions truth")
        try:
            keys = keys_anywhere(json.loads(raw))
        except ValueError:
            keys = set()
        if any("truth" in k.lower() for k in keys):
            fail("no truth in any response", f"{method} {path} has a truth key")
        asker = next((d for d in (A, B, C) if f"driver_id={d}" in path), None)
        for other in (A, B, C):
            if other != asker and other in raw:
                fail("no other driver's id", f"{method} {path} (asked by {asker}) contains {other}")
    ok("no truth, no other driver's id", f"{len(seen_bodies)} responses checked")


def main() -> None:
    done = subprocess.run([sys.executable, "sim.py", "--out", RUN], cwd=HERE, capture_output=True, text=True)
    if done.returncode != 0:
        fail("make day", done.stderr.strip()[-500:])
    port = spare_port()
    log = HERE / RUN / "server.log"
    proc = start_server(port, log)
    try:
        run_checks(f"http://127.0.0.1:{port}")
        check_leaks()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("ALL PASS")


if __name__ == "__main__":
    main()
