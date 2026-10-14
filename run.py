#!/usr/bin/env python3
# box: L1 · lane: BD · read BRIDGES.md before editing
"""
ParkFind in one command: data, server, page, browser, and a live board in the terminal.

    python run.py                 # a simulated campus day at 10x, opens the browser
    python run.py --fresh         # make a new day of data first (and re-read the camera photos)
    python run.py --speed 60      # faster replay (claims' 8-minute window becomes 8 seconds)
    python run.py --no-browser    # start everything, open nothing
    python run.py --phone         # also serve https://<laptop Wi-Fi address>:8443 for a phone on the same Wi-Fi

Ctrl+C stops everything. The two servers write to out/logs/, so this terminal stays readable.

Where the data comes from: lots with a camera file (cameras/*.json) and the PKLot photos on this
machine run on real photos through vision.py; every other lot is simulated by sim.py. The two
are merged into one feed in time order. No PKLot download: everything is simulated, as before.

This file only starts and watches the pieces; it decides nothing about parking. The same
three commands still work by hand (README, "See it in the browser").
"""

from __future__ import annotations

import argparse
import bisect
import heapq
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "out" / "latest"          # what the server reads: simulated lots + camera lots, one feed
SIM = HERE / "out" / "sim"             # the simulator's own output
VISION = HERE / "out" / "vision"       # one feed per camera lot (vision.py)
LOGS = HERE / "out" / "logs"
SERVER_PORT, PAGE_PORT = 8765, 8085
VIEW_URL = f"http://localhost:{SERVER_PORT}/view"
PAGE_URL = f"http://localhost:{PAGE_PORT}"


def port_busy(port: int) -> bool:
    """why: a server left over from an earlier run holds the port, and the new one would die silently.
    boundary: tries to connect only; changes nothing.
    ugly: anything on the port counts, even a different program; the message says which port.
    """
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("localhost", port)) == 0


def wait_until_up(url: str, seconds: float, proc: subprocess.Popen, name: str, log: Path) -> None:
    """why: the next step needs the previous one answering, not merely started.
    boundary: polls one URL; reads the child's log only to explain a failure.
    ugly: Java compiles the page on first start, which can take several seconds on a slow laptop.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-8:]
            raise SystemExit(f"\n{name} stopped while starting. Last lines of {log.relative_to(HERE)}:\n  " +
                             "\n  ".join(tail))
        try:
            urllib.request.urlopen(url, timeout=1).read(1)
            return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"\n{name} did not answer at {url} within {seconds:.0f} s (see {log.relative_to(HERE)}).")


def usable_cameras() -> list[dict]:
    """why: a camera lot runs on photos only on machines that have the PKLot download.
    boundary: reads cameras/*.json and checks that their first replayed photo exists; writes nothing.
    ugly: without the photos (a teammate's laptop) the list is empty and every lot is simulated, as before.
    """
    found = []
    for path in sorted((HERE / "cameras").glob("*.json")):
        cam = json.loads(path.read_text(encoding="utf-8"))
        if cam.get("replay") and (HERE / cam["replay"][0]["file"]).exists():
            found.append({"path": path, "lot_id": cam["lot_id"], "camera_id": cam["camera_id"]})
    return found


def newer(a: Path, *b: Path) -> bool:
    """True when a exists and is newer than every b that exists."""
    return a.exists() and all(not x.exists() or a.stat().st_mtime >= x.stat().st_mtime for x in b)


LABEL_HOLD = timedelta(minutes=10)  # photos are 5 minutes apart; one missing photo is a gap, not a change


def splice_camera_truth(cams: list[dict]) -> None:
    """why: for a camera lot, the simulator's truth is a World nobody watches; the people's labels on each photo are
            what was really parked there. Put those in truth.json so tests score the photo lots like every other lot.
    boundary: reads out/sim/truth.json and the camera files' replay labels; writes out/latest/truth.json only.
              vision.py never sees this file, and neither does the server: labels stay out of the feed.
    ugly: between photos the last labels hold for at most LABEL_HOLD; past that (or after the last photo, ~7 p.m.)
          the lot is left out of that tick, so a scorer skips it instead of grading against a guess.
    """
    truth = json.loads((SIM / "truth.json").read_text(encoding="utf-8"))
    sources = {}
    if cams:
        from vision import observed_at   # the same photo clock the feed uses, so truth and readings line up
    for c in cams:
        cam = json.loads(c["path"].read_text(encoding="utf-8"))
        lot = cam["lot_id"]
        stall_of = {str(s["space_id"]): f"{lot}:{s['stall']}" for s in cam["spaces"]}
        photos = sorted((datetime.fromisoformat(observed_at(cam, ph).replace("Z", "+00:00")), ph["labels"])
                        for ph in cam["replay"])
        times = [t for t, _ in photos]
        for tick in truth["ticks"]:
            t = datetime.fromisoformat(tick["t"].replace("Z", "+00:00"))
            i = bisect.bisect_right(times, t) - 1
            if i < 0 or t - times[i] > LABEL_HOLD:
                tick["lots"].pop(lot, None)
                continue
            stalls = {stall_of[sid]: ("occupied" if v else "free") for sid, v in photos[i][1].items()}
            zones: dict[str, dict] = {}
            for sid, state in stalls.items():
                z = zones.setdefault(sid.rsplit("-", 1)[0], {"free": 0, "occupied": 0, "total": 0})
                z[state] += 1
                z["total"] += 1
            free = sum(1 for v in stalls.values() if v == "free")
            tick["lots"][lot] = {"free": free, "total": len(stalls), "stalls": stalls, "zones": zones}
        sources[lot] = f"labels:{cam['camera_id']}"
    truth["truth_sources"] = {lot: sources.get(lot, "simulator")
                              for lot in sorted({l for tick in truth["ticks"] for l in tick["lots"]} | set(sources))}
    (RUN / "truth.json").write_text(json.dumps(truth, separators=(",", ":")), encoding="utf-8")


def prepare_data(fresh: bool) -> list[dict]:
    """why: one feed for the server: real photos for the camera lots, the simulator for the rest.
    boundary: runs vision.py per camera and sim.py (skipping camera lots), then merges by observed_at
              into out/latest/feed.jsonl; each step reruns only when its inputs changed or --fresh.
    ugly: a camera lot's photos cover its day (about 6 a.m. to 7 p.m.); after that, its stalls age into unknown.
    """
    cams = usable_cameras()
    for cam in cams:
        out = VISION / f"{cam['lot_id']}.jsonl"
        if fresh or not newer(out, cam["path"], HERE / "vision.py"):
            print(f"Reading photos for {cam['lot_id']} ({cam['camera_id']}); a minute or two the first time ...", flush=True)
            subprocess.run([sys.executable, "vision.py", "--camera", str(cam["path"].relative_to(HERE))],
                           cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    skip = ",".join(c["lot_id"] for c in cams)
    marker = SIM / "skip.txt"
    if fresh or not (SIM / "feed.jsonl").exists() or not marker.exists() or marker.read_text() != skip:
        print("Making a day of simulated parking data ...", flush=True)
        subprocess.run([sys.executable, "sim.py", "--minutes", "900", "--out", str(SIM.relative_to(HERE)),
                        "--skip", skip], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
        marker.write_text(skip)
    sources = [SIM / "feed.jsonl"] + [VISION / f"{c['lot_id']}.jsonl" for c in cams]
    RUN.mkdir(parents=True, exist_ok=True)
    merged = RUN / "feed.jsonl"
    if fresh or not newer(merged, *sources):
        # every source is already in time order; a merge keeps the one feed in time order (SK-FEED)
        files = [s.open(encoding="utf-8") for s in sources]
        try:
            with merged.open("w", encoding="utf-8", newline="\n") as out:
                for line in heapq.merge(*files, key=lambda l: json.loads(l)["observed_at"]):
                    out.write(line if line.endswith("\n") else line + "\n")
        finally:
            for f in files:
                f.close()
    if fresh or not newer(RUN / "truth.json", SIM / "truth.json", *(c["path"] for c in cams)):
        splice_camera_truth(cams)
    return cams


def camera_summary(cams: list[dict]) -> str:
    """One line per camera lot: how well it reads, and what its two gates (vision.py) let it promise."""
    lines = []
    for c in cams:
        g = VISION / f"{c['lot_id']}.grade.json"
        grade = json.loads(g.read_text(encoding="utf-8")) if g.exists() else {}
        verdict = (f"names {grade.get('trusted', '?')} of {grade.get('stalls', '?')} stalls"
                   if grade.get("cadence") == "near_live" else "rows and counts only")
        lines.append(f"  {c['lot_id']:8s} photos from {c['camera_id']}: {100 * grade.get('right', 0):.1f}% right, "
                     f"named spot taken {100 * grade.get('named_free_wrong', 0):.1f}% -> {verdict}")
    return "\n".join(lines)


def feed_span(feed: Path) -> tuple[datetime, datetime]:
    """why: the loop needs to know where the recorded day starts and ends.
    boundary: reads observed_at from the first and last lines only (the feed is in time order).
    ugly: a feed with a broken last line falls back to scanning backwards for a readable one.
    """
    lines = feed.read_text(encoding="utf-8").splitlines()
    def stamp(line: str) -> datetime:
        return datetime.fromisoformat(json.loads(line)["observed_at"].replace("Z", "+00:00"))
    first = stamp(lines[0])
    for line in reversed(lines):
        try:
            return first, stamp(line)
        except (ValueError, KeyError):
            continue
    raise SystemExit(f"{feed} has no readable reports")


PHONE = HERE / "out" / "phone"
PHONE_PASS = "parkfind"   # protects a throwaway demo certificate, not a secret


def lan_address() -> str | None:
    """why: the phone reaches the laptop by its Wi-Fi address, not localhost.
    boundary: asks the operating system which address it would use to reach the internet; sends nothing (UDP connect).
    ugly: no network, or only a VPN, can give an address the phone can't reach; the printout says to check.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))   # a documentation-only address: nothing is sent
            return s.getsockname()[0]
        except OSError:
            return None


def phone_certificate(ip: str) -> Path:
    """why: phones give location and the compass only to HTTPS pages, so the page needs a certificate for this address.
    boundary: runs Java's own keytool (it comes with Java); writes out/phone/parkfind.p12 and the address it is for.
    ugly: self-signed, so the phone warns once ("not private"): accept it for this demo. A new Wi-Fi address means
          a new certificate (the old one is replaced).
    """
    keytool = shutil.which("keytool")
    if keytool is None:
        raise SystemExit("keytool was not found (it comes with Java). Install a full Java (JDK) 17 or newer for --phone.")
    PHONE.mkdir(parents=True, exist_ok=True)
    store, made_for = PHONE / "parkfind.p12", PHONE / "address.txt"
    if store.exists() and made_for.exists() and made_for.read_text().strip() == ip:
        return store
    if store.exists():
        store.unlink()
    subprocess.run([keytool, "-genkeypair", "-alias", "parkfind", "-keyalg", "RSA", "-keysize", "2048", "-validity", "365",
                    "-storetype", "PKCS12", "-keystore", str(store), "-storepass", PHONE_PASS, "-keypass", PHONE_PASS,
                    "-dname", "CN=ParkFind demo", "-ext", f"SAN=ip:{ip},ip:127.0.0.1,dns:localhost"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    made_for.write_text(ip)
    return store


class Stack:
    """The two servers this launcher owns: started together, stopped together."""

    def __init__(self, speed: float, phone_store: Path | None = None):
        self.speed = speed
        self.phone_store = phone_store
        self.server: subprocess.Popen | None = None
        self.page: subprocess.Popen | None = None
        LOGS.mkdir(parents=True, exist_ok=True)

    def start_server(self) -> None:
        log = LOGS / "server.log"
        self.server = subprocess.Popen(
            # --demo: this is always a replayed recording, so the watcher may drive a demo car to their spot
            [sys.executable, "-m", "parkfind.server", "--run", str(RUN), "--speed", str(self.speed), "--demo"],
            cwd=HERE, stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
        wait_until_up(VIEW_URL, 30, self.server, "The data server", log)

    def start_page(self) -> None:
        log = LOGS / "page.log"
        env = dict(os.environ)
        if self.phone_store is not None:
            env.update(PARKFIND_HTTPS=str(self.phone_store), PARKFIND_HTTPS_PASS=PHONE_PASS)
        self.page = subprocess.Popen(["java", "--source", "17", "WebPage"], cwd=HERE, env=env,
                                     stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
        wait_until_up(PAGE_URL, 90, self.page, "The page", log)

    def restart_server(self) -> None:
        """why: the day is over; start it again from the morning instead of letting every lot go grey.
        boundary: restarts the data server only; the page keeps running and reconnects by itself.
        ugly: claims live in the server's memory, so a loop clears them (drivers see their claim end).
        """
        self.stop(self.server)
        self.start_server()

    @staticmethod
    def stop(proc: subprocess.Popen | None) -> None:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop_all(self) -> None:
        self.stop(self.page)
        self.stop(self.server)


def board_line(view: dict, utc_offset: str) -> str:
    """why: the terminal shows the same truth as the page, at a glance: campus time and free spots per lot.
    boundary: formats one SK-VIEW reply; reads nothing else.
    ugly: lots with only old data show "~" or "?", exactly like the page, never a guessed number.
    """
    sign = -1 if utc_offset.startswith("-") else 1
    hh, mm = utc_offset[1:].split(":")
    as_of = datetime.fromisoformat(view["as_of"]).astimezone(timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    parts = []
    total_free = total = 0
    for lot_id, lot in view["status"]["lots"].items():
        short = lot["name"].split(" · ")[0] + (" (camera?)" if view.get("camera_health", {}).get(lot_id, {}).get("flag") else "")
        if lot["unknown"] <= lot["total"] / 2:
            text = f"{lot['free']}/{lot['total']}"
            total_free += lot["free"]
        elif lot.get("last_count"):
            c = lot["last_count"]
            text = ("" if c["state"] == "fresh" else "~") + f"{c['free_count']}/{c['total_count']}"
            total_free += c["free_count"] if c["state"] == "fresh" else 0
        else:
            text = f"?/{lot['total']}"
        total += lot["total"]
        parts.append(f"{short} {text}")
    return f"{as_of:%I:%M %p}  free {total_free:3d}/{total}  |  " + "  ".join(parts)


def main() -> None:
    """why: one command for the whole product, with the terminal as an optional live board.
    boundary: starts sim.py, parkfind.server and WebPage as child processes and watches them; writes out/logs/.
    ugly: Ctrl+C, a crashed child, or a closed terminal all end with every child stopped, never orphaned.
    """
    p = argparse.ArgumentParser(description="Start ParkFind: data, server, page, browser.")
    p.add_argument("--speed", type=float, default=10.0, help="replay speed (10 = ten campus minutes per real minute)")
    p.add_argument("--fresh", action="store_true", help="make a new day of simulated data first")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--quiet", action="store_true", help="no live board, just start and wait")
    p.add_argument("--phone", action="store_true", help="also serve the page over HTTPS for a phone on the same Wi-Fi")
    args = p.parse_args()

    if shutil.which("java") is None:
        raise SystemExit("Java was not found. The page needs Java 17 or newer (java --version).")
    busy = [port for port in (SERVER_PORT, PAGE_PORT) if port_busy(port)]
    if busy:
        raise SystemExit(f"Port(s) {busy} are already in use: an earlier ParkFind is probably still running. "
                         "Close its window (or Ctrl+C it) and try again.")

    cams = prepare_data(args.fresh)
    if cams:
        print("Camera lots (real photos, PKLot):\n" + camera_summary(cams))
    else:
        print("No PKLot photos on this machine: every lot is simulated.")
    start, end = feed_span(RUN / "feed.jsonl")
    day_real_s = (end - start).total_seconds() / args.speed
    utc_offset = json.loads((HERE / "campus.json").read_text(encoding="utf-8")).get("utc_offset", "+00:00")

    phone_ip = lan_address() if args.phone else None
    if args.phone and phone_ip is None:
        raise SystemExit("--phone: this computer has no network address a phone could reach. Join the Wi-Fi first.")
    stack = Stack(args.speed, phone_certificate(phone_ip) if args.phone else None)
    try:
        print("Starting the data server ...", end=" ", flush=True)
        stack.start_server()
        print(f"up at {VIEW_URL}")
        print("Starting the page (Java compiles it the first time) ...", end=" ", flush=True)
        stack.start_page()
        print(f"up at {PAGE_URL}")
        if phone_ip is not None:
            print(f"\nOn your phone (same Wi-Fi): https://{phone_ip}:8443\n"
                  "  The phone warns once that the connection isn't private (our own demo certificate): accept it.\n"
                  "  If it can't connect, allow Java on private networks when Windows asks (or in the firewall).")
        if not args.no_browser:
            webbrowser.open(PAGE_URL)
        print(f"\nParkFind is running: a campus day every {day_real_s / 60:.0f} real minutes at {args.speed:g}x. "
              "Ctrl+C stops everything.\n", flush=True)

        loop_started = time.time()
        while True:
            time.sleep(10)
            for proc, name in ((stack.server, "data server"), (stack.page, "page")):
                if proc.poll() is not None:
                    raise SystemExit(f"\nThe {name} stopped (see out/logs/). Stopping everything.")
            if time.time() - loop_started > day_real_s:
                print("\nEnd of the recorded day: starting it again from the morning.\n", flush=True)
                stack.restart_server()
                loop_started = time.time()
            if not args.quiet:
                try:
                    view = json.load(urllib.request.urlopen(VIEW_URL, timeout=3))
                    print(board_line(view, utc_offset), flush=True)
                except OSError:
                    print("(data server not answering for a moment)", flush=True)
    except KeyboardInterrupt:
        print("\nStopping ParkFind ...")
    finally:
        stack.stop_all()
        print("Stopped.")


if __name__ == "__main__":
    main()
