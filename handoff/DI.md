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
