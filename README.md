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

Needs Java 17 or newer for the page. Use three terminals, all in the repo folder:

```
python sim.py --minutes 900
python -m parkfind.server --run out/latest --speed 10
java --source 17 WebPage
```

Then open http://localhost:8085. The simulator writes a full day from 06:30 lot time; the server
replays it ten times faster than real time (so a claim's 8-minute window takes 48 seconds); the
page asks for fresh status every five seconds.
To freeze the morning at one moment instead, start the server with
`--now 2026-09-21T08:15:00-04:00 --speed 0`.

Click a P pin to open that lot: it leads with the best spot for your car and how old that
sighting is; stalls show free, taken, held or unknown, and lots that only count cars (an hourly
count, a gate) show their counts row by row with their age. Press **Claim this spot** and nobody
else is sent there; if no car reaches it within 8 minutes (13 or 23 for slower cameras), it is
released and you are told. Search takes buildings, lots or spots: `CUB`, `Lot 41`, `Sage B-04`.

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
