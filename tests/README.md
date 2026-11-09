# tests: how to run them

Standard library only, from the repo folder, on Python 3.10 or newer. Each test makes its own
simulated day in its own out/ folder (never out/latest) and prints one PASS line per check.
Exit 0 = pass, 1 = the first wrong answer (printed as FAIL with what went wrong).

    python tests/test_contention.py     # S0-DI-2: two drivers never get one spot (about 1 s)
    python tests/test_stale.py          # S0-DI-3: unknown is not free (about 2 s)
    python tests/test_server_smoke.py   # S0-DI-3: the real server answers every endpoint (about 1 s)
    python tests/score_day.py           # the played day against the truth (needs out/latest: python run.py once)

| Test | Day it makes | What it proves |
|---|---|---|
| test_contention.py | out/test | second claim refused (taken); 200-round two-thread race has one winner; guidance never names a held spot, for any lot or car type; claiming again switches; counted lots refuse claims; a regular car gets 409 wrong_type on every ADA/EV stall |
| test_stale.py | out/test_quick, out/test_slow | past its ttl every stall, row and lot claim reads unknown; never-seen is unknown; named stalls are live, free, in ttl; every answer has an age; slow day never names a stall; nothing free an hour after the recording; Michigan Ave never named (out/latest with photos only, else SKIP) |
| test_server_smoke.py | out/test_smoke | every GET and POST answers with the right code and shape; bad vehicle_class or lot_id is 400; no "truth" and no other driver's id in any response |

The S0 join check runs all four, on all three laptops, on a fresh pull.
