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

### V-5 · One-command launcher · BD
What: one command starts the replay, the server and the page in order, checks each is up, opens the browser, loops the day.
Why: nobody should need three terminals to see the product.
BD: yes
