# Handoff — BD
Only BD writes here. Newest entry at the bottom. Format: see BRIDGES.md.

2026-09-28 · BD-1 done · writes SK-LAYOUT
  landed: lot_commuter_north.json — 120 stalls, rows N1–N4 / M1–M4 / F1–F4 × 10; ADA N1-01…05; EV N1-06…09, M1-01…04.
  → DI: DI-2 lists every stall from this file, so a stall never seen is unknown, not missing.
  → DK: DK-2 (W2) draws the grid from this file instead of hard-coded ids and ADA/EV positions.
  known gap: the simulator has no ADA/EV drivers yet, so those 13 stalls stay free all run.

2026-09-28 · team rule
  → DI, DK: new methods need a docstring with why:, boundary:, ugly: lines.
  → DI: you can start DI-1 against a few hand-written feed lines in the SK-EVENT shape; BD-2 (event.py) lands next.

2026-09-29 · tag line rule
  landed: every code file's first lines carry its tag (box · lane · read BRIDGES.md before editing). sim.py tagged: # box: S1–S7 · lane: BD.
  → DK: please add as the first line of WebPage:  // box: T6 · lane: DK · read BRIDGES.md before editing
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
        Never call datetime.now() inside parkfind/.

2026-10-01 · BD-4 done · writes SK-FEED · SK-TRUTH
  landed: sim.py --out <run> writes out/<run>/feed.jsonl and out/<run>/truth.json. live_snapshot/snapshot.json removed.
          Gate notes say only "gate +1 car in" / "gate -1 car out". Hourly zone claims carry free_count/total_count.
          --start is lot-local (layout utc_offset -04:00): 06:30 at the lot = 10:30Z in the feed.
  → DI: read feed.jsonl only; truth.json is for DI-5/DI-6 tests. A lot-local --now looks like 2026-09-21T08:15:00-04:00.
  → DK: the lot's local offset is in lot_commuter_north.json (utc_offset). Show times as lot-local; ages come from SK-VIEW.
        Requests for WebPage: add as line 1  // box: T6 · lane: DK · read BRIDGES.md before editing
        "Last updated" uses the browser clock (new Date()) and the lots are typed-in sample numbers; both get replaced by SK-VIEW in DK-3.
        The server moved to port 8085; CONTRACT now says so. Tell BD if the nine campus lots should replace the single practice lot.

2026-10-05 · BD-5 done · README
  landed: README "One parking update (an occupancy event)": a real line from the feed, read out in plain words.
  → DI, DK: start there if a feed line is unclear.

2026-10-05 · BD-6 done · README
  landed: README "Run it (about ten minutes)": clone, python sim.py, expected output, the quick and slow runs, where things live.
          "Current phase" and "Status" now say the simulator runs.
  → DI, DK: if those steps fail on your machine, say so here.

2026-10-05 · BD-1/BD-4 redo · writes SK-LAYOUT · SK-FEED · SK-TRUTH
  landed: campus.json replaces lot_commuter_north.json: DK's nine lots, 200 stalls, each with its own sensors.
          sim.py runs every lot in one morning. Stall ids are lot:row-NN (sage:B-04), zones are lot:row (sage:B).
          Live cameras now re-report every stall each minute (ttl 90s), so live lots stay fresh instead of expiring to unknown.
  → DI: read_feed works unchanged (checked). DI-2 keys stalls by the new ids and adds a lots summary per lot_id (see SK-STATUS).
  → DK: drop the typed-in lots. Names and totals come from campus.json; keep pin positions in the page keyed by lot_id
        (rinker, sage, libn, libs, hollis, east, west1, west2, stetson). Counts and ages will come from SK-VIEW.

2026-10-12 · BD-10 started · writes SK-FEED for camera lots
  landed: vision.py — photos + a camera file (one polygon per stall) → events in the same shape as the simulator's.
          observed_at = when the photo was taken (from its file name), never when it was processed.
          Pillow and NumPy are allowed in vision.py only; nothing in parkfind/ uses them, so DI and DK install nothing.
  → DI: nothing changes for read_feed; camera events look exactly like simulator events.
  → DK: nothing yet. One of the nine lots will become a real-photo lot once its camera file exists.

2026-10-12 · campus linked end to end · edited DI and DK files at the lead's request
  Why: DI-2..DI-4 and DK-2/DK-3 were built on lot_commuter_north.json; the campus change would have shown every stall unknown.
  landed (BD lane): gate counter now reports the lot's running count (free_count/total_count) every 5 min and on every car;
          15-minute snapshots last 24m instead of 8m, so those lots no longer go unknown between polls.
  landed (DI files, by BD): lastseen.py reads campus.json (load_layout, layout_stalls), ids lot:row-NN,
          status adds lots summary + lot_claims; server.py finds campus.json itself and, without --now, replays from the feed's first report.
  landed (DK file, by BD): WebPage reads campus.json; each of the nine lots is a P pin (positions are PLACEHOLDERS, please move them
          to the real lots); lot names from campus.json; "Last count" from status.lots; search accepts sage:B-04 in any case.
  checked: sim → server (--speed 60 and frozen 08:15) → page in a headless browser; 200 stalls, no page errors, counts match truth.json.
  → DI: please review your two files; the shapes are in CONTRACT SK-STATUS. read_feed is unchanged.
  → DK: please review WebPage, move the nine LOT_MARKERS to the real lot positions, and check the pop-up distances (they are within-lot only now).

2026-10-12 · BD-8 landed · writes SK-ANSWER · edited DI and DK files at the lead's request
  landed: parkfind/guidance.py — answer(status, layout, now, vehicle_class, driver_id, lot_id) per D4:
          stall (live + free + inside ttl) → zone → count → none. Regular cars never get ADA/EV. No lot_id → null.
  landed (DI file, by BD): server.py takes lot_id and returns 400 on a bad lot_id or vehicle_class.
          The feed is now read once and reused until the file changes (events_until); each request was re-reading
          the whole day (about 1 s). Same events, same validation: status matches read_feed at five replay times.
  landed (DK file, by BD): "the map tells the truth" —
          lot pins are coloured by how full the lot is (green ≥ 25% free, amber, red, grey = old data) and labelled "13/32";
          a legend explains the colours; the ADA/EV tabs hide lots with none and recount the rest;
          a lot window leads with guidance's answer and preselects the stall it names (outlined blue);
          the spot chip list is gone; users see "Row B · spot 04", never sage:B-04; search takes "Sage" or "Sage B-04";
          "Live · updated 7:18 AM" in campus time; the route leaves the gate along Michigan Ave toward the lot's own pin
          (PLACEHOLDER geometry, no distance quoted outside the lot); closest-lots-to-a-building uses the pins, not the
          pop-up drawing space (it was naming the same two lots for every building); the close-up inset now hides when
          a route is dropped (it used to stay up forever).
  checked: headless browser walk through pin, tab, building, search, route; no page errors; window badge always equals its pin.
  → DI: please review server.py (events_until) and pull before your next change there.
  → DK: please review WebPage. Pin colours/counts live in lotPinState/updateLotPins, keyed by lot_id, so they carry
        over to the live map you're building. When you do, campus.json needs lat/long per lot; ask BD and we add it together.

2026-10-12 · BD-9 landed (claims) · writes SK-CLAIM · edited DI and DK files at the lead's request
  landed: parkfind/claims.py — ClaimBook: claim / release / overlay, one lock, in server memory (a restart clears claims).
          Rules in CONTRACT BD-9. A claim is never an OccupancyEvent and never enters the feed.
  landed (DI file, by BD): server.py — POST /claim, POST /release, OPTIONS; the view lays claims over status before guidance,
          and adds my_claim + last_release for the asking driver only.
  landed (DK file, by BD): "Claim this spot" (only on spots seen free), held spots in purple, your spot in solid blue,
          "Held for you until 8:13 AM" + Release in the route panel, "Car detected in your spot" once a sensor sees a car,
          a pop-up "Unresponsive, so spot released" on a no-show; quiet releases (car came and left) show nothing.
  checked: rule tests (first wins, no_show at exactly +8:00, arrive-then-leave → quiet release, 23 min for 15-minute lots,
          refusals for occupied / counted / unknown spots); two drivers in two browsers; 8 simultaneous claims → one 200, seven 409.
  note: the camera can't tell whose car it is; any car in a held spot counts as the driver's arrival (true for real cameras too).
  demo: run the server with --speed 10 so 8 minutes is 48 seconds.
  → DI: please review server.py (do_POST, build_view order: status → claims → guidance).
  → DK: please review WebPage (claimSpot, releaseSpot, noticeRelease, statusClass held/mine).

2026-10-12 · building names from the official map · edited DK file at the lead's request
  source: Stetson's DeLand campus map, edition of 7 Aug 2026 (stetson.edu/maps, deland-campus-map.pdf), kept locally in
          data/stetson_map/ (gitignored). It has 80 numbered buildings; DK's 1–80 numbering matches it.
  checked: every pin on the PDF fitted to DK's positions (median miss ~8 picture units). Corrections made:
          DK's old #42 was the P42 parking-lot label → it is #18 (Russian, East European and Eurasian Studies);
          #42 Nemec Hall and #59 Hulley Tower added; #48, #49, #52 (University Village) and #54 (CUB) moved;
          colours now follow the map's categories (academic, residential, student life, athletics, offices).
          #43, #66, #69, #71, #72 are off-campus arrows on the map and are left off.
  landed (DK file, by BD): every building has its official name; the "Building 1–41" list is gone; a Buildings switch at the
          top shows all names + a directory grouped by category (off by default: 10 landmark names, other pins dimmed);
          search takes buildings ("CUB", "Flagler", "54"), lots win when the text starts a lot's name ("Sage", "east");
          lot areas are tinted with their pin's colour.
  note: the page's second text block is ~53 KB of Java's 64 KB limit per string; the next big addition needs a part3.
  → DK: please review. The official map also shows Stetson's real parking lots (P01–P54, typed commuter / faculty /
        resident / visitor); our nine lot pins are still placeholders. Placing them on real lots is the next decision.

2026-10-12 · real Stetson lots · writes SK-LAYOUT · edited DK file at the lead's request
  landed: campus.json — each of the nine lots now stands for a real Stetson lot from the official map (Aug 2026):
          official_lot + permits added, names are what drivers read. lot_id, rows, sizes and sensors unchanged, so
          sim.py, last-seen, guidance, claims and saved runs keep working.
          rinker → Lot 03 (Edmunds Center, open permit)        sage → Lot 33 (Sage, commuter/resident)
          libn → Lot 25 (Flagler, commuter/faculty)             libs → Lot 41 (LBC, commuter/faculty)
          hollis → Lot 08 (Hollis Center, faculty/visitor/resident)   east → Lot 24 (Soccer Fields, faculty/visitor)
          west1 → Lot 42 (Michigan Ave, commuter)               west2 → Lot 54 (Dog Park, commuter)
          stetson → Lot 40 (Facilities, faculty/visitor)
          Stall counts are still ours, not Stetson's; real counts come with real cameras.
  landed (DK file, by BD): LOT_MARKERS moved onto those lots by the same fit as the buildings, then nudged off roads and
          buildings (checked by code: no overlaps); lot labels pick a side so none clash or leave the map;
          Fit now fills the map box's width, and with the Buildings switch on it fits the map's height and gives the rest
          of the box to a full-height directory; tabs are colour-coded with icons (All green P, Regular car, ADA blue,
          EV purple, Buildings teal, set apart by a divider); Release spot clears the route, close-up and side panel;
          search takes "Lot 41" (a bare number stays a building number, as on the official map).
  checked: page walk, counted lots, two-driver claim with no-show notice, label clash test; no page errors.
  docs: README run steps now sim --minutes 900 and server --speed 10; CONTRACT SK-LAYOUT lists official_lot/permits.
  note: the page's second text block is now ~56 KB of Java's 64 KB limit; the next big addition needs a part3.
  → DK: please review WebPage; when your live map lands, campus.json is where lat/long per lot should go.
  → DI: nothing to change; lot names in status come from campus.json as before.

2026-10-12 · page layout: whole map in view · edited DK file at the lead's request
  landed (DK file, by BD): Fit shows the whole campus with no scrolling (zoom to the box's height) and shrinks the map box
          to the map's width; the right-hand column (.side-col) takes the rest. The building directory moved out of the
          map into that column, two columns wide, with a close button (closing = Buildings switch off). The lot window
          now opens over map and column together so it keeps its full width. Legend made compact.
  checked: 1366×768, 1700×1000, 1920×1080: no scrolling inside the map or the page; page walk and claim/release still clean.
  → DK: layout is .layout = .map-box (width set by fit()) + .side-col (flex: 1, min 320px); phones stack them.

2026-10-12 · claim rules on the page; legend fades · edited DI and DK files at the lead's request
  landed (DI file, by BD): POST /claim takes vehicle_class and refuses a regular car claiming an ADA or EV spot (409 wrong_type).
          Found by test: with "All spots" selected, a regular driver could claim an ADA stall; guidance never sent one there,
          but nothing stopped a claim.
  landed (DK file, by BD): "Claim this spot" is always shown and greyed out (not clickable) unless the spot is seen free
          and suits the car; the reason is on hover; "Just show the way" offers directions without a claim.
          The map legend is hidden until the pointer is over the map, fades in, fades out slowly on leave, and stays
          hidden while zoomed in past Fit.
  checked: page walk; taken vs free spot buttons; regular→ADA claim refused by the server, ADA→ADA accepted; claim rule tests.
  → DI: please review the vehicle_class check in do_POST.

2026-10-12 · map layout: stretched middle, calm pins, live lot list · edited DK file at the lead's request
  landed (DK file, by BD):
    stretch  — WX()/WY() map picture units to drawn pixels: space grows around the dense centre and eases toward the
               edges, total size unchanged. One stretch per axis, so roads stay straight; buildings keep their size and
               only their spacing changes (they shrink only where an edge is squeezed). Measurements (closest lots,
               route directions) still use the real, unstretched positions. Tune it in STRETCH.
               Checked: building/road overlaps went from 30 (all already in the original placement) to 21, none new.
    pins     — only lot pins and the 10 landmarks show; every other building is an outline whose name appears on
               hover. The Buildings switch brings all pins + the directory; closing it takes them away.
    layout   — right column 360px: help card + "Lots right now" (every lot, colour, fill bar, count; most room first,
               old data last; same verdict as the pins). With Buildings on, the column widens to 560px for the
               directory and the list steps aside. The map box takes the rest and Fit fills it; the streets, lawn and
               trees run on past the picture's edges (bleed) instead of leaving empty lawn.
    size     — the page is now cut into part1/part2/part3 (Java's 64 KB per string constant); cut at function boundaries.
  checked: 1366×768, 1600×900, 1920×1080 with no scrolling; hover names; switch open/close; list row opens its lot;
           page walk, counted lots, claim buttons, legend fade, two-driver claim with no-show notice.
  → DK: please review; when your live map lands, the stretch is no longer needed (real tiles handle zoom).

2026-10-13 · labels place themselves · edited DK file at the lead's request
  landed (DK file, by BD): placeLabels() — landmark names, then lot labels, each try right / left / below / above their pin
          and keep the spot that covers least (names, pins, other labels; off-screen counts as covering). A label only
          moves when it covers something, so live counts don't make labels hop. Runs after every update and every Fit.
          Fixed on the way: Flagler's lot label sat on Flagler Hall and Elizabeth Hall; Edmunds Center's on its building;
          the Elizabeth Hall pin covered the "Flagler Hall" name.
  checked: 7 overlaps before, 0 after, at 1366×768, 1600×900, 1920×1080; no side changes over 20 s of live updates.
