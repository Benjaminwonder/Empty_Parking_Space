# box: S1-DI-2 STAND-IN · written in BD's lane for the demo · DI replaces it with his directory (S1-DI-1/2)

"""
GET /sites: the site directory, read from sites/*/site.json.
GET /sites/<site_id>/package: a live site's lot outlines, for the open map.

Serves each site's public card (SK-SITE, draft) and nothing else: never the layout, cameras or stall states.
"""

import json
import re
from pathlib import Path

STATUSES = {"coming_soon", "counts", "named"}
ACCESS = {"public", "private"}
CARD_KEYS = ("site_id", "name", "centre", "outline", "status", "access", "utc_zone")


def load_cards(sites_dir: Path) -> dict:
    """
    why: the driver's first screen lists every site we know; this is the only list it reads.
    boundary: reads sites/*/site.json; returns {"sites": [card...], "rejected": [site folder...]}; writes nothing.
    ugly: one broken site file must not empty the directory: it is skipped and named in "rejected", never guessed.
    """
    cards, rejected = [], []
    for path in sorted(sites_dir.glob("*/site.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))["card"]
            if (any(k not in card for k in CARD_KEYS) or card["status"] not in STATUSES
                    or card["access"] not in ACCESS or card["site_id"] != path.parent.name):
                raise ValueError("card does not match SK-SITE")
            cards.append({k: card[k] for k in CARD_KEYS})   # only the card's fields, even if the file grows
        except (OSError, ValueError, KeyError, TypeError):
            rejected.append(path.parent.name)
    return {"sites": cards, "rejected": rejected}


SITE_ID = re.compile(r"^[a-z0-9-]{1,40}$")
LOT_KEYS = ("lot_id", "name", "outline", "centre")


def load_package(sites_dir: Path, site_id: str):
    """
    why: the open map draws a live site's lots in real coordinates; this hands over their outlines only.
    boundary: reads sites/<site_id>/site.json; returns {"card", "lots": [{lot_id, name, outline, centre}]} or None.
    ugly: site_id comes from a URL, so it must match SITE_ID before it touches a path ("../" never reaches
          the disk); a coming_soon site has no lots to give and answers None, the same as an unknown one.
    """
    if not SITE_ID.match(site_id or ""):
        return None
    path = sites_dir / site_id / "site.json"
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    layout = package.get("layout") or {}
    if package.get("card", {}).get("status") == "coming_soon" or not layout.get("lots"):
        return None
    return {"card": {k: package["card"][k] for k in CARD_KEYS},
            "lots": [{k: lot[k] for k in LOT_KEYS} for lot in layout["lots"]]}
