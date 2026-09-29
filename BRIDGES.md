# BRIDGES — read first

ParkFind sends a driver to a free stall, or the smallest honest zone,
and says how old the information is.

## Before you change anything
1. Read handoff/CONTRACT.md. Socket names and shapes are fixed; your lane's atoms are listed there.
2. Read the other lanes' handoff files for entries addressed to your lane.
3. Work only in your lane's files. Needing a change in someone else's
   socket is a request in your handoff file, not an edit.

## Lanes
BD   sim.py · lot_commuter_north.json · parkfind/event.py · parkfind/clock.py · parkfind/guidance.py · librarian.py
DI   parkfind/lastseen.py · parkfind/server.py · tests/
DK   WebPage.java

## Rules that do not bend
- Every code file's first lines carry its tag:  # box: T2 · lane: DI · read BRIDGES.md before editing
  (Java uses //). librarian.py --check fails on a file without it.
- One event shape (SK-EVENT). No second shape.
- Unknown is not free. A claim past its ttl becomes unknown.
- Nothing in parkfind/ imports sim.py. Simulator truth never reaches the page.
- The page invents nothing: every colour, count and age comes from SK-VIEW.
- Python standard library only on the event path.

## Before you commit
- python librarian.py --check passes (new methods need a why/boundary/ugly docstring).
- Commit message starts with the atom ID:  DI-1: read_feed skips future lines
- Append one entry to handoff/<your lane>.md

## Entry format
2026-09-29 · BD-2 done · writes SK-EVENT
  landed: parkfind/event.py — OccupancyEvent, from_json(d), ttl_seconds()
  → DI: DI-1 and DI-2 can import it now. Do not add fields; ask BD.
  → DK: nothing yet.
