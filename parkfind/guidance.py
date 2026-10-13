# box: G1 · lane: BD · read BRIDGES.md before editing
"""
Guidance: one honest answer to "where should I park in this lot?"

Last-seen (DI) says what every stall looked like and how old that look is.
Guidance turns that into the one thing the driver acts on, and it is only as
specific as the data allows (D4 in handoff/CONTRACT.md):

  stall  a free stall seen by a live sensor (continuous, or a 5-minute camera)
         still inside its ttl. Only then do we name a stall.
  zone   fresher-than-ttl data that is too slow to bet a stall on: "row B, 5 free".
  count  only a lot count, possibly expired; we show it with its age.
  none   nothing we can stand behind.

Which lot to answer for is the caller's choice (nearest lot to the driver, or
the pin they clicked). Guidance never picks a lot on its own, so a driver with
no location and no click is not handed a stall nobody asked for.
"""

from __future__ import annotations

from datetime import datetime

VEHICLE_CLASSES = ("regular", "ada", "ev")
# Fast enough to name a stall. A 5-minute camera counts as near_live (decided 2026-10-12).
LIVE_CADENCES = ("continuous", "near_live")
# Which stall types each car may use, best first. A regular car never gets ADA or EV.
TIERS = {"regular": ("regular",), "ada": ("ada", "regular"), "ev": ("ev", "regular")}


def stall_types(lot: dict) -> dict[str, str]:
    """why: every stall in one lot mapped to regular / ada / ev, keyed by full id (sage:A-01).
    boundary: reads the campus.json entry for one lot only.
    ugly: special_stalls holds lot-local ids (A-01); forgetting the lot prefix would quietly make every stall regular.
    """
    lot_id = lot["lot_id"]
    special = {f"{lot_id}:{s}": "ada" for s in lot["special_stalls"].get("ada", [])}
    special.update({f"{lot_id}:{s}": "ev" for s in lot["special_stalls"].get("ev", [])})
    types = {}
    for row in lot["rows"]:
        for n in range(1, lot["stalls_per_row"] + 1):
            sid = f"{lot_id}:{row}-{n:02d}"
            types[sid] = special.get(sid, "regular")
    return types


def walk_order(stall_id: str) -> tuple[str, int]:
    """why: "closest" inside a lot: row A is nearest the entrance, then the lower stall number.
    boundary: reads the id only.
    ugly: a stand-in for real walking distance; replace it when lots get real coordinates, not before.
    """
    row, number = stall_id.split(":", 1)[1].split("-")
    return row, int(number)


def _based_on(claim: dict) -> dict:
    """why: every answer carries where it came from and how old it is, so the page can never show a bare promise.
    boundary: copies fields from one status claim; computes nothing.
    ugly: age_s is the age at status time; the page must not recompute it from its own clock.
    """
    return {
        "source": claim.get("source"),
        "observed_at": claim.get("observed_at"),
        "age_s": claim.get("age_s"),
        "cadence_class": claim.get("cadence_class"),
        "fresh": claim.get("state") != "unknown",
    }


def answer(status: dict, layout: dict, now: datetime, vehicle_class: str, driver_id: str,
           lot_id: str | None = None) -> dict | None:
    """why: the one place the D4 rules live: name a stall only when a live sensor saw it free, else step down to zone, count, none.
    boundary: reads SK-STATUS and SK-LAYOUT; writes nothing and holds nothing (claims and holds are BD-9, which will use now and driver_id).
    ugly: an unknown stall is never treated as free, and a regular car is never sent to ADA/EV even when those are the only free stalls.
    """
    if vehicle_class not in VEHICLE_CLASSES:
        raise ValueError(f"vehicle_class {vehicle_class!r} is not one of {VEHICLE_CLASSES}")
    if lot_id is None:
        return None
    lot = next((l for l in layout["lots"] if l["lot_id"] == lot_id), None)
    if lot is None:
        raise ValueError(f"lot_id {lot_id!r} is not in campus.json")

    tiers = TIERS[vehicle_class]
    types = stall_types(lot)
    stalls = status["stalls"]
    base = {"vehicle_class": vehicle_class, "lot_id": lot_id}

    # 1. stall: live, free, inside ttl (state is already "unknown" past ttl), best tier first.
    for tier in tiers:
        live_free = sorted(
            (sid for sid, t in types.items() if t == tier
             and stalls[sid]["state"] == "free" and stalls[sid]["cadence_class"] in LIVE_CADENCES),
            key=walk_order)
        if live_free:
            sid = live_free[0]
            return {**base, "grain": "stall", "stall_id": sid, "zone_id": sid.rsplit("-", 1)[0],
                    "based_on": _based_on(stalls[sid])}

    # 2. zone: data inside its ttl but too slow to name a stall. Two kinds feed this:
    #    stall claims from slow snapshots, and row counts (free_count) from zone sensors.
    usable = set(tiers)
    candidates = []
    for row in lot["rows"]:
        zid = f"{lot_id}:{row}"
        row_ids = [sid for sid in types if sid.startswith(zid + "-")]
        seen_free = [sid for sid in row_ids if types[sid] in usable and stalls[sid]["state"] == "free"]
        if seen_free:
            oldest = max((stalls[s] for s in seen_free), key=lambda c: c["age_s"])
            candidates.append((len(seen_free), row, len(row_ids), oldest))
            continue
        claim = status["zones"].get(zid)
        if claim and claim["state"] != "unknown" and "free_count" in claim:
            free = claim["free_count"]
            if vehicle_class == "regular":
                # A row count includes ADA/EV stalls; for a regular car it is a lower bound (D4).
                free = max(0, free - sum(1 for s in row_ids if types[s] != "regular"))
            if free > 0:
                candidates.append((free, row, claim["total_count"], claim))
    if candidates:
        free, row, total, claim = min(candidates, key=lambda c: c[1])  # nearest row with room
        return {**base, "grain": "zone", "zone_id": f"{lot_id}:{row}", "free_count": free,
                "total_count": total, "based_on": _based_on(claim)}

    # 3. count: the lot's last count, even expired, always with its age; never a stall.
    count = status["lots"].get(lot_id, {}).get("last_count")
    if count:
        claim = status["lot_claims"].get(lot_id, {})
        return {**base, "grain": "count", "free_count": count["free_count"],
                "total_count": count["total_count"],
                "based_on": {"source": claim.get("source"), "observed_at": count["observed_at"],
                             "age_s": count["age_s"], "cadence_class": claim.get("cadence_class"),
                             "fresh": count["state"] == "fresh"}}

    return {**base, "grain": "none"}
