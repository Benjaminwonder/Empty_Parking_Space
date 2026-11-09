# Handoff — DI
Only DI writes here. Newest entry at the bottom. Format: see BRIDGES.md.

2026-10-05 · DI-1 done · reads SK-FEED and SK-EVENT
landed: parkfind/lastseen.py — read_feed(path, now) validates occupancy events, counts broken lines, and skips events after now.
→ BD: no socket changes requested.
→ DK: nothing yet.
2026-10-05 · DI-2 done · builds SK-STATUS
landed: parkfind/lastseen.py — status(events, layout, now) keeps newest claims by observed_at, ages claims by TTL, marks stale and never-seen stalls unknown, and preserves stall/zone/lot grain.
→ BD: status data is ready for downstream guidance work.
→ DK: stall and zone state are now available; HTTP/view wiring comes in DI-3.

2026-10-11 · DI-3 done · writes SK-STATUS JSON
landed: parkfind/lastseen.py — CLI reads SK-FEED, uses SK-CLOCK, builds freshness-aware status, and writes out/<run>/status.json with rejected_lines.
verified: quick and slow snapshots both contain 120 stalls; rejected_lines=0; expired claims become unknown.
note: existing quick feed has 15s TTL claims and produces 120 unknown stalls at 08:15 local. A better quick/slow comparison needs appropriately timed sensor observations.
→ BD: status.json is available for guidance; review the quick/slow demonstration data.
→ DK: JSON status is ready; HTTP SK-VIEW integration follows in DI-4.

2026-10-12 · DI-4 HTTP view implemented · exposes SK-VIEW
landed: parkfind/server.py — GET /view returns as_of, freshness-aware status, and answer.
verified: quick and slow feeds both return 120 stalls; CORS allows http://localhost:8085; no simulator truth is exposed.
→ BD: answer is currently null; integrate guidance.answer() when BD-8 lands.
→ DK: frontend can now request http://localhost:8765/view?vehicle_class=regular&driver_id=test1.

2026-11-09 · S0-BD-3 review · reads SK-SITE, SK-CONNECTOR, SK-PERMIT (drafts)
  agree: the three shapes, as drafted. Questions, none blocking S0:
  → BD (SK-CONNECTOR): event.from_json refuses unknown keys, so the day site_id is added to SK-EVENT, every reader on
    the old event.py rejects every line. Can event.py and my ingest change in one commit, with both shapes read for
    one stage?
  → BD (SK-CONNECTOR): the health line ({"kind": "connector_health", ...}) is not an SK-EVENT. It must not land in
    feed.jsonl or read_feed counts it as a rejected line. I'll take it on its own path (camera_feed); agreed?
  → BD (SK-CONNECTOR): with debounce of N frames, observed_at is the first frame that showed the change or the Nth?
    "the frame that showed it" reads as the first; then a stall can sit up to N frames in the past when it arrives.
  → BD (SK-SITE): utc_zone replaces utc_offset per site. Today sim.py, vision.py and SK-TRUTH read utc_offset
    (-04:00, wrong for live times since 1 Nov). Who moves them, and in which stage?
  → BD (SK-PERMIT): one HMAC key per site or one for all sites? And is the token-signing key a different key from
    the permit-hash key (I'd keep them apart, so leaking one doesn't give the other)?
  → DK: nothing yet.

2026-11-09 · S0-DI-1 done · review of server.py and lastseen.py
  landed: parkfind/lastseen.py — removed the unused parse_utc import; pyflakes clean (lastseen.py and tests/).
  checked: server on out/latest answers /view; two drivers claiming sage:A-03 → one held, one 409 taken.
  questions → BD:
    1. /taken builds status without driver reports or demo cars; every other POST includes them. Intended
       (labels only from real camera readings)?
    2. lastseen counts reserved and out_of_service stalls as "unknown" in the lot summary. Intended, or own counts?
    3. Two readings for one stall with the same observed_at: the earlier feed line wins (strict >). Should a
       driver report or a camera win a tie?
  mine, noted for later (not changed in S0):
    4. /view's 400 comes back as HTML with no CORS header (send_error); every other error is JSON. → _send_json.
    5. first_observed() compares timestamp strings; safe only while every writer stamps "...Z" to the second (sim
       and vision do). Parse with parse_utc before S3 connectors.
    6. /claim checks permits and ADA/EV inside server.py: decision logic, moves to claims.py in S2 (S2-DI-2).
  → DK: S0-DK-2 can review the page against these endpoints.

2026-11-09 · S0-DI-2 done · tests/test_contention.py (was DI-5)
  landed: tests/test_contention.py, tests/README.md. Own day in out/test; fixed moment 08:15 at the lot.
  checks: second claim → taken; 200 rounds of two threads on one stall → exactly one winner each round; guidance
          never names a held spot (44 stall answers, every lot x car type, no stall twice, no regular car on ADA/EV);
          claiming again releases the old spot as switched; counted lots (rinker, east, west2) refuse with not_free;
          every ADA/EV stall → 409 wrong_type for a regular car (through the HTTP handler).
  checked: exits 0 in ~1 s; with the "taken" check removed in a scratch claims.py it exits 1.
  → BD, DK: python tests/test_contention.py is part of the S0 join check.

2026-11-09 · S0-DI-3 done · tests/test_stale.py, tests/test_server_smoke.py (was DI-6, DI-7)
  landed: test_stale.py (quick + slow day, 14 moments incl. an hour after the recording; Michigan Ave check on
          out/latest with photos, else SKIP), test_server_smoke.py (real server, frozen clock, --demo, every endpoint),
          tests/NOTES.md.
  checked: both exit 0; test_stale.py exits 1 with ttl ageing removed in a scratch lastseen.py; score_day PASS.
  open: Michigan Ave check skipped on this laptop (no PKLot in data/); needs a laptop with the photos.
  → BD, DK: S0 join check = python run.py · tests/score_day.py · tests/test_contention.py · tests/test_stale.py ·
    tests/test_server_smoke.py · the page on DK's phone.
