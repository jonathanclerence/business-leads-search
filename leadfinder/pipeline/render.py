"""Lead → HTML. One Jinja template renders both the preview on dunous.com
(with the "Make it mine" bar and form) and the finished site we hand over
after payment (`final=True`: no preview bar, no DuNous form)."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .content import CTA_BAND, CTA_LABELS, KINDS, THEME_ABOUT, THEME_STATEMENT, THEME_STYLE
from .leads import slugify

HERE = Path(__file__).resolve().parent
ASSET_SRC = HERE / "assets"

_env = Environment(loader=FileSystemLoader(HERE / "templates"),
                   autoescape=select_autoescape(["html", "j2"]),
                   trim_blocks=True, lstrip_blocks=True)

CTA_SHORT = {"book": "Book now", "quote": "Free quote", "enquire": "Enquire", "visit": "Directions"}

# Offered in the preview's colour picker (the theme's own colour comes first).
SWATCHES = ["#9a5b43", "#b0546f", "#7a2b3a", "#d23a2a", "#e09a12", "#4c7a3a",
            "#138a9e", "#2563a8", "#4b46d6", "#1f1f1f"]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def ink_for(hex_colour: str) -> str:
    """Black or white text, whichever reads better on the colour."""
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "#141414" if lum > 0.36 else "#ffffff"


def initials(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name) if w.lower() not in {"the", "and", "of", "pty", "ltd"}]
    return "".join(w[0] for w in words[:2]).upper() or name[:1].upper()


def name_size(name: str) -> str:
    n = len(name)
    return "xl" if n <= 14 else "l" if n <= 24 else "m" if n <= 36 else "s"


def _json(value: Any) -> Any:
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value or None


def video_available(theme: str) -> bool:
    return (config.MARKETING_SITE_DIR / config.ASSETS_DIR / "video" / f"{theme}.mp4").exists()


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
    t_accent, t_type, t_paper = THEME_STYLE.get(theme, THEME_STYLE["local"])
    accent = lead.get("accent") if _HEX.match(lead.get("accent") or "") else t_accent
    hours = _json(lead.get("hours_json"))
    quotes = _json(lead.get("reviews_json")) or []
    if rated:
        lede = f"Trusted by locals — rated {rating:g} stars from {reviews:,} Google reviews."
    else:
        lede = f"Your local {lead['category'].lower()} in {suburb}. Friendly, reliable and easy to reach."

    return {
        "accent": accent,
        "accent_ink": ink_for(accent),
        "type_style": lead.get("type_style") if lead.get("type_style") in ("serif", "grotesk") else t_type,
        "paper": lead.get("paper") if lead.get("paper") in ("light", "dark") else t_paper,
        "swatches": list(dict.fromkeys([t_accent] + SWATCHES)),
        "initials": initials(lead["name"]),
        "name_words": lead["name"].split(),
        "name_size": name_size(lead["name"]),
        "video": video_available(theme),
        "marquee": [t for t, _ in kind["services"]] + [f"{lead['category']} in {suburb}"]
                   + ([f"{rating:g}★ on Google"] if rated else []),
        "statement": THEME_STATEMENT.get(theme, THEME_STATEMENT["local"]),
        "cta_band": CTA_BAND[cta],
        "hours": hours,
        "hours_json": json.dumps(hours).replace("</", "<\\/") if hours else "",
        "reviews": quotes[:3],
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
