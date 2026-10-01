# Handoff — BD
Only BD writes here. Newest entry at the bottom. Format: see BRIDGES.md.

2026-09-28 · BD-1 done · writes SK-LAYOUT
  landed: lot_commuter_north.json — 120 stalls, rows N1–N4 / M1–M4 / F1–F4 × 10; ADA N1-01…05; EV N1-06…09, M1-01…04.
  → DI: DI-2 lists every stall from this file, so a stall never seen is unknown, not missing.
  → DK: DK-2 (W2) draws the grid from this file instead of hard-coded ids and ADA/EV positions.
  known gap: the simulator has no ADA/EV drivers yet, so those 13 stalls stay free all run.

2026-09-28 · BD-0 started · writes SK-LIB
  landed: librarian.py — python librarian.py <name> | --list | --check
  → DI, DK: before each commit run python librarian.py --check. New methods need a docstring with why:, boundary:, ugly: lines.
  → DI: you can start DI-1 against a few hand-written feed lines in the SK-EVENT shape; BD-2 (event.py) lands next.

2026-09-29 · BD-0 update · writes SK-LIB
  landed: librarian.py --check now also fails on a code file whose first ten lines lack the tag
          (box · lane · read BRIDGES.md before editing). sim.py tagged: # box: S1–S7 · lane: BD.
  → DK: please add as the first line of WebPage:  // box: T6 · lane: DK · read BRIDGES.md before editing
        Until then --check reports it; nothing else changes.
  → DI: every new file in parkfind/ and tests/ starts with that line (# for Python).

2026-09-29 · BD-2 done · writes SK-EVENT
  landed: parkfind/event.py — OccupancyEvent, EventShapeError, from_json(d), to_json(), ttl_seconds(), observed_utc(); State, Cadence, STATES, CADENCES.
          sim.py now imports the event from parkfind; its output is byte-identical to before.
  → DI: DI-1 can start for real: for each feed line, OccupancyEvent.from_json(json.loads(line)); catch EventShapeError and count it.
        Age = now - event.observed_utc(); expired when age > event.ttl_seconds(). Do not parse observed_at or ttl yourself.
        Unknown keys are refused on purpose. If you need a field, ask BD.
  → DK: nothing yet.

2026-10-01 · BD-3 done · writes SK-CLOCK
  landed: parkfind/clock.py — parse_utc(text), make_clock(start=None, speed=1.0) → now(). event.observed_utc() uses parse_utc.
  → DI: in DI-3 and DI-4 only: now = make_clock(args.now, args.speed); call now() once per request and pass the result down.
        Never call datetime.now() inside parkfind/; librarian --check fails on it (rule B3).

2026-10-01 · BD-4 done · writes SK-FEED · SK-TRUTH
  landed: sim.py --out <run> writes out/<run>/feed.jsonl and out/<run>/truth.json. live_snapshot/snapshot.json removed.
          Gate notes say only "gate +1 car in" / "gate -1 car out". Hourly zone claims carry free_count/total_count.
          --start is lot-local (layout utc_offset -04:00): 06:30 at the lot = 10:30Z in the feed.
  → DI: read feed.jsonl only; truth.json is for DI-5/DI-6 tests. A lot-local --now looks like 2026-09-21T08:15:00-04:00.
  → DK: the lot's local offset is in lot_commuter_north.json (utc_offset). Show times as lot-local; ages come from SK-VIEW.
        Requests for WebPage: add as line 1  // box: T6 · lane: DK · read BRIDGES.md before editing
        "Last updated" uses the browser clock (new Date()) and the lots are typed-in sample numbers; both get replaced by SK-VIEW in DK-3.
        The server moved to port 8085; CONTRACT now says so. Tell BD if the nine campus lots should replace the single practice lot.
