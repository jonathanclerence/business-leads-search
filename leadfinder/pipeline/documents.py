"""Client documents as PDFs: the proposal, the service agreement, the
onboarding form, and the website pack that puts all three in one short file
(five pages: cover, their website, packages and hosting, agreement, form).

Every page is a fixed A4 sheet (pipeline/docs/pages/*.html.j2), printed by
the same Chromium that Playwright drives for scraping. The boxes clients fill
in (their details, package and hosting ticks, signatures, the onboarding
questions) become real PDF form fields, so the file can be filled in on
screen in Preview, Acrobat or Chrome and emailed back.

With a lead, the documents are made for that business: their rating and
reviews, screenshots of the website we built them, a QR code to it, and the
forms pre-filled with what we know. Without one you get the generic pack,
kept in pipeline/assets/ and linked from every preview's "Make it mine" sheet.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, offer
from .content import BOOKING, KINDS, booking_mode
from .leads import slugify
from .render import ASSET_SRC, INFO_PACK, initials, render

Log = Callable[[str], None]

DOCS = Path(__file__).resolve().parent / "docs"
GENERIC_PACK = ASSET_SRC / INFO_PACK
EXPORT_DIR = config.ROOT / "exports" / "docs"

DOCUMENTS = {
    "pack": dict(title="Website pack", pages=["cover", "website", "packages", "agreement", "onboarding"]),
    "proposal": dict(title="Website proposal", pages=["cover", "website", "packages"]),
    "agreement": dict(title="Service agreement", pages=["agreement"]),
    "onboarding": dict(title="Onboarding form", pages=["onboarding"]),
}
SECTIONS = {"agreement": "Service agreement", "onboarding": "Onboarding form"}

# What customers can't do without a website, by the booking widget theirs has.
PAYOFF = {
    "appointment": "book in or check prices",
    "quote": "see your work or ask for a quote",
    "table": "check the menu or book a table",
    "order": "see what you make or order ahead",
    "consult": "find out what you do",
}

PT = 0.75               # one CSS pixel in PDF points
MM = 72 / 25.4          # one millimetre in PDF points
FIELD_TEXT = (0.043, 0.075, 0.141)   # --ink, for typed answers
CHECK_COLOUR = (0.031, 0.184, 0.286)  # --navy

_env = Environment(loader=FileSystemLoader(DOCS), autoescape=select_autoescape(["html", "j2"]),
                   trim_blocks=True, lstrip_blocks=True)
_env.filters["money"] = offer.money


class DocumentError(RuntimeError):
    pass


# --------------------------------------------------------------- context

def _fonts() -> List[Dict[str, str]]:
    def uri(name: str) -> str:
        return "data:font/woff2;base64," + base64.b64encode((DOCS / "fonts" / name).read_bytes()).decode()
    fonts = [dict(family="Geist", weight=str(w), style="normal", uri=uri(f"geist-{w}.woff2"))
             for w in (400, 500, 600, 700)]
    fonts += [dict(family="Instrument Serif", weight="400", style=s, uri=uri(n))
              for s, n in (("normal", "instrument-serif.woff2"), ("italic", "instrument-serif-italic.woff2"))]
    return fonts


def _a(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def _clean(text: str) -> str:
    """Google's hours use narrow no-break spaces; PDF form fonts don't have them."""
    return re.sub(r"[   ]", " ", text or "").strip()


def _hours(lead: Dict[str, Any]) -> str:
    try:
        rows = json.loads(lead.get("hours_json") or "null") or []
    except ValueError:
        return ""
    return "\n".join(_clean(f"{day}: {times}") for day, times in rows)


def short_name(name: str, limit: int = 34) -> str:
    """Google names are often keyword-stuffed ("Oxley Landscaping | Gardening |
    Fencing | … Morwell"). Keep the part before the first separator, or the
    first few words, for headings and forms."""
    name = " ".join(name.split())
    if len(name) <= limit:
        return name
    first = re.split(r"\s+[|\-–—:]\s+|,\s+|\s+\(", name)[0].strip()
    if 3 <= len(first) <= limit:
        return first
    words, out = first.split(), ""
    for w in words:
        if out and len(out) + 1 + len(w) > limit:
            break
        out = f"{out} {w}".strip()
    return out or name[:limit]


def _title_size(name: str) -> str:
    n = len(name)
    return "t-xl" if n <= 16 else "t-l" if n <= 26 else "t-m" if n <= 48 else "t-s"


def _qr(url: str) -> str:
    try:
        import segno
    except ImportError:  # the QR is a nice-to-have; the link is printed anyway
        return ""
    return segno.make(url, error="m").svg_inline(scale=4, border=0, dark="#082f49")


def context(kind: str, lead: Optional[Dict[str, Any]] = None, today: Optional[date] = None,
            shots: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if kind not in DOCUMENTS:
        raise DocumentError(f"Unknown document {kind!r} (use {', '.join(DOCUMENTS)})")
    today = today or date.today()
    # The page about their own website needs a business to show.
    pages = [p for p in DOCUMENTS[kind]["pages"] if lead or p != "website"]
    ctx: Dict[str, Any] = {
        "doc_title": DOCUMENTS[kind]["title"],
        "pages": pages,
        "packages": offer.PACKAGES,
        "enterprise": offer.ENTERPRISE,
        "hosting": offer.HOSTING,
        "rate": offer.HOURLY_RATE,
        "payment_due_days": offer.PAYMENT_DUE_DAYS,
        "terms_url": offer.TERMS_URL,
        "terms_short": offer.TERMS_URL.split("//", 1)[-1].replace("www.", ""),
        "contact": dict(email="info@dunous.com", site_short=config.SITE_URL.split("//", 1)[-1],
                        whatsapp_display=config.WHATSAPP_DISPLAY),
        "signatory": os.getenv("DOCS_SIGNATORY", "").strip(),
        "shots": shots or {},
        "biz": None, "suburb": "", "state": "", "rated": False, "prefill": {}, "qr": "",
    }
    if not lead:
        ctx["meta_title"] = f"DuNous — {ctx['doc_title']}"
        return ctx

    k = KINDS.get(lead.get("kind") or "local", KINDS["local"])
    mode = booking_mode(lead.get("kind") or "local", k["cta"])
    rating, reviews = lead.get("rating"), lead.get("reviews") or 0
    category = (lead.get("category") or k["label"]).lower()
    preview = config.preview_url(lead["slug"])
    hours = _hours(lead)
    biz = short_name(lead["name"])
    ctx.update({
        "lead": lead,
        "biz": biz,
        "meta_title": f"DuNous — {ctx['doc_title']} for {biz}",
        "title_size": _title_size(biz),
        "suburb": lead.get("suburb") or "",
        "state": lead.get("state") or "",
        "category_a": _a(category),
        "rated": bool(rating and rating >= 4.0 and reviews >= 3),
        "rating": f"{rating:g}" if rating else "",
        "reviews_fmt": f"{reviews:,}",
        "booking": BOOKING[mode],
        "payoff": PAYOFF[mode],
        "preview_url": preview,
        "preview_short": preview.split("//", 1)[-1].replace("www.", ""),
        "qr": _qr(preview),
        "today_str": f"{today.day} {today:%B %Y}",
        "valid_until_str": (lambda d: f"{d.day} {d:%B %Y}")(today + timedelta(days=offer.PROPOSAL_VALID_DAYS)),
        "ref": f"DN-{today:%y%m%d}-{initials(biz)}",
        "prefill": {
            "business": biz,
            "contact": lead.get("contact_name") or "",
            "phone": lead.get("phone_display") or "",
            "email": lead.get("email") or "",
            "address": _clean(lead.get("address") or ""),
            "domain": lead.get("domain") or "",
            "hours": hours,
            "services": "\n".join(title for title, _ in k["services"]),
            "colours": f"{lead['accent']} (the colour you picked in the preview)" if lead.get("accent") else "",
        },
    })
    return ctx


def html(kind: str, lead: Optional[Dict[str, Any]] = None, today: Optional[date] = None,
         shots: Optional[Dict[str, str]] = None) -> str:
    """The whole document as one HTML page (one <section class="page"> per sheet)."""
    ctx = context(kind, lead, today, shots)
    ctx["ui"] = _env.get_template("_ui.html.j2").make_module()
    pages = ctx["pages"]
    sheets = []
    for n, name in enumerate(pages, 1):
        section = SECTIONS.get(name, "Website proposal")
        sheets.append(_env.get_template(f"pages/{name}.html.j2").render(
            ctx, page_name=name, n=n, total=len(pages), section=section))
    return _env.get_template("base.html.j2").render(
        meta_title=ctx["meta_title"], fonts=_fonts(), css=(DOCS / "docs.css").read_text(encoding="utf-8"),
        pages="\n".join(sheets))


# ----------------------------------------------------------- the browser

def _launch(pw):
    path = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or None
    return pw.chromium.launch(headless=True, **({"executable_path": path} if path else {}))


def _screenshots(browser, lead: Dict[str, Any], log: Log) -> Dict[str, str]:
    """Desktop and phone screenshots of the finished site, as data URIs.

    The page and its assets are served from disk under one made-up origin, so
    the shared icon sprite loads (browsers refuse <use> across file:// URLs)."""
    site_assets = config.MARKETING_SITE_DIR / config.ASSETS_DIR
    if not (site_assets / "fonts").is_dir():
        log(f"No screenshots: {site_assets} not found (set MARKETING_SITE_DIR in .env).")
        return {}
    page_html = render(lead, final=True)
    roots = [ASSET_SRC.resolve(), site_assets.resolve()]

    def serve(route):
        path = urllib.parse.urlparse(route.request.url).path
        if path == "/":
            return route.fulfill(body=page_html, content_type="text/html; charset=utf-8")
        name = path[len("/previewsite-assets/"):] if path.startswith("/previewsite-assets/") else ""
        for root in roots:
            f = (root / name).resolve()
            if name and root in f.parents and f.is_file():
                return route.fulfill(path=str(f))
        return route.abort()

    shots = {}
    for key, viewport, scale, mobile in (("desktop", {"width": 1280, "height": 800}, 1.5, False),
                                         ("phone", {"width": 390, "height": 844}, 2, True)):
        ctx = browser.new_context(viewport=viewport, device_scale_factor=scale, is_mobile=mobile,
                                  has_touch=mobile, reduced_motion="reduce")
        try:
            page = ctx.new_page()
            page.route("**/*", serve)
            page.goto("https://preview.dunous.test/", wait_until="load", timeout=20000)
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            # Stop above the scrolling strip under the hero, which a still frame cuts mid-word.
            strip = page.evaluate("document.querySelector('.marquee')?.getBoundingClientRect().top || 0")
            height = int(min(viewport["height"], strip - 1)) if strip > viewport["height"] * 0.6 else viewport["height"]
            shot = page.screenshot(type="jpeg", quality=78, clip={"x": 0, "y": 0, "width": viewport["width"], "height": height})
            shots[key] = "data:image/jpeg;base64," + base64.b64encode(shot).decode()
        except Exception as exc:  # noqa: BLE001 — documents still work without pictures
            log(f"Screenshot ({key}) failed: {exc}")
        finally:
            ctx.close()
    return shots


_MEASURE = """() => {
  const pages = [...document.querySelectorAll('.page')];
  const overflow = pages.map((p, i) => {
    const b = p.querySelector('.page-body');
    return b && b.scrollHeight > b.clientHeight + 1 ? i + 1 : 0;
  }).filter(Boolean);
  const fields = [...document.querySelectorAll('[data-field]')].map((el) => {
    const page = el.closest('.page'), r = el.getBoundingClientRect(), pr = page.getBoundingClientRect();
    return {name: el.dataset.field, kind: el.dataset.kind, label: el.dataset.label, value: el.dataset.value || '',
            page: pages.indexOf(page), x: r.left - pr.left, y: r.top - pr.top, w: r.width, h: r.height};
  });
  return {overflow, fields};
}"""


def _print(browser, document_html: str) -> Dict[str, Any]:
    ctx = browser.new_context(viewport={"width": 794, "height": 1123})
    try:
        page = ctx.new_page()
        page.emulate_media(media="print")
        page.set_content(document_html, wait_until="load")
        page.evaluate("document.fonts.ready")
        measured = page.evaluate(_MEASURE)
        pdf = page.pdf(prefer_css_page_size=True, print_background=True, tagged=True, outline=True)
    finally:
        ctx.close()
    return {"pdf": pdf, **measured}


# ------------------------------------------------------------ form fields

def _add_fields(pdf: bytes, fields: List[Dict[str, Any]], info: Dict[str, str]) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, FloatObject,
                               NameObject, NumberObject, TextStringObject)

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.add_metadata(info)
    if not fields:
        return _bytes(writer)

    def font(base: str) -> DictionaryObject:
        d = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                              NameObject("/BaseFont"): NameObject(base)})
        if base == "/Helvetica":
            d[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
        return d

    acro = DictionaryObject({
        NameObject("/Fields"): ArrayObject(),
        NameObject("/DR"): DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/Helv"): writer._add_object(font("/Helvetica")),
            NameObject("/ZaDb"): writer._add_object(font("/ZapfDingbats")),
        })}),
        NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 g"),
    })
    writer.root_object[NameObject("/AcroForm")] = acro

    def stream(data: bytes, w: float, h: float):
        s = DecodedStreamObject()
        s.set_data(data)
        s.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                  NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(w), FloatObject(h)])})
        return writer._add_object(s)

    ink = " ".join(f"{c:.3f}" for c in FIELD_TEXT)
    values = {}
    for f in fields:
        page = writer.pages[f["page"]]
        top = float(page.mediabox.top)
        # Text sits a little in from the drawn box's edges; tick boxes fill theirs.
        dx = 0 if f["kind"] == "check" else 2 * MM
        dy = 0.8 * MM if f["kind"] == "multi" else 0
        x0, x1 = f["x"] * PT + dx, (f["x"] + f["w"]) * PT - dx
        y1, y0 = top - f["y"] * PT - dy, top - (f["y"] + f["h"]) * PT + dy
        widget = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/T"): TextStringObject(f["name"]), NameObject("/TU"): TextStringObject(f["label"]),
            NameObject("/F"): NumberObject(4),
            NameObject("/Rect"): ArrayObject([FloatObject(round(v, 2)) for v in (x0, y0, x1, y1)]),
        })
        if f["kind"] == "check":
            w, h = x1 - x0, y1 - y0
            tick = (f"q {' '.join(f'{c:.3f}' for c in CHECK_COLOUR)} RG {w * 0.13:.2f} w 1 J 1 j "
                    f"{w * .24:.2f} {h * .52:.2f} m {w * .43:.2f} {h * .31:.2f} l {w * .78:.2f} {h * .72:.2f} l S Q")
            widget.update({
                NameObject("/FT"): NameObject("/Btn"), NameObject("/V"): NameObject("/Off"),
                NameObject("/AS"): NameObject("/Off"),
                NameObject("/MK"): DictionaryObject({NameObject("/CA"): TextStringObject("4")}),
                NameObject("/DA"): TextStringObject("/ZaDb 0 Tf 0.031 0.184 0.286 rg"),
                NameObject("/AP"): DictionaryObject({NameObject("/N"): DictionaryObject({
                    NameObject("/Yes"): stream(tick.encode(), w, h), NameObject("/Off"): stream(b"", w, h)})}),
            })
        else:
            multi = f["kind"] == "multi"
            widget.update({
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/DA"): TextStringObject(f"/Helv {9 if multi else 10} Tf {ink} rg"),
                NameObject("/Ff"): NumberObject(4096 if multi else 0),
                NameObject("/MK"): DictionaryObject(),
            })
            if f["value"]:
                values[f["name"]] = f["value"]
        acro["/Fields"].append(writer.add_annotation(page, widget).indirect_reference)
    if values:
        writer.update_page_form_field_values(None, values, auto_regenerate=False)
    acro[NameObject("/NeedAppearances")] = BooleanObject(True)
    return _bytes(writer)


def _bytes(writer) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ build

def build(kind: str, lead: Optional[Dict[str, Any]] = None, today: Optional[date] = None,
          log: Log = print, fingerprint: str = "") -> bytes:
    """One document as PDF bytes. kind: pack | proposal | agreement | onboarding."""
    from playwright.sync_api import sync_playwright

    ctx = context(kind, lead, today)
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            shots = _screenshots(browser, lead, log) if lead and "website" in ctx["pages"] else {}
            out = _print(browser, html(kind, lead, today, shots))
        finally:
            browser.close()
    if out["overflow"]:
        log(f"Warning: page(s) {out['overflow']} of the {kind} overflow — shorten the text on them.")
    info = {"/Title": ctx["meta_title"], "/Author": "DuNous", "/Creator": "DuNous lead pipeline",
            "/Subject": ctx["doc_title"]}
    if fingerprint:
        info["/DunousSource"] = fingerprint
    return _add_fields(out["pdf"], out["fields"], info)


def filename(kind: str, lead: Optional[Dict[str, Any]] = None) -> str:
    title = DOCUMENTS[kind]["title"].replace(" ", "-")
    return f"DuNous-{title}" + (f"-{slugify(short_name(lead['name']), 40)}" if lead else "") + ".pdf"


def save(kind: str, lead: Dict[str, Any], log: Log = print) -> Path:
    out = EXPORT_DIR / lead["slug"] / filename(kind, lead)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build(kind, lead, log=log))
    return out


def generic_fingerprint() -> str:
    """Changes whenever the generic pack's content would (prices, wording, design)."""
    return hashlib.sha1(html("pack").encode("utf-8")).hexdigest()[:16]


def ensure_generic_pack(log: Log = print, force: bool = False) -> bool:
    """Rebuild pipeline/assets/dunous-website-pack.pdf if it's missing or out of
    date. Returns True if it was rewritten."""
    want = generic_fingerprint()
    if GENERIC_PACK.exists() and not force:
        from pypdf import PdfReader
        try:
            have = (PdfReader(GENERIC_PACK).metadata or {}).get("/DunousSource")
        except Exception:  # noqa: BLE001 — unreadable file: just rebuild it
            have = None
        if have == want:
            return False
    log(f"Building the generic website pack → {GENERIC_PACK.name}")
    GENERIC_PACK.write_bytes(build("pack", log=log, fingerprint=want))
    return True
