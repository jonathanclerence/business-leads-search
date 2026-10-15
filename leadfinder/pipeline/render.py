"""Lead → HTML. One Jinja template renders both the preview on dunous.com
(with the "Make it mine" bar and form) and the finished site we hand over
after payment (`final=True`: no preview bar, no DuNous form)."""

from __future__ import annotations

import hashlib
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .content import CTA_LABELS, KINDS, THEME_ABOUT
from .leads import slugify

HERE = Path(__file__).resolve().parent
ASSET_SRC = HERE / "assets"

_env = Environment(loader=FileSystemLoader(HERE / "templates"),
                   autoescape=select_autoescape(["html", "j2"]),
                   trim_blocks=True, lstrip_blocks=True)

CTA_SHORT = {"book": "Book now", "quote": "Free quote", "enquire": "Enquire", "visit": "Directions"}


def asset_version() -> str:
    """Changes whenever the shared css/js/icons change, so browsers never mix old and new."""
    h = hashlib.sha1()
    for f in sorted(ASSET_SRC.iterdir()):
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:10]


def maps_link(lead: Dict[str, Any]) -> str:
    query = f"{lead['name']} {lead['address'] or lead['suburb'] + ' ' + (lead['state'] or '')}".strip()
    params = {"api": "1", "query": query}
    if lead.get("place_id"):
        params["query_place_id"] = lead["place_id"]
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode(params)


def context(lead: Dict[str, Any], final: bool = False, assets: str = "/previewsite-assets") -> Dict[str, Any]:
    kind = KINDS.get(lead.get("kind") or "local", KINDS["local"])
    theme = lead.get("theme") or kind["theme"]
    suburb = lead.get("suburb") or "your area"
    rating, reviews = lead.get("rating"), lead.get("reviews") or 0
    rated = bool(rating and rating >= 4.0 and reviews >= 3)
    cta = kind["cta"]
    street = bool(lead.get("address")) and lead["address"].strip().lower() != suburb.lower()
    service_area = not street or "mobile" in lead["name"].lower() or lead.get("kind") == "mobile-mechanic"

    version = asset_version()
    if rated:
        lede = f"Trusted by locals — rated {rating:g} stars from {reviews:,} Google reviews."
    else:
        lede = f"Your local {lead['category'].lower()} in {suburb}. Friendly, reliable and easy to reach."

    return {
        "lead": lead,
        "final": final,
        "theme": theme,
        "assets": assets,
        "version": version,
        "icons": f"{assets}/preview-icons.svg?v={version}",
        "headline": kind["headline"].format(suburb=suburb),
        "lede": lede,
        "about": THEME_ABOUT.get(theme, THEME_ABOUT["local"]).format(
            name=lead["name"], suburb=suburb, what=lead["category"].lower()),
        "services": kind["services"],
        "services_title": f"Come and see us in {suburb}" if theme in ("food", "winery")
                          else f"How we can help in {suburb}",
        "cta": cta,
        "cta_label": CTA_LABELS[cta],
        "cta_short": CTA_SHORT[cta],
        "rated": rated,
        "rating": f"{rating:g}" if rating else "",
        "reviews_fmt": f"{reviews:,}",
        "maps_link": maps_link(lead),
        "street": street,
        "service_area": service_area,
        "domain_hint": f"{slugify(lead['name'], 30).replace('-', '')}.com.au",
        "year": date.today().year,
        "brand": config.BRAND,
        "whatsapp_href": config.WHATSAPP_HREF,
        "whatsapp_display": config.WHATSAPP_DISPLAY,
    }


def render(lead: Dict[str, Any], final: bool = False, assets: str = "/previewsite-assets") -> str:
    return _env.get_template("site.html.j2").render(**context(lead, final=final, assets=assets))
