# TeamVote

Ideas and features wait here until the team votes. Nothing is built from this file directly.

## How it works
1. Add an idea at the bottom: next ID, one line on what, one line on why, your initials.
2. Vote by adding one line under it: `BD: yes`, `DI: no — reason`, `DK: yes`. One line per person, so votes never clash in git.
3. Two of three carries it. The proposer moves it into handoff/CONTRACT.md as an atom with an owner, and marks it **carried → <atom>** here.
   Two noes: mark it **dropped** and keep the line, so nobody re-proposes it without new reasons.
4. Pull before you vote; read every open idea before adding one.

## Ideas

### V-3 · Real map with real coordinates · DK
Note (BD, 2026-10-12): lots and buildings now sit where Stetson's official map puts them (Aug 2026 edition), still on the drawn picture; real coordinates remain open.
What: replace the hand-drawn campus picture with a live map (map tiles); lots get lat/long in campus.json.
Why: location, distances and routes are only honest on real coordinates.
BD: yes

### V-4 · Building names and pictures on the map · BD · **names carried 2026-10-12** (pictures still open)
What: real Stetson building names on the map instead of "Building 1–80"; small photos only if we took them or they are clearly licensed.
Why: drivers know "Sage Hall", not "Building 44".
BD: yes

### V-5 · One-command launcher · BD · **carried 2026-10-13**
What: one command starts the replay, the server and the page in order, checks each is up, opens the browser, loops the day.
Why: nobody should need three terminals to see the product.
BD: yes

### V-6 · Hold sized by the drive, not a flat 8 minutes · BD · built 2026-10-13, awaiting DI and DK
What: the page asks the server to hold a spot about as long as the drive takes (route length at 20 km/h, x1.3, +3 min),
whole minutes only, clamped to 4-15 min; slower sensors still add their interval. No ask = the old 8 minutes.
Why: a flat 8 minutes lets someone next door hoard a spot and makes someone across campus lose theirs on the way.
Undo if dropped: the page stops sending hold_min (one line in claimSpot); the server falls back to 8 minutes.
BD: yes

### V-7 · One extension for a driver visibly on the way · BD · built 2026-10-13, awaiting DI and DK
What: near the end of a hold, if the page sees the driver is at least 50 m closer by road than when they claimed (and not
yet at the lot), it asks once for 2-5 more minutes; the server allows one per claim, before the deadline.
Why: someone stuck behind a bus should not lose the spot they are clearly driving to.
Undo if dropped: remove maybeExtend() from the poll; /extend stays unused.
BD: yes

### V-8 · Suggest the lot that will still have room on arrival · BD · built 2026-10-13, awaiting DI and DK
What: a lot with fewer free spots than it typically loses during your drive (~1 per 10 min, measured on validation days)
is marked "may be gone", and suggestions prefer a lot with margin. A trend-line forecast was tested and lost to
"stays as it is now" on every validation day, so it is graded in score_day but not used.
Why: "filling up" now can mean full when you get there.
BD: yes

### V-9 · Drivers' confirmations as a live camera health check · BD · built 2026-10-13, awaiting DI and DK
What: per camera, keep a running rate of "the driver found a car where the camera said free" (and the reverse) from
confirmations; flag a camera on the page and in run.py when that rate rises above its graded level.
Why: one day of confirmations is far too few to retrain on (BD-24), but enough to notice a camera drifting
(moved mount, new tree, glare) within days instead of weeks.
Built (BD-25): last 50 confirmations per camera; flagged at >= 10 confirmations, >= 2 against, and a rate >= max(10%,
twice the camera's graded error). Shows a warning in the lot list, the lot window and the run.py board; changes nothing else.
Undo if dropped: the page stops showing camera_health; the server keeps counting.
BD: yes

### V-10 · A flagged camera stops naming single spots · BD · proposed 2026-10-13 (not built)
What: while a camera is flagged by the health check (V-9), its lot answers with rows and counts only, like a camera that
failed its quality gate; it names single spots again once drivers stop contradicting it. Only counts as flagged when the
contradictions come from at least 3 different drivers.
Why: a camera drivers keep contradicting should not keep promising spots; 3 different drivers keeps one person (or a few
angry taps) from switching a camera off.
BD: yes
