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
