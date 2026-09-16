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

## Features

- **Honest guidance, not a fake live map.** Recommendation shrinks from stall → row → zone as the observation ages.
- **Occupancy fabric.** Sim, CCTV+YOLO, stall sensors, gate counts, partner APIs, periodic lot scrapes, and driver reports all write one canonical event.
- **Freshness as a first-class field.** Every state has `confidence`, `source`, `observed_at`, `ttl`, and `cadence_class`. Stale data becomes `unknown`.
- **Inside-lot maps.** Aisle graphs so we do not recommend a stall the driver cannot legally drive to from their current approach.
- **Holds that expire with the data.** Hold windows shrink as the feed gets older. No hold on an hour-old lot total.
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

### Canonical event

```json
{
  "stall_id": "A-114",
  "zone_id": "deck-2-west",
  "state": "free",
  "confidence": 0.86,
  "source": "cctv.cam-04",
  "observed_at": "2026-09-16T14:02:11Z",
  "ttl": "12s",
  "cadence_class": "continuous"
}
```

`state` is one of: `free` | `occupied` | `reserved` | `out_of_service` | `unknown`.

`unknown ≠ free`. A 5-minute lot feed does not get a 4-second TTL.

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

**Now:** Spec. The README is the public shape of the idea. Code starts with a simulator that can lie to us on purpose (late snapshots, two drivers, a stall that flips after assign).

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

## Privacy and access

Prefer edge inference and occupancy events over stored video. Do not invent legal authority to scrape, tap cameras, or reserve stalls we do not control. ADA / EV constraints are first-class.

---

## Status

Private founding spec. No public demo yet. First runnable artifact will be the simulator, not a camera.

Inspired in README shape by [thebkht/smart-parking-system](https://github.com/thebkht/smart-parking-system). Product question is ParkFind’s, not theirs.

## License

TBD by the founders. Do not publish adapters that imply rights we do not have.
