"""
box: S1-BD-1 · lane: BD · tools/geo_export.py
why: Stetson's lots live in WebPage as picture units; a site package needs latitude/longitude.
     This file is the one place our drawing is converted into the world's coordinates.
boundary: the GEO numbers are copied from WebPage (DK's file); read them there, never edit them.
          Reads campus.json, writes sites/stetson/site.json; nothing else.
run: python tools/geo_export.py
"""
import json
import math
from pathlib import Path

# Copied exactly from WebPage's GEO (five road crossings, fitted 2026-10-13, about 1 m error).
# If GEO is ever refitted, these change with it, or pins and outlines drift apart.
LAT0, LON0 = 29.0355, -81.2995
A = [[1.80372, 0.00531], [0.05338, -1.81864], [-730.5595, 774.4908]]

# The fit was made with these metres-per-degree numbers, so the way back must use the same ones,
# even though 110574 is the equator's value: "correcting" it would shift every point by metres.
M_PER_DEG_LAT = 110574
M_PER_DEG_LON = 111320 * math.cos(math.radians(LAT0))


def to_latlng(u: float, v: float) -> tuple[float, float]:
    """why: turn one point on our drawing into the latitude/longitude any map understands.
    boundary: pure arithmetic; no files, no rounding (whoever writes a file rounds).
    ugly: v grows downward on the drawing, so north is -v; the flat-Earth step holds near Stetson only.
    """
    east_m = u * A[0][0] + v * A[1][0] + A[2][0]
    north_m = u * A[0][1] + v * A[1][1] + A[2][1]
    return LAT0 + north_m / M_PER_DEG_LAT, LON0 + east_m / M_PER_DEG_LON



def point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """why: "is this point inside that outline?" (pin in lot, gate in site, later: phone in site).
    boundary: pure; polygon is [[lat, lng], ...], closed implicitly (last point joins the first).
    ugly: a point exactly on an edge may land either side; outlines carry a margin so it never matters.
    """
    # Ray casting: walk east from the point and count edge crossings; odd = inside.
    inside = False
    for (a_lat, a_lng), (b_lat, b_lng) in zip(polygon, polygon[1:] + polygon[:1]):
        if (a_lat > lat) != (b_lat > lat):
            cross_lng = a_lng + (lat - a_lat) * (b_lng - a_lng) / (b_lat - a_lat)
            if lng < cross_lng:
                inside = not inside
    return inside


def box_outline(x: float, y: float, w: float, h: float) -> list:
    """Four corners of a picture-unit box, clockwise from north-west, as rounded [lat, lng]."""
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return [[round(c, 6) for c in to_latlng(u, v)] for u, v in corners]


# Copied from WebPage (read-only). These are PINS, nudged off roads and labels, not traced lot shapes.
# Until each lot is traced from a map (OpenStreetMap's server refused automated reads), the pin box is
# the outline, and site.json says so in outline_source so nobody mistakes it for a survey.
LOT_MARKERS = {
    "rinker": (190, 169, 29, 30), "hollis": (281, 214, 25, 68), "libn": (74, 468, 58, 18),
    "libs": (222, 553, 56, 38), "west1": (282, 553, 32, 40), "sage": (339, 484, 48, 16),
    "west2": (400, 553, 23, 18), "east": (588, 350, 22, 66), "stetson": (634, 433, 20, 92),
}
GATE_U, GATE_V = 169, 547        # WebPage's Main Gate: where Woodland's and Michigan's centrelines cross
DRAWING_W, DRAWING_H = 690, 736  # WebPage's drawing, picture units
CAMPUS_MARGIN = 40               # WebPage's onCampus margin (~70 m): the same edge the page already uses

HERE = Path(__file__).resolve().parent.parent


def build_stetson() -> dict:
    """why: Stetson's Site Package: its public card (SK-SITE, draft) plus campus.json with real geometry.
    boundary: reads campus.json; returns a dict; never edits campus.json (still read by everyone until S2).
    ugly: a lot in campus.json with no pin stops the build; a site with a missing lot would look complete.
    """
    layout = json.loads((HERE / "campus.json").read_text(encoding="utf-8"))
    for lot in layout["lots"]:
        if lot["lot_id"] not in LOT_MARKERS:
            raise SystemExit(f"{lot['lot_id']} has no pin in WebPage: no outline, no site package")
        outline = box_outline(*LOT_MARKERS[lot["lot_id"]])
        lot["outline"] = outline
        lot["outline_source"] = "pin box from WebPage (approximate, to be traced)"
        lot["centre"] = {"lat": round(sum(p[0] for p in outline) / 4, 6),
                         "lng": round(sum(p[1] for p in outline) / 4, 6)}
    m = CAMPUS_MARGIN
    site_outline = box_outline(-m, -m, DRAWING_W + 2 * m, DRAWING_H + 2 * m)
    card = {  # SK-SITE (draft, stage S0): the only part the directory ever serves
        "site_id": "stetson",
        "name": "Stetson University",
        "centre": {"lat": round(sum(p[0] for p in site_outline) / 4, 6),
                   "lng": round(sum(p[1] for p in site_outline) / 4, 6)},
        "outline": site_outline,
        "status": "named",
        "access": "public",          # permits wait for S5; until then Stetson opens as today
        "utc_zone": "America/New_York",
    }
    return {"card": card, "layout": layout}


if __name__ == "__main__":
    lat, lng = to_latlng(GATE_U, GATE_V)
    print(f"Main Gate: {lat:.5f}, {lng:.5f}")
    package = build_stetson()
    site = package["card"]["outline"]
    ok = point_in_polygon(lat, lng, site)
    print(f"Main Gate inside the site outline: {ok}")
    for lot in package["layout"]["lots"]:
        c = lot["centre"]
        inside_lot = point_in_polygon(c["lat"], c["lng"], lot["outline"])
        inside_site = point_in_polygon(c["lat"], c["lng"], site)
        ok = ok and inside_lot and inside_site
        print(f"  {lot['lot_id']:8} {lot['name']:28} centre {c['lat']:.6f}, {c['lng']:.6f}"
              f"  in lot: {inside_lot}  in site: {inside_site}")
    if not ok:
        raise SystemExit("a check failed: site.json not written")
    out = HERE / "sites" / "stetson" / "site.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(HERE)}")
