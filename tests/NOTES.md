# tests: notes (DI-7)

2026-11-09 · Tried: removed the "already taken" check in a scratch copy of claims.py -> test_contention.py FAILs at once ("driver-b was also given sage:C-08"). Removed ttl ageing in a scratch copy of lastseen.py -> test_stale.py FAILs ("rinker:A-01 is 3600s old (ttl 90s) but reads free"). Both tests pass on the real code.
2026-11-09 · Happened: in the morning the quick and slow days never age a reading past its ttl (the sim re-reports in time), so "unknown is not free" is only really exercised by the moment an hour after the recording ends; that moment is in the test on purpose.
2026-11-09 · Open: the ADA/EV claim rule lives in server.py, so test_contention checks it through the HTTP handler; when it moves to claims.py (S2-DI-2) the check can call ClaimBook directly. This laptop has no PKLot download, so the Michigan Ave check SKIPs here; it must run on a laptop with data/ before the join check counts it.
