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

2026-10-13 · live location · edited DK file at the lead's request
  georeference: five road crossings read off Google Maps by BD (Woodland & Michigan, Woodland & Pennsylvania, Amelia &
          University, Garfield & Minnesota, Amelia & Ohio) fitted to the drawing: every point within ~1 m, each predicted
          from the other four within 4 m; north-up to 0.2°; 1 picture unit ≈ 1.81 m. In the page as GEO / geoToPic().
  landed (DK file, by BD): with permission (watchPosition), a blue dot + accuracy ring; routes, directions and the close-up
          start from the driver when on campus (origin()), else from the Main Gate; a location card heads the right column
          (nearest lot with room + distance, or off campus with km to the gate, or location off); lot list shows metres
          from you; the nearest lot with room opens by itself once, only after both location and live data are in;
          building windows quote real straight-line metres again ("About 241 m from the CUB").
          Location stays in the browser: never sent to the server, never stored.
          The right column scrolls by itself on short screens instead of the page.
  checked: virtual driver by the CUB (opens Lot 08, 212 m), moving driver, route from the driver, off campus 3.2 km north,
           location refused; page walk, layout at three sizes, claims with no-show notice.
  note: browsers share location only over HTTPS or on localhost; hosting must be HTTPS for phones.
  → DK: origin(), drawMe(), renderMeCard() are the pieces your live map will need to keep.

2026-10-13 · simulator: a campus day, not a frozen morning; collapsible location card
  why: from ~9:00 to 11:45 the whole campus saw only 3–10 stall changes per 15 min (none at all 10:00–10:15):
       75% of drivers stayed 4–8 h, arrivals all but stopped after 10 a.m., so lots filled and the map looked stuck.
  landed: sim.py — arrivals continue all day (26/h per 120 stalls until 3 p.m.) and bunch in the 15 min before each hour;
          half the drivers are class-hoppers who leave at :50–:59 after 1–3 classes, 20% stay half a day, 30% all day.
          Result: ~55 changes per half hour around each class change, ~15 between; every lot changes at least every
          25–40 min of campus time (the two smallest about hourly); campus free count moves between ~50 and 85 of 200.
  landed (DK file, by BD): the location card collapses to one bar ("Live location · on campus" + arrow); the arrow drops
          the details down again; the choice is remembered in the browser.
  checked: guidance (no violations), all 12 claim tests on the new day, page walk, location cases, layout at three sizes.
  → DI: feeds are bigger in the middle of the day now; nothing in the shape changed.
  → everyone: rerun `python sim.py --minutes 900` to get the new day.

2026-10-13 · launcher (V-5) · new file run.py
  landed: run.py — `python run.py` makes a day of data if missing (--fresh for a new one), starts parkfind.server and
          the Java page as child processes, waits until each answers, opens the browser, prints a live board every 10 s,
          restarts the data server from the morning when the recorded day ends (claims clear on that loop), and stops
          every child on Ctrl+C or if one of them dies. Refuses to start if 8765/8085 are taken, and says why.
          Logs: out/logs/server.log, out/logs/page.log (out/ is gitignored).
  checked: full day at 600x with the loop and Ctrl+C (no processes left behind); busy-port refusal.
  docs: README "See it in the browser" leads with python run.py; BRIDGES lists run.py in BD's lane.
  → DI, DK: nothing changes in your files; the three manual commands still work.

2026-10-13 · routes along roads; guaranteed-first suggestions; close-up folds · edited DK file at the lead's request
  landed (DK file, by BD):
    routes  — ROAD_LINES (every drawn road's centreline, picture units) → a network of crossings and road pieces;
              Dijkstra finds the shortest drive in metres (shortestDrive, tripTo). Start snaps to the nearest road,
              the end is where the lot meets its road. Drawn through WX/WY, so the route stays on the asphalt.
              Directions name the streets ("Turn right onto E Michigan Ave and go about 255 m").
              The unlabelled connector by Rinker Field is Bert Fish Dr on Stetson's map.
              CLOSED = [] holds stretches cars can't use; one line each, and every route avoids them.
              Checked: 9 lots × 2 starts, every middle segment lies on a road centreline.
    location card — leads with the nearest lot where a live camera sees a free spot for this car (guaranteed);
              a closer slow-sensor lot with room shows underneath as "not guaranteed"; auto-open picks the guaranteed one.
    close-up — folds to its title bar with an arrow (remembered); shows the real route around you.
  note: page is now part1 / part2 / part2b / part3 (Java's 64 KB per string).
  open: which drawn road stretches are not drivable (e.g. University or Minnesota between Woodland and Amelia).

2026-10-13 · BD-10: three lots on real photos (PKLot) · new pklot_cameras.py, cameras/, vision.py rewritten
  landed: pklot_cameras.py (stdlib) — PKLot labels → cameras/sage.json (UFPR05, Fri 2013-02-22), cameras/libn.json
          (PUCPR, Thu 2012-11-08), cameras/west1.json (UFPR04, Tue 2013-01-22): stall map (Stetson stall ← PKLot space,
          the spaces that change most on the tuning days), tuning photos with labels, replayed photos (labels kept for
          grading only). Photos keep their clock time on the replay day (2026-09-21).
  landed: vision.py — each stall's empty look (median of tuning photos labelled empty), then two numbers per stall
          (difference from empty, edge detail) → one logistic model per camera; caution set on the tuning days by
          learning on one day and reading another (wrong "free" ≤ 5%); grade printed and saved (out/vision/<lot>.grade.json).
          Gate: near_live only if the replayed day's wrong-"free" ≤ 5%, else periodic_snapshot (rows and counts).
          Grades: Sage 99.4% right / 2.5% wrong free → passes; Flagler 99.9% / 0.0% → passes;
                  Michigan Ave 94.4% / 20.2% → fails (rows only), even after adding a cloudy tuning day.
          The first baseline (edge energy alone) scored 57% on Sage with 68% wrong "free"; it is gone.
  landed: sim.py --skip <lots> (no simulated sensor there; World still turns so other lots' days are unchanged;
          truth.json lists camera_lots); run.py reads cameras with photos on this machine, simulates the rest,
          merges by observed_at into out/latest/feed.jsonl, prints each camera's grade at start.
  landed (DK file, by BD): a failed-gate camera's row answer says "camera isn't accurate enough yet", not "too slow".
  checked: merged feed in time order with all 8 sources; Sage/Flagler give stall answers, Michigan Ave rows only,
           no claim there; page walk, routes, location card on the merged feed.
  → DI: feed has three new sources (camera.ufpr05/.pucpr/.ufpr04); truth.json "camera_lots" must be skipped in tests.
  → DK: nothing to change; photo lots look like any other lot, with their source in the answer.
  landed (DK file, by BD): location card names the closer, not-guaranteed lot in amber (#b45309), matching "Filling up".

2026-10-13 · BD-11: score every lot, photo lots included
  landed: run.py splice_camera_truth: photo lots' truth comes from PKLot's labels (held up to 10 min between
          photos, absent after the last one); truth.json gains truth_sources. Labels never reach the feed.
  landed (DI lane, by BD, agreed with BD): tests/score_day.py: replays the day through the server's own reader,
          lastseen.status and guidance.answer, and checks each against truth.json. Exit 1 if named spots >5% taken.
  found: Sage FAILS end-to-end: 16.7% of named spots really taken, though only 2.8% of its "free" reads are wrong.
         Two stalls (D-06, D-07) read free while taken; when the rest of the lot fills, guidance names exactly them.
         A camera-wide gate cannot see this. Next: decide a per-stall gate (BD, vision.py).
  → DI: score_day.py is yours now; rewrite freely. Your tests can stop skipping camera_lots: their truth is real.
  → DK: nothing.

2026-10-13 · BD-12: per-stall gate (vision.py)
  landed: vision.py trains a trust flag per stall from the tuning days' cross-day test (MIN_FREE_CALLS 20, 5% limit);
          untrusted stalls report periodic_snapshot. The camera gate now checks the spot guidance would name per
          photo, not single readings: errors bunch where the lot fills, which is where it names.
  result: Sage names 23/32 (row D out), named spot taken 1.1% (was 16.7%). Flagler 19/20, 0.0%.
          Michigan Ave: 19/24 trusted, but named spot taken 7.4% -> stays rows and counts. score_day.py PASS.
  run.py: startup summary shows "named spot taken" and "names N of M stalls".
  → DI: a lot can now mix near_live and periodic_snapshot stalls; lastseen and the claim rules already handle it.
  → DK: nothing; guaranteedSpots() already counts only live stalls.

2026-10-13 · BD-12b: Michigan Ave, more cloudy tuning days (tried, reverted)
  tried: rule fixed in advance: add every earlier busy, mostly-cloudy weekday (weather tags only): 2013-01-15, 01-16.
  result: worse: named spot taken 29.6% (was 7.4%), 92.8% right. One median "empty look" per stall blurs across
          light, and the new tuning days re-picked which PKLot spaces become Stetson stalls.
  kept: original tuning days; Michigan Ave stays rows and counts (gate held both times). score_day.py PASS.
  lesson: more data does not fix this model; the next step is the model (empty looks per light), tested on a
          validation day before the replayed day is touched again.

2026-10-13 · BD-13: validation and exam days; per-light model; UFPR04 outline fix
  landed: camera files carry tuning / validation / replay / exam photos (with weather) and the chosen model.
          vision.py --validate (choose models here only) and --exam (once per final model, writes <lot>.exam.json);
          one grade() for all three graded days. Models: median (one empty look) or per_light (one per weather).
  found: UFPR04's stall outlines moved up to 146 px between December and January; we had been cutting December
         photos (tuning 12-14) with January outlines. pklot_cameras.py now refuses any day whose outlines moved
         more than 3 px. So BD-12b's "per-light blur" reading was partly wrong: the camera had moved.
  chosen on validation (named spot taken): sage per_light 1.8% vs median 1.8%, tie broken by 'free' wrong 1.9% vs 6.3%;
         libn per_light 2.3% vs 3.0%; west1 per_light 0.0% vs 0.7% (Michigan Ave validation 98.2% right, was 66.8%).
  replayed day: Sage 24/32 named, 1.1%; Flagler 19/20, 0.0%; Michigan Ave 17.2% -> rows and counts only.
  exam (once): Sage 5.3% (2 of 38: just over the line, small sample); Flagler 0.0%; Michigan Ave 7.9%.
  score_day.py: PASS; new "worst hr" column.
  → DI: score_day.py has a worst-hour column; nothing else changed for you.

2026-10-13 · BD-14: Google street map under the close-up (DK file, by BD, user's call)
  landed (WebPage): mapsKey() reads GOOGLE_MAPS_KEY or maps.key (gitignored), refuses odd values, injects __MAPS_KEY__.
          One Static Maps picture, fixed on campus (29.0358,-81.2996, zoom 16, 640x640 @2x), same URL for everyone:
          the driver's position never reaches Google. Placed with an affine from three corners (our drawing's axes
          are ~1.7 deg off square; a plain rectangle put crossings up to 19 m off; the affine: within 2 cm of geoToPic).
          Close-up draws in real (unstretched) units on that picture: tripTo() route, dot, accuracy ring,
          "Map data © Google". One download per visit. No key / refused key -> our drawn close-up, as before.
  checked: stand-in picture with the five surveyed crossings: the dot lands in its ring; 403 falls back cleanly.
  → DK: your live map with real tiles can reuse GMAP / GMAP_MATRIX; keep the fixed-picture rule or change CONTRACT.

2026-10-13 · BD-15: close-up on OpenStreetMap, nearest landmark, turnable (DK file, by BD); Google reverted
  reverted: BD-14's Google close-up, mapsKey() and maps.key (user's call: a free map instead).
  landed (WebPage): one fixed set of 30 OSM tiles (zoom 17) covering campus, the same for everyone, placed with the
          same three-corner affine (surveyed crossings land where geoToPic puts them); our roads and buildings drawn
          underneath, so blocked tiles still leave a map. "© OpenStreetMap contributors" in the corner.
          Nearest landmark (LANDMARKS) outlined in amber, named on the map or on an edge arrow, and in a line under
          the title with distance and ground compass direction ("Hollis Center, 160 m west").
          Turnable: ↺ ↻ by 30°, a needle that shows north (tap: north-up); on phones ◎ turns with the compass
          (iPhone asks permission; sideways screens handled; at most 5 redraws a second). Labels stay upright.
          ROAD_LINES now keep each road's width (for the close-up).
  checked: stand-in tiles with the surveyed crossings: a dot 40 m E / 30 m S of one lands 39 m / 30 m from its ring;
           90° turn puts west at the top and the needle right; tiles blocked -> our drawing; ◎ only on touch screens;
           collapse hides map and landmark line; no page errors.
  note: OSM's tile policy asks for light use and credit; 30 tiles per visit, browser-cached, is fine for a demo,
        not for a public launch (then: a tile provider plan or our own tiles).
  → DK: for your live map, the same tiles + OSM_MATRIX fit our coordinates; keep the fixed-tiles rule (CONTRACT).

2026-10-13 · BD-16: close-up as a navigation view (DK file, by BD)
  landed (WebPage): street-level OSM tiles (zoom 18, one fixed set of 88 for campus, loaded the first time the
          close-up shows); 320 x 230 view; +/- zoom (about 160 / 290 / 510 m across, remembered); you sit at 62% height
          so more road ahead shows; next-turn banner from the same Dijkstra trip ("400 m · Turn left onto N Amelia
          Ave", matches roadSteps); P pin for the lot or an edge arrow with its distance; scale bar; heading beam in
          compass mode; edge labels step aside so they never overlap; credit kept.
  checked: stand-in z18 tiles: crossing ring where it should be; banners match the written steps (Sage, LBC,
           Facilities from the gate); 90° turn, zoom limits, tiles blocked -> our drawing, phone view; no errors.
  open: claims never "arrive" in the demo (the feed is a recording; nobody drives your car). Design agreed in
        principle with the user (camera decides; "I've parked" optional and checked against the camera; driver
        reports on low-visibility lots; demo car). Waiting on three answers before building.

2026-10-13 · BD-17: arrival you can trust (server half); driver reports
  found: claims never "arrived" in the demo because the claimed stall usually stayed free in the recording, and a
         recorded car that did park there was credited to the claimer without asking whose car it was.
  landed: claims.py phases held -> car_seen -> arrived. car_seen = a sensor saw a car after the claim (anyone's).
          arrived = "I've parked" agreed with the camera (camera wins; a tap before the camera's next picture is
          remembered and confirms itself), or on a slow stall the driver's report. New outcomes: not_seen (said parked,
          never seen), taken (the page says the car was someone else's). POST /parked, POST /taken.
          reports.py (new, BD): driver reports as SK-EVENTs (source driver.report, cadence event_only): row counts
          (10 min; refused on rows a live camera watches) and "I've parked" on slow stalls (until the next reading).
          POST /report. server.py (DI file, by BD): current_status reads reports alongside the feed; new endpoints.
          WebPage bridge only: car_seen shown as "car detected", not_seen release message. Full page: BD-18.
  checked: point A (recorded car arrives in the window -> car_seen -> "I've parked" -> confirmed); taken; not_seen;
           slow stall recorded and reads occupied from driver.report; row report used by guidance (zone grain,
           ADA taken off for a regular car), refused on a camera row, gone after 10 min; old claim tests 12/12.
  → DI: server.py has /parked, /taken, /report and current_status(…, reports). Please review; tests welcome.
  → DK: SK-CLAIM phases and SK-REPORT in CONTRACT; BD-18 adds the buttons to the page.

2026-10-13 · BD-18: the page side of arrival; trip card; routes pick the best road to join (DK file, by BD)
  landed (WebPage): trip card at the top of the right column (under "Live · updated"): spot, state (held / waiting
          for the camera / car seen: "Was that you?" / parked / showing the way), what the sensor last saw, and
          buttons: I've parked (green), Release / I've left (red outline), Yes, I parked / No, not me, Show lot,
          End route (grey). Parked -> the route leaves the map, the card stays. No, not me -> POST /taken, toast,
          the lot opens on the next best spot. Window footer: one non-wrapping group, Cancel grey, Just show the
          way blue outline, Claim green. "Here now? Help other drivers" row report in lots without full live
          cameras (POST /report) and drivers' reports shown there. showRoute keeps only the directions.
  fixed (routing): both maps attached you to the single nearest road before Dijkstra, so from 30 m off one road
          and 40 m off another it could take the long way. Now every road within ~80 m of you (and every road
          touching the lot) is a Dijkstra start (end), costed by its off-road metres. 40 random starts x 9 lots:
          0 longer, 199 of 360 shorter (up to 108 m), 0 legs off a road, 0 failures.
  checked (browser, 30x, recorded day): held -> car arrives 11:08 -> "Was that you?" -> Yes -> "Confirmed: the
          camera sees your car at A-05" -> parked, route off the map -> I've left; A-06 -> No, not me -> lot opens on
          A-08; LBC "I've parked" recorded from the driver; Edmunds report sent and shown; way-only card; card
          placement at 1600 and 1366; footer on one row; no page errors. score_day PASS.
  next: BD-19 answers "Was that you?" from location (far away -> taken, auto-claim the next spot, Undo).

2026-10-13 · BD-19: whose car was it? answered from location (DK file, by BD)
  landed (WebPage): judgeCarSeen() on every poll: car_seen + you within ~60 m of the lot (+ GPS accuracy) -> POST
          /parked (camera still decides); 120 m or more away -> card "Someone else parked in A-06. You're about
          843 m away... Finding you another spot in 5 s" with Find another now / That was me; then POST /taken,
          ask guidance for a stall in the same lot, else the nearest lot with a guaranteed spot, claimSpot it,
          toast names the new spot, route redrawn. In between or no location: "Was that you?". Location never
          leaves the page (CONTRACT line added).
  fixed: standing at a lot made a trip with no road leg; the written steps looked up a road that does not exist and
         threw, and claimSpot's catch called it a network problem. Steps now say "You're at <lot>: make your way
         in"; the banner says the same; .catch only blames the network for real network errors (isNetworkError).
  checked (4 drivers at once, 30x, recorded day): at Sage -> parked with no tap; 843 m away -> countdown -> A-06
         released as taken -> A-08 held, route updated; far + "That was me" -> parked; 91 m away -> asked.
         Steps/banner from 49 points x 9 lots: 0 errors, 0 "undefined". Slice-2 flow 24/24, routing unchanged.

2026-10-13 · BD-20: held vs yours, footer by stage; permits and find-my-car built in, switched off (DK file, by BD)
  explained: your own spot is solid blue on purpose ("yours"); purple is someone else's hold. The legend never said
             so: it now has "Yours" and "Held by others".
  fixed: the lot window offered Start route for your spot at every stage. Now: held -> Release + Start route;
         car seen -> Yes, I parked / No, not me; parked -> I've left.
  landed: FEATURES = { findMyCar: false, permits: false } (one switch; ?features=findMyCar,permits for a demo).
          Permits: WebPage.java passes campus.json permits per lot; "Parking as" chip (Any / Commuter / Resident /
          Faculty-staff / Visitor, remembered); lots you can't use fade (pins, list, last in the list), are skipped
          by suggestions and the automatic next-spot claim, can't be claimed, and say whose lot they are.
          server.py (DI file, by BD): /claim&permit=... -> 409 wrong_permit. Later a gate camera sets the permit.
          Find my car: parked -> Find my car -> the route from you to your spot (card "Finding your car", Found it).
          The driver id now lives in the browser, so a reload keeps your claim (needed to find your car later).
  checked: features off: no chip, no fades, no button, legend + "yours" colour, parked footer, reload keeps claim.
           on: visitor fades Flagler/LBC/Sage/Michigan Ave/Dog Park, suggestion moves to Facilities, page and server
           refuse Sage (409 wrong_permit), Hollis allowed (200); Find my car survives polls, Found it ends it. 21/21.
  known: find-my-car directions use driving words ("Head west on ..."); walking words when the feature goes live.

2026-10-13 · BD-21: the demo drive (DK file + DI file, by BD; parkfind/demo.py new, BD)
  landed: parkfind/demo.py DemoBook: POST /demo/park puts the driver's demo car on their claimed stall as a camera
          reading (source demo.car, the camera's cadence and ttl) stamped at every read (to the millisecond: a
          sensor reporting on the whole second would tie, and ties go to the older) while the claim lasts; refused
          on slow stalls ("slow": the driver taps I've parked) and where a car got there first ("occupied").
          server.py: --demo (run.py passes it), SK-VIEW "demo": {speed}, demo cars read with the feed and reports.
          claims.py: holder(), mine(). WebPage: "Drive there (demo)" on a held spot; the dot drives tripTo() at
          20 km/h x replay speed, map, mini map and banner follow, real location waits (kept for after);
          at the lot -> /demo/park -> the camera sees the car -> location says it is you -> confirmed -> parked.
  fixed on the way: the nearest-lot window popped open when the demo dot appeared (first "location");
          whose-car was re-judged on later polls, so a car seen while you were 85 m away became "yours" once you
          drove up: now decided once, from where you were when it appeared; a re-claim in flight looked like
          "no claim" and ended the demo (demoHandoff); a next spot in the same lot is a zero-length drive.
  checked (browser): camera lot: drive -> parked, survives polls, I've left -> demo car gone; slow lot -> tap
          I've parked; recorded car takes Sage A-05 mid-drive -> released as taken -> A-06 held -> drives on ->
          parked, never two cars in A-05. Regression: four drivers, slice-2 flow 24/24, features 21/21, routing,
          step sweep 441/441, claims 12/12 + 15/15, score_day PASS.

2026-10-13 · BD-22: hold sized by the drive (TeamVote V-6, built, awaiting DI/DK)
  landed: claims.py hold_window(hold_min): whole minutes from the page, clamped 4-15; none -> 8 (old rule); slower
          sensors still add 5/15. server.py: /claim&hold_min=. WebPage: holdMinutes() = route metres at 20 km/h x1.3
          + 3 min, sent with every claim (also the automatic re-claim); card says "Held N min, sized to your drive";
          the demo car drives at the same CAMPUS_KMH. CONTRACT: hold_min is the only trace of position sent.
  checked: clamps and default (5/5); at Sage 58 m -> 4 min, gate -> Sage 509 m -> 5 min, gate -> Facilities 1084 m
           -> 8 min; claim requests carry only stall_id, driver_id, vehicle_class, hold_min. Regression: four
           drivers 11/11 (test re-cast: a driver 90 m away now gets 4 min, so the old stall's car came too late,
           correctly released), demo 3 scenarios, flow 24/24, features 21/21, claims 12/12 + 15/15.
  → DI, DK: please vote on V-6 in TeamVote.md.

2026-10-13 · BD-23: one extension on the way (V-7); arrival margin (V-8); forecast graded honestly
  landed: claims.py extend() (once, held, before the deadline, +2..5) + POST /extend. WebPage maybeExtend(): road
          metres at claim (or at demo-drive start) vs now; 50 m closer and not at the lot, within the last ~90 s
          (wider at fast replay speeds) -> /extend; toast + "Extended once because you're on your way."
          parkfind/forecast.py (new, BD): per-lot counts now, -10, -20 min (minute cache), trend + DRIFT_PER_MIN;
          SK-VIEW "forecast". WebPage arrival(): ETA from the route; "may be gone" when free <= ceil(drift x ETA);
          lotSuggestions prefers lots with margin; location card and lot window say it. score_day grades the
          forecast (trend vs "stays") at 5 and 10 minutes.
  finding: the trend line lost to "stays as it is now" on validation days (sim seeds 11, 13, 17): average error
          15-25% worse at 5 and 10 min; half-strength and falling-only only tied. Model chosen by a rule fixed
          before looking at those days: "stays" + drift margin. Honest note: the replayed day's grade was looked at
          before the rule was set; its verdict agrees. The simulated lots never fill; full lots come from photos.
  checked: extend rules 4/4; E1 moved 1073 -> 539 m -> +4 min once; E2 still -> no extension; margin moves the
           suggestion; view ~12 ms; regression: four drivers 11/11, demo 3 scenarios, hold 6/6, flow 24/24,
           features 21/21, routing, sweep 441/441, claims 12/12 + 15/15.
  → DI, DK: votes on V-6, V-7, V-8 in TeamVote.md.

2026-10-13 · BD-24: drivers' confirmations as camera labels (pipeline built; one day is too little to help)
  landed: parkfind/confirmations.py (new) LabelLog: confirmations from real camera readings only (never demo.car,
          simulator or driver reports) -> out/<run>/labels.jsonl. claims.py logs "I've parked" + camera
          (driver_and_camera) and disputed not-seen; server.py logs "No, not me" (someone_else) and "I've left"
          after a confirmed arrival (driver_left, joined to the first photo within 10 min). labels.py (new):
          collect (log -> out/labels/<lot>.json, graded vs the people's labels) and simulate --p (synthetic drivers at
          real arrivals/departures). vision.py --with-labels: learns from partial labels (only the confirmed stall
          per photo), model saved as <lot>.<model>.drivers.npz, and grades the gate on the validation day because
          the labels come from the replayed day.
  result (validation day, never trained on): west1 98.2% -> 98.2% right at p=0.3 (42 labels), 98.3% at p=1.0
          (116 labels: every arrival and departure that day); sage 99.1% -> 99.1%. A day of confirmations is a
          trickle next to ~7,700 training views. Proposed instead for now: V-9, confirmations as a camera health check.
  checked: only camera readings logged (demo.car/simulator refused); confirmed arrival logged on the photo that saw
           the car; collect joins to photos; regression: four drivers 11/11, demo x3, extension 5/5, flow 24/24,
           features 21/21, hold 6/6, claims 12/12 + 15/15.

2026-10-13 · BD-25: phone-ready; camera health check (V-9 built)
  landed (WebPage): the page asks its own address (/api/...); ApiProxy passes GET/POST to the data server
          (PARKFIND_API, default localhost:8765), 502 + JSON when it is down; thread pools so the proxy never queues
          pages. HTTPS on 8443 when PARKFIND_HTTPS names a PKCS12 keystore. Phone layout (<= 900 px): trip card
          above the map, close-up under it, 44 px buttons, full-screen lot window, chips scroll, 16 px search (no
          iPhone zoom), no sideways scroll; screen wake lock while a route runs. Footer for your own held spot now
          says "Held for you until ..." (was "Not seen free right now").
          run.py --phone: Wi-Fi address (UDP connect, nothing sent), keytool certificate for it (+127.0.0.1,
          localhost) in out/phone/, remade when the address changes; prints the phone address and the two
          one-time steps (accept the warning, allow Java on private networks).
  landed (V-9): confirmations.py health per camera (last 50; agree: driver_and_camera, someone_else; disagree:
          driver_found_car, disputed_not_seen; flag at >= 10, >= 2 against, rate >= max(10%, 2 x graded error));
          rebuilt from the log on restart. server.py: SK-VIEW camera_health, /taken?reason=found_car, graded levels
          from out/vision/*.grade.json. WebPage: "There's a car in it" on a held spot (labels the camera wrong,
          re-claims, never the same spot); warnings in the lot list and window; run.py board marks "(camera?)".
  checked: proxy GET/POST, HTTPS page + api, certificate names, 502 when down; iPhone 13 over HTTPS on a non-
           localhost address: secure context, live data, location on, layout 10/10; health rules 7/7 (one
           contradiction never flags); seeded log -> Sage flagged 3 of 12, warnings shown; "There's a car in it"
           -> thanked, B-03 held (was re-claiming B-02: fixed). Regression: four drivers 11/11, demo x3, extension
           5/5, flow 24/24, features 21/21, hold 6/6, routing, sweep, claims 12/12 + 15/15.
  open: V-9 entry in TeamVote.md still says "proposed (not built)"; not edited (TeamVote changes need BD's OK).
  TeamVote (with BD's OK, 2026-10-13): V-6..V-9 kept, V-9 marked built; V-10 added (flagged camera stops naming spots,
  only when 3+ different drivers contradicted it; proposed, not built).
