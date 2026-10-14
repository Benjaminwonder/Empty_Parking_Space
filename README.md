# ParkFind

> Which empty stall — or the smallest honest zone — should this driver go to **right now**, and how sure are we given the age of the last observation?

ParkFind gets a driver to a free parking stall in a large lot without circling. It works when the lot has live cameras **and** when the best feed is a snapshot every 5 minutes, 15 minutes, or an hour.

This is not a payment app, a curb-meter city platform, or a YOLO demo on PKLot. Occupancy is a spectrum. Unknown is not free.

---

## Why this exists

Most open parking repos stop at a green/red overlay on a camera frame.

| What those repos do well | What they leave the driver with |
| --- | --- |
| Detect cars in painted stalls from one overhead view | A map, not a destination |
| Assume a continuous video stream | Silence when the lot only updates every 15 minutes |
| Publish PKLot / CNRPark accuracy | No aisle path, no contention, no data-age clock |

Drivers do not fail because the detector was 2 points off. They fail because they were sent to a stall that is stale, contested, or unreachable from the entrance they just used.

**v1 success (one pilot lot)**

- Cut median in-lot search time by ~40%
- Recommend a free stall/bay with ≥90% daylight accuracy **when live sensing exists**
- Still give a useful, honest recommendation when the lot only updates on a timer

---

## What the driver sees

Fresh + high confidence → a specific stall, held briefly.

5–15 minutes old → a row or zone, last-seen clock visible, short or no exclusive hold.

Hour-old → “this deck is usually emptier at this hour; last count said ~20 free.” No stall pin.

Two drivers in flight + stale data → they are not sent to the same guessed stall.

```
You  →  filter constraints (ADA / EV / height / vehicle)
     →  free + confident + fresh enough
     →  score travel cost + uncertainty + contention + data age
     →  hold only when freshness supports it
     →  instant reassign on "taken"
```

---

## Run it (about ten minutes)

You need Python 3.10 or newer. Nothing else to install.

```
git clone https://github.com/Benjaminwonder/Empty_Parking_Space.git
cd Empty_Parking_Space
python --version
python sim.py
```

On Windows, if `python` is not found, use `py`.

You should see one line every 30 simulated minutes, 06:30 to 09:30 lot time, showing how full
each of the nine lots is, ending with `lots=9  stalls=200  arrivals=166  departures=21  events=14187`.
The run writes:

- `out/latest/feed.jsonl`: the sensor reports, one per line (what ParkFind reads)
- `out/latest/truth.json`: what was really true each tick (tests only)

To check a played day against the truth (photo lots use the people's labels on each photo):

```
python tests/score_day.py
```

It prints one row per lot and exits 1 if any lot named a spot that was really taken more than 5% of the time.

Two runs the team uses:

```
python sim.py --cadence continuous --out out/quick
python sim.py --cadence periodic_15min,hourly --out out/slow
```

Without `--cadence`, each lot uses its own sensors from `campus.json`: some live cameras, some
slow snapshots, one gate counter. With it, every lot gets the same sensor: the first line gives the
whole campus live cameras, the second only slow feeds. Same morning, very different certainty.

Where things live:

- `sim.py`: the fake lot and its fake sensors
- `campus.json`: the nine lots (200 stalls) everyone reads; each stands for a real Stetson lot (`official_lot`, `permits`)
- `parkfind/`: the program itself: `event.py` (the update format), `clock.py` (what time it is),
  `lastseen.py` (what every stall last looked like), `guidance.py` (where to send a driver),
  `claims.py` (who holds which spot), `server.py` (serves it all to the page)
- `WebPage`: the map drivers use (Java, served at http://localhost:8085)
- `BRIDGES.md` and `handoff/`: how the team splits and hands off work

### See it in the browser

One command, from the repo folder (needs Java 17 or newer for the page):

```
python run.py
```

It makes a day of data if there is none, starts the data server and the page, opens your browser,
and shows a live board in the terminal (campus time and free spots per lot). When the recorded day
ends it starts again from the morning. Ctrl+C stops everything. Options: `--fresh` (new day of data),
`--speed 60` (faster), `--no-browser`, `--quiet`. The servers' own output goes to `out/logs/`.

The same thing by hand, in three terminals, all in the repo folder:

```
python sim.py --minutes 900
python -m parkfind.server --run out/latest --speed 10
java --source 17 WebPage
```

Then open http://localhost:8085. The simulator writes a full day from 06:30 lot time; the server
replays it ten times faster than real time (so an 8-minute hold takes 48 seconds); the
page asks for fresh status every five seconds.
To freeze the morning at one moment instead, start the server with
`--now 2026-09-21T08:15:00-04:00 --speed 0`.

Click a P pin to open that lot: it leads with the best spot for your car and how old that
sighting is; stalls show free, taken, held or unknown, and lots that only count cars (an hourly
count, a gate) show their counts row by row with their age. Press **Claim this spot** and nobody
else is sent there; if no car reaches it in time (about your drive time, see below; slower cameras add
their 5 or 15 minutes), it is released and you are told. Search takes buildings, lots or spots: `CUB`, `Lot 41`, `Sage B-04`.

Your spot lives in a card at the top of the right column, under "Live · updated": held until
when, what the camera last saw, and the buttons. A spot is held about as long as your drive to it
takes (4 to 15 minutes; the page sends only the minutes, never where you are). If you are visibly closer by
road near the end of the hold, it is extended once, by 2 to 5 minutes. Suggestions prefer a lot
that will still have room when you arrive: a lot with fewer free spots than it typically loses
during your drive (about one per 10 minutes) is marked "may be gone". `python tests/score_day.py`
also grades the arrival guess against a trend line, so we notice the day a trend starts to win. When the camera sees a car in your spot, your
location (used in the page only) decides whose it was: at the lot (about 60 m) you are parked;
far away (120 m or more) someone else took it, and after 5 seconds with "That was me" on screen
we hold the best spot left (same lot first) and update the route; in between, or without
location, it asks "Was that you?" (Yes, I parked / No, not me). "I've
parked" is checked against the camera, which wins; on slow-sensor lots your word counts until the
sensor checks. Once you are parked the route leaves the map. In the demo (run.py), a held spot offers "Drive there (demo)": your dot drives the route at
campus speed (20 km/h, times the replay speed), and at a camera lot the camera sees your car, so
the claim, "Was that you?" and parking all run on the product's own logic; at a slow lot you tap
"I've parked". Recorded cars still play: if one takes your spot on the way, you are moved to the
next spot and drive on. Two features are built but switched off until a campus needs them
(add `?features=findMyCar,permits` to the page address to try them): Find my car routes a parked
driver back to their spot, and Parking as (permit) fades lots your permit can't use and keeps them
out of suggestions and claims (the server refuses them too); later, gate cameras can set the permit. In lots no live camera fully
watches, "Here now? Help other drivers" lets you report roughly how many spots a row has free
(counted for 10 minutes, never a promised spot).

With your permission the page uses your location: a blue dot shows where you are, routes start
from you, and the nearest lot with room opens by itself once. Off campus or refused, everything
starts at the Main Gate instead. Location never leaves the page. Browsers only share location
over HTTPS or on localhost, so a phone reaching the page through a laptop gets the Main Gate.

The "You are here" close-up is a small navigation view on OpenStreetMap's street map (free, no
key): street level by default (+/- for about 160 / 290 / 510 m across), you just below the middle so more
road ahead shows, the next turn in a banner ("400 m · Turn left onto N Amelia Ave"), a P pin for the
lot (or an edge arrow with its distance), a scale bar, and the nearest landmark outlined and named
with its distance and direction. It turns: the round buttons turn it, the needle shows north (tap
it for north-up), and on a phone the extra button turns it with your compass.
The page asks OpenStreetMap for one fixed set of campus tiles, the same for everyone, and draws
your dot and route on top: the tile server sees that someone opened Stetson's map (and the
visitor's IP address, as with any web request), never where you are. If the tiles cannot load,
our own drawing shows instead.

Three lots run on real photos. PKLot's cameras (real lots, a photo every 5 minutes, every space
labelled by people) play one weekday each on the Stetson map: Sage · Lot 33, Flagler · Lot 25 and
Michigan Ave · Lot 42. `vision.py` learns each stall's empty look on other days, reads the replayed
day, and grades itself against the people's labels. Two gates decide what a driver is promised.
Stall by stall, on the tuning days: a stall the camera misreads (Sage's far row D) reports rows only.
Camera-wide, on the unseen day: the one spot guidance would name must be really free at least 19
times in 20. Sage names 24 of 32 stalls (named spot taken 1.1%), Flagler 19 of 20 (0.0%); Michigan
Ave fails (17.2%), so it reports rows and counts. `python tests/score_day.py` checks the whole day.

On a phone: `python run.py --phone` also serves the page over HTTPS at the laptop's Wi-Fi address
(printed at start, e.g. https://192.168.1.23:8443) with a certificate it makes once with Java's keytool.
Phones give location and the compass only to HTTPS pages. The phone warns once that the connection
isn't private (our own demo certificate): accept it. Windows may ask to let Java on private networks:
allow it. On a phone the trip card sits above the map, the close-up under it, buttons are thumb-sized,
and the screen stays on while a route runs (where the phone allows).

Each camera has a health check: over its last 50 confirmations, how often drivers contradicted it
("There's a car in it" where it said free, or "I've parked" it never saw). With 10 or more
confirmations, 2 or more against, and a rate of 10% (or twice its graded error, if higher), the lot
shows a warning in the lot list and window, and on the run.py board.

Drivers' confirmations become camera labels: "I've parked" agreed by the camera, "No, not me" and
"I've left" are logged (real camera readings only, never the demo car) and `python labels.py collect`
turns them into labelled photos; `python vision.py --camera cameras/west1.json --with-labels
out/labels/west1.json` learns from them. `python labels.py simulate --p 0.3` makes a synthetic set for
experiments. One day of confirmations changes nothing measurable (see handoff/BD.md, BD-24).

Each camera's days are kept apart: tuning (learn), validation (choose the model: `vision.py --validate`),
replayed (what drivers see, and the gate), exam (graded once per final model: `vision.py --exam`).
With the PKLot download in `data/`, `python pklot_cameras.py` then `python run.py` uses the photos;
without it, every lot is simulated.

The lots sit on real Stetson lots and every building carries its official name, from Stetson's
DeLand campus map (edition of 7 Aug 2026, stetson.edu/maps).

---

## Features

- **Honest guidance, not a fake live map.** Recommendation shrinks from stall → row → zone as the observation ages.
- **Occupancy fabric.** Sim, CCTV+YOLO, stall sensors, gate counts, partner APIs, periodic lot scrapes, and driver reports all write one canonical event.
- **Freshness as a first-class field.** Every state has `confidence`, `source`, `observed_at`, `ttl`, and `cadence_class`. Stale data becomes `unknown`.
- **Inside-lot maps.** Aisle graphs so we do not recommend a stall the driver cannot legally drive to from their current approach.
- **Claims that end on their own.** First driver to claim a spot gets it; no car within the arrival window, or the car has left, and it is released. No claims where no sensor can see the spot.
- **Driver reports as the patch between snapshots.** The live layer when cameras are not streaming.
- **ADA and EV stalls are first-class constraints**, not filters bolted on later.
- **Edge inference preferred.** Occupancy events leave the lot. Raw video does not have to.

---

## Architecture

```
adapters (sim | vision | sensors | gates | APIs | scrapes | reports)
        │
        ▼
 canonical occupancy event
        │
        ▼
 occupancy store (Postgres/PostGIS) + live snapshot / holds (Redis)
        │
        ├─► guidance engine  ─► driver app (stall or zone + age clock)
        └─► web occupancy map (operator / pilot view)
```

Adapters are swappable. The product is the event + the guidance rule, not a particular camera brand.

### One parking update (an occupancy event)

Every sensor (today the simulator, later a camera) reports in this one shape:

```json
{"state": "free", "confidence": 0.97, "source": "sim.continuous",
 "observed_at": "2026-09-21T12:06:30Z", "ttl": "90s", "cadence_class": "continuous",
 "stall_id": "sage:B-01", "zone_id": "sage:B", "lot_id": "sage"}
```

Read it as: stall B-01 in row B of the Sage lot (Stetson's Lot 33) was seen free at 8:06:30 a.m. lot time
(12:06:30 UTC), by a live camera that is 97% sure, and that claim is good for 90 seconds.

- `state`: free · occupied · reserved · out_of_service · unknown. Unknown is never free.
- `observed_at`: when the sensor saw it, always UTC. Age = now − observed_at.
- `ttl`: how long the claim stays true. Past it, the stall becomes unknown.
- Zone reports carry `free_count` / `total_count` instead of a `stall_id`; gate reports name only the lot.

The format and its rules live in `parkfind/event.py`.

---

## Freshness model

Live is a spectrum. ParkFind must be correct at every point on it.

| Class | Typical source | What we may claim | What we must not claim |
| --- | --- | --- | --- |
| Continuous | CCTV + YOLO, in-stall sensors, streaming operator API | This stall, now | Certainty at night / occlusion without evidence |
| Near-live | 30s–2 min camera poll, fast count API | This stall or row, almost now | That nothing changed since the last poll |
| Periodic snapshot | 5–15 min lot occupancy, dashboard scrape | Zone/lot count as of T; likely emptier areas | Pin a specific stall as free |
| Slow snapshot | Hourly / a few times per day | Prior + schedule + uncertainty band | Anything that sounds live |
| Event-only | Gate ticks, one user report, hours of operation | Direction of change, not a map of stalls | A live stall inventory |

**Compromise ladder when a lot has no stall-level live video**

1. Find a real source (operator API, municipal open data, existing camera, count board, allowed scrape).
2. If only lot-level numbers exist, run zone inference + time-of-week prior.
3. If updates are every N minutes, show the last-seen clock and expand stall → row → zone as N grows.
4. If updates are hourly, treat occupancy as a forecast with a wide band and push “report what you see.”
5. Between snapshots, use driver reports and gate deltas as the live patch.
6. Never paint a stall green from an hour-old lot total.

Prediction v1 is a **bridge between snapshots**, not a replacement for a live feed.

---

## How this compares to nearby open-source work

ParkFind is a guidance product. These repos are the closest public artifacts — use them as adapters or as anti-patterns, not as the product.

| Repo | What it is | What ParkFind takes | What ParkFind refuses |
| --- | --- | --- | --- |
| [thebkht/smart-parking-system](https://github.com/thebkht/smart-parking-system) | Edge YOLO-cls → JSON → FastAPI → web/mobile map. Best README + product shape in this category. | Occupancy events over video; edge-first; shared lot layout across map and inference | PKLot-style accuracy as the north star; “find my car” before “get me a stall” |
| [lotvulture/lotvulture](https://github.com/lotvulture/lotvulture) | Existing RTSP/IP cameras → on-device occupancy maps, hysteresis, alerts | Reuse existing cameras; temporal smoothing so stalls do not flicker | Operator analytics as v1; paid-edition split |
| [DeepParking/DeepParking](https://github.com/DeepParking/DeepParking) | YOLO v3 + Redis + route driver to closest vacant spot | Closest-reachable-free as a scoring input | Kubernetes week-1; $150-garage cost theater |
| [ultralytics parking management](https://docs.ultralytics.com/guides/parking-management/) | Stall polygons + vehicle overlap on a stream | Vision v1 recipe: polygons + detection + overlap + smoothing | Treating the overlay as the product |
| CNRPark / PKLot notebooks | Research occupancy classifiers | Fine-tune later on the **pilot lot’s own images** | Leaderboard numbers as pilot accuracy |

Domain shift is the real vision problem. Do not treat PKLot scores as product accuracy.

---

## Stack (pilot default, not religion)

| Layer | Default | Why | Switch when |
| --- | --- | --- | --- |
| Simulator | 80–200 stall lot emitting the same events as production, including delayed and bursty updates | Learn the product under ugly data before cameras | A real adapter is writing the same event |
| API | Thin HTTP + occupancy + guidance + holds | Founder can run it | Need streaming fanout at multi-lot |
| Store | Postgres / PostGIS for layout + history | Stalls are geometry | — |
| Snapshot / holds | Redis | Contention and short holds | — |
| Map | Web occupancy map first | Debug freshness without a phone | Driver app exists |
| Driver app | Flutter or React Native | One codebase, later | Web-only pilot is enough |
| Vision worker | Python, same event schema | Isolated from API | First real camera is signed |

Observability: store the raw feed log (`timestamp`, `source`, payload age). A two-driver race test and a stale-data test are both mandatory.

---

## Repository layout (target)

Nothing below is required to exist on day one. Simulator MVP comes before cameras.

```
sim/           Fake lot that emits canonical occupancy events
               at continuous, 5-min, 15-min, and hourly cadences
adapters/      One folder per source; each writes the same event
api/           Guidance, holds, reports, lot layout
store/         Schema for facility / lot / level / zone / stall
web/           Occupancy map + last-seen clock
app/           Thin driver client (after the map works)
vision/        Stall polygons + detection + overlap + smoothing
docs/          Decisions, freshness rules, pilot checklist
```

---

## Current phase

```
Discovery → Spec → Simulator MVP → One real sensor adapter
         → Thin driver app → One-lot pilot → Multi-lot
```

**Now:** Simulator MVP. The simulator writes the event feed; the reader that ages it is landing next.

---

## What this is not (v1)

- Payments, reservations marketplaces, permit wallets
- City-wide curb / meter inventory
- Drones, research-only allocation papers
- A promise to cover every lot on earth without an adapter plan
- A green stall painted from an hour-old lot total

If it does not get a driver to stop circling — or teach us how — it is not the work.

---

## Glossary

| Word | Meaning |
| --- | --- |
| Facility | The property (mall, campus, garage complex) |
| Lot | One parkable surface or structure |
| Level | A floor of a structure |
| Zone | A navigable cluster of stalls (row, bay, deck wing) |
| Stall | One painted or sensed space |
| Occupancy event | The canonical write: who, what state, how sure, when, how long that is good for |
| Hold | A short exclusive claim on a recommendation, only when freshness supports it |
| Report | A driver- or attendant-sourced observation used to patch between snapshots |
| Freshness | Age + cadence class of the last observation, shown to the driver |

---

## Data credits

Test photos come from the PKLot dataset (CC BY 4.0): P. R. L. de Almeida, L. S. Oliveira,
A. S. Britto Jr., E. J. Silva Jr. and A. L. Koerich, "PKLot – A robust dataset for parking lot
classification", Expert Systems with Applications 42(11), 2015. The photos are not stored in
this repository; each person downloads them into `data/` (ignored by git).

---

## Privacy and access

Prefer edge inference and occupancy events over stored video. Do not invent legal authority to scrape, tap cameras, or reserve stalls we do not control. ADA / EV constraints are first-class.

---

## Status

Private founding spec. No public demo yet. The simulator runs; see Run it.

Inspired in README shape by [thebkht/smart-parking-system](https://github.com/thebkht/smart-parking-system). Product question is ParkFind’s, not theirs.

## License

TBD by the founders. Do not publish adapters that imply rights we do not have.

Founders 
Dayspring Idahosa
Benjamin Nukunu Davis
Daniel Kilgore
