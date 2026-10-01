# CONTRACT — sockets and atoms

A socket is a file, function or link with exactly one writer. Everyone else only reads it.
An atom is the smallest piece of work one lane can finish alone and show running.
Weeks: W1, W2, W3. Lanes: BD, DI, DK. Read BRIDGES.md first.

## Sockets

| Socket | Where | Shape | Writer | Readers | From |
|---|---|---|---|---|---|
| SK-LAYOUT | lot_commuter_north.json | lot_id; utc_offset (lot-local time, "-04:00"); zones[{zone_id, fill_priority, rows[], stalls_per_row}]; special_stalls{ada[], ev[]}. Stall ids are row-NN: N1-01 … F4-10. | BD-1 | sim · DI-2 · BD-8 · DK-2 | W1 |
| SK-EVENT | parkfind/event.py | OccupancyEvent: stall_id?, zone_id?, lot_id?, state ∈ {free, occupied, reserved, out_of_service, unknown}, confidence, source, observed_at (UTC), ttl, cadence_class ∈ {continuous, near_live, periodic_snapshot, slow_snapshot, event_only}, free_count?, total_count?, note?. Every event is validated when it is made, by writers and readers alike. from_json(dict) raises EventShapeError on a bad shape or any unknown key · to_json() · ttl_seconds() · observed_utc() → aware UTC datetime. Also exports State, Cadence, STATES, CADENCES. | BD-2 | sim · DI-1 · DI-2 · BD-8 | W1 |
| SK-CLOCK | parkfind/clock.py | parse_utc(text) → UTC datetime (the one timestamp reader; refuses times without Z/offset). make_clock(start=None, speed=1.0) → now(): no start = real UTC clock; with start = a replay that moves at speed (60 = 1 min per second, 0 = frozen). Built only by DI-3 and DI-4 from --now / --speed; every other function takes now as an argument. | BD-3 | DI-3 · DI-4 | W1 |
| SK-FEED | out/<run>/feed.jsonl | One SK-EVENT as JSON per line, in observed_at order, stamped in UTC (Z). Zone claims carry free_count/total_count; gate claims carry no stall id. | BD-4 | DI-1 | W1 |
| SK-TRUTH | out/<run>/truth.json | {lot_id, tick_s, utc_offset, ticks: [{t, stalls: {id: state}, zones: {id: {free, occupied, total}}}]}. Tests only. | BD-4 | DI-5 · DI-6 | W1 |
| SK-STATUS | lastseen.status(events, layout, now); file form out/<run>/status.json | {as_of, rejected_lines, stalls: {id: {state, last_claim, observed_at, age_s, ttl_s, source, cadence_class, confidence}}, zones: {id: {state, last_claim, free_count, total_count, observed_at, age_s, …}}, lot: {…}}. state is after aging (past ttl → unknown); last_claim is what the event said. Every stall in SK-LAYOUT appears; never seen → unknown. | DI-2 · DI-3 | BD-8 · DI-4 | W1 |
| SK-ANSWER | guidance.answer(status, layout, now, vehicle_class, driver_id) | {vehicle_class, grain: stall \| zone \| count \| none, stall_id?, zone_id?, free_count?, total_count?, based_on: {source, observed_at, age_s, cadence_class}, hold_until?} | BD-8 · BD-9 | DI-4 | W3 |
| SK-VIEW | GET http://localhost:8765/view?vehicle_class=regular&driver_id=… | {as_of, status: SK-STATUS, answer: SK-ANSWER or null}. Nothing else: no truth, no simulator state, no debug keys. | DI-4 | DK-3 · DK-4 · DI-5 · DI-6 | W2 |
| SK-LIB | librarian.py | Index rebuilt from code on every run; --check for headers and cuts. | BD-0 | all | W1 |

## Guidance rules (D4, used by BD-8)
- A stall is named only from a free claim of cadence continuous or near_live still inside its ttl.
- Any other claim inside its ttl → a zone, with its age. Past ttl → the last count and its age, no stall.
- Regular car → regular stalls only. ADA → ADA first, then regular. EV → EV first, then regular.
- A zone count for a regular car is free_count minus that zone's ADA + EV stalls (floor 0): a lower bound.

## Atoms — BD
| Atom | Wk | File | Writes | Reads | Done when |
|---|---|---|---|---|---|
| BD-0 | all | librarian.py | SK-LIB | all code | python librarian.py --check passes at the end of every turn with new or pulled code: every code file tagged, every method headed, no cuts. |
| BD-1 | W1 | lot_commuter_north.json | SK-LAYOUT | — | sim.py loads 120 stalls: 40 per zone, 5 ADA, 8 EV. **Landed.** |
| BD-2 | W1 | parkfind/event.py, parkfind/__init__.py | SK-EVENT | — | sim.py imports the event from parkfind; nothing in parkfind imports sim.py. **Landed.** |
| BD-3 | W1 | parkfind/clock.py | SK-CLOCK | — | The same --now gives the same ages twice. **Landed.** |
| BD-4 | W1 | sim.py | SK-FEED · SK-TRUTH | SK-LAYOUT · SK-EVENT | --out <run> writes feed.jsonl + truth.json; no simulator truth or hidden stall id in the feed; --start is lot-local. **Landed.** |
| BD-5 | W1 | README.md | — | SK-FEED | One feed line explained in plain words; ttl example matches sim.py. |
| BD-6 | W1 | git, README "Run it" | — | — | A fresh clone runs the simulator in ten minutes on stock Python 3.10+. |
| BD-7 | W2 | out/quick, out/slow | SK-FEED · SK-TRUTH | SK-VIEW | Same --now: the slow run's page shows more unknown and older ages. |
| BD-8 | W3 | parkfind/guidance.py | SK-ANSWER | SK-STATUS · SK-LAYOUT | Quick run → stall answers; slow run → zone or count; never a regular car to ADA/EV. |
| BD-9 | W3 | parkfind/guidance.py | SK-ANSWER | — | Two driver_ids never share a stall; same driver twice → same stall; no hold on zone/count answers; hold ends by observed_at + ttl. |

## Atoms — DI
| Atom | Wk | File | Writes | Reads | Done when |
|---|---|---|---|---|---|
| DI-1 | W1 | parkfind/lastseen.py · read_feed(path, now) | — | SK-FEED · SK-EVENT | A broken line is counted, not fixed. Lines after now are skipped, not rejected. |
| DI-2 | W1–2 | parkfind/lastseen.py · status(events, layout, now) | SK-STATUS | SK-EVENT · SK-LAYOUT | All 120 stalls present; past ttl → unknown with last_claim kept; zone claims stay zone claims. |
| DI-3 | W1 | python -m parkfind.lastseen --run out/<run> --now … [--speed …] | SK-STATUS (file) | SK-FEED · SK-CLOCK | Last known status of a few stalls answered from out/<run>/status.json. |
| DI-4 | W2 (answer W3) | parkfind/server.py | SK-VIEW | SK-STATUS · SK-ANSWER · SK-CLOCK | curl shows as_of and every stall; no key named truth anywhere; CORS for the page's origin (DK's server, currently http://localhost:8085). |
| DI-5 | W3 | tests/test_contention.py | — | SK-VIEW · SK-TRUTH | Two stall answers never share a stall_id; slow run → zone/count, no hold. |
| DI-6 | W3 | tests/test_stale.py | — | SK-VIEW · SK-TRUTH | answer.grain is never stall; age present; no unknown stall comes back free. |
| DI-7 | W3 | tests/NOTES.md | — | — | Three or four lines: what was tried, what happened. |

## Atoms — DK
| Atom | Wk | File | Writes | Reads | Done when |
|---|---|---|---|---|---|
| DK-1 | W1 | WebPage | — | — | Exists. Carries X3 (Random occupancy), X4 (server-start clock), X5 (own layout); no .java extension. |
| DK-2 | W2 | WebPage.java | — | SK-LAYOUT | No stall id or ADA/EV position left in the Java source. |
| DK-3 | W2 | WebPage.java | — | SK-VIEW | Random is gone; unknown is never green; zone claims drawn as counts; as_of and ages shown. |
| DK-4 | W3 | WebPage.java | — | SK-VIEW | A stall is named only when answer.grain is stall; the age is always on screen. |

## The sync (end of every week)
1. git pull → python librarian.py --check
2. python sim.py --cadence continuous --out out/quick
3. python sim.py --cadence periodic_15min,hourly --out out/slow
4. python -m parkfind.server --run out/quick --now 2026-09-21T08:15:00-04:00 --speed 0   (08:15 at the lot; --speed 60 to watch it move)
5. Run WebPage.java → http://localhost:8080
6. Pick regular, ADA, EV (W3)
7. Restart step 4 with out/slow, same --now: the page must look less sure
8. python tests/test_contention.py · python tests/test_stale.py (W3)
