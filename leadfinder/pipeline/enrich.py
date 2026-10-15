"""Enrichment: opening hours + a few short review snippets from Google Maps.

For each lead we open its Google Maps place page (one browser, one tab, paced)
and store, on the lead row only:

  hours_json    [["Monday", "9 AM–5 PM"], …, ["Sunday", "Closed"]]  or NULL
  reviews_json  [{"text": "...", "author": "Sam", "stars": 5}, …]      or NULL (max 3)
  enriched_at   when we looked

How the page is read (checked against live place pages, Oct 2026):

  hours    The Overview tab carries the weekly table in the DOM even while it
           is collapsed: ``table.eK4R0e`` → ``tr`` → day cell + hours cell whose
           ``li.G8aQO`` items are the displayed ranges. Rows start at *today*,
           so we re-order to Monday..Sunday. Fallbacks: an element whose
           aria-label lists all seven days, then the per-day "Copy open hours"
           buttons (``data-value="Thursday, 9 AM–7 PM"``).
  reviews  Click the "Reviews" tab; each review is ``div.jftiEf[data-review-id]``
           with the author in ``.d4r55``, stars in ``span[role=img][aria-label="5 stars"]``
           and the text in ``.MyEned .wiI7pd`` (owner replies live in ``.CDe7pd``
           and are ignored). Long reviews are cut with a "More" button
           (``button[aria-label="See more"]``) which we click before reading.
           If the first page is thin we scroll the list to load more.

Everything that decides *what* we keep (hours normalising, snippet trimming,
the "is this review safe to put on a website" filter) is pure Python, tested
offline in tests/test_enrich.py.

    python -m pipeline.enrich --grade Hot --limit 50          # next 50 un-enriched Hot leads
    python -m pipeline.enrich got-you-nails-and-beauty urban-trim
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import urllib.parse
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from leadfinder.config import settings
from leadfinder.scraper import BlockedError, GoogleMapsScraper, _human_pause

from . import db

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

MAX_REVIEWS = 3
MIN_STARS = 4            # never quote a 1–3 star review on a sales preview
MIN_CHARS = 40
MAX_CHARS = 220
SCROLL_ROUNDS = 2        # extra pages of reviews to load when the first page is thin

# ---------------------------------------------------------------------------
# In-page extraction (one round-trip each). They return raw text pieces; the
# parsing/cleaning happens in Python so it can be unit-tested.
# ---------------------------------------------------------------------------

JS_HOURS = r"""
() => {
  const DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
  const main = document.querySelector('div[role="main"]') || document;
  const parts = (el) => {
    const out = [];
    if (!el) return out;
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) { const t = (n.nodeValue || '').trim(); if (t) out.push(t); }
    return out;
  };
  const startsWithDay = (s) => DAYS.some((d) => (s || '').trim().startsWith(d));

  // 1) The weekly hours table (present in the DOM even when collapsed).
  const tables = [...main.querySelectorAll('table.eK4R0e'), ...main.querySelectorAll('table')];
  for (const t of tables) {
    const rows = [];
    for (const tr of t.querySelectorAll('tr')) {
      const cells = tr.querySelectorAll('td, th');
      if (cells.length < 2) continue;
      const day = parts(cells[0]);
      if (!startsWithDay(day.join(' '))) continue;
      const items = [...cells[1].querySelectorAll('li')].map((li) => parts(li).join(' ')).filter(Boolean);
      rows.push({ day, items: items.length ? items : parts(cells[1]) });
    }
    if (rows.length >= 7) return { rows };
  }

  // 2) An element whose aria-label spells out the whole week.
  for (const el of main.querySelectorAll('[aria-label]')) {
    const l = el.getAttribute('aria-label') || '';
    if (DAYS.every((d) => l.includes(d))) return { label: l };
  }

  // 3) The per-day "Copy open hours" buttons.
  const values = [...main.querySelectorAll('[data-value]')]
    .map((b) => b.getAttribute('data-value') || '')
    .filter((v) => DAYS.some((d) => v.startsWith(d + ',')));
  if (values.length >= 7) return { values };
  return null;
}
"""

JS_EXPAND_REVIEWS = r"""
() => {
  // Only the review-text expanders — never the "+3 more photos" buttons.
  let n = 0;
  document.querySelectorAll('[data-review-id] button[aria-expanded="false"]').forEach((b) => {
    const label = (b.getAttribute('aria-label') || '').trim();
    const text = (b.textContent || '').trim();
    if (/^see more$/i.test(label) || /^more$/i.test(text)) { b.click(); n++; }
  });
  return n;
}
"""

JS_SCROLL_REVIEWS = r"""
() => {
  const first = document.querySelector('div.jftiEf[data-review-id]') || document.querySelector('[data-review-id]');
  let el = first && first.parentElement;
  while (el && el !== document.body) {
    const cs = getComputedStyle(el);
    if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 10) {
      el.scrollTop = el.scrollHeight;
      return true;
    }
    el = el.parentElement;
  }
  return false;
}
"""

JS_REVIEWS = r"""
() => {
  const norm = (s) => (s || '').trim();
  const out = [];
  const seen = new Set();
  let nodes = [...document.querySelectorAll('div.jftiEf[data-review-id]')];
  if (!nodes.length) {
    // Fallback: the outermost element carrying each review id.
    nodes = [...document.querySelectorAll('[data-review-id]')].filter((el) => {
      const id = el.getAttribute('data-review-id');
      const up = el.parentElement && el.parentElement.closest('[data-review-id]');
      return !(up && up.getAttribute('data-review-id') === id);
    });
  }
  for (const r of nodes) {
    const id = r.getAttribute('data-review-id');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const authorEl = r.querySelector('.d4r55');
    let author = norm(authorEl && authorEl.textContent) || norm(r.getAttribute('aria-label'));
    if (!author) {
      const photo = r.querySelector('[aria-label^="Photo of "]');
      if (photo) author = norm(photo.getAttribute('aria-label')).replace(/^Photo of /, '');
    }
    const starEl = r.querySelector('[role="img"][aria-label*="star" i]');
    let stars = starEl ? starEl.getAttribute('aria-label') : '';
    if (!stars) { const s = r.querySelector('.fzvQIb'); stars = s ? s.textContent : ''; }  // "5/5" layout
    // The reviewer's own words; owner replies (.CDe7pd) also use .wiI7pd.
    let body = r.querySelector('.MyEned .wiI7pd');
    if (!body) body = [...r.querySelectorAll('.wiI7pd')].find((el) => !el.closest('.CDe7pd'));
    const holder = r.querySelector('.MyEned');
    const moreLeft = [...r.querySelectorAll('button[aria-expanded="false"]')]
      .some((b) => /^see more$/i.test((b.getAttribute('aria-label') || '').trim()));
    out.push({
      id, author, stars,
      text: body ? (body.innerText || body.textContent || '') : '',
      lang: holder ? (holder.getAttribute('lang') || '') : '',
      truncated: moreLeft,
    });
  }
  return out;
}
"""

JS_PAGE_STATE = r"""
() => {
  const body = (document.body && document.body.innerText) || '';
  const h1 = document.querySelector('div[role="main"] h1');
  return {
    url: location.href,
    h1: h1 ? h1.textContent.trim() : '',
    blocked: !!document.querySelector('form#captcha-form, iframe[src*="recaptcha"]')
             || (!h1 && /unusual traffic|not a robot|detected unusual/i.test(body.slice(0, 5000))),
    feed: !!document.querySelector('div[role="feed"]'),
    firstPlace: (document.querySelector('div[role="feed"] a[href*="/maps/place/"]') || {}).href || '',
  };
}
"""


# ---------------------------------------------------------------------------
# Pure helpers (tested offline)
# ---------------------------------------------------------------------------

_INVISIBLE = re.compile(r"[​-‏‪-‮⁠﻿]")
_SPACE = re.compile(r"\s+")  # \s covers U+00A0, U+202F, U+2009 … in Python 3
_PUA = re.compile(r"[-]")  # Google's icon-font glyphs leak into textContent


def norm_ws(text: Optional[str]) -> str:
    """Collapse every kind of whitespace (incl. the U+202F in "9 AM") to one
    plain space; drop invisible direction marks and icon glyphs."""
    text = _PUA.sub("", _INVISIBLE.sub("", text or ""))
    return _SPACE.sub(" ", text).strip()


_HOURS_NOTE = re.compile(r"hours might differ|hours may differ|holiday hours|special hours|"
                         r"confirmed by|updated by|reported by", re.I)
_SPECIAL_NOTE = re.compile(r"holiday hours|special hours", re.I)


def _hours_text(items: Sequence[str]) -> Tuple[str, bool]:
    """Displayed ranges for one day → ("9 AM–12 PM, 1–5 PM", is_special_hours)."""
    special = False
    keep: List[str] = []
    for raw in items:
        item = norm_ws(raw)
        if not item:
            continue
        if _HOURS_NOTE.search(item):
            special = special or bool(_SPECIAL_NOTE.search(item))
            continue
        if item not in keep:
            keep.append(item)
    return ", ".join(keep), special


def _aria_range(text: str) -> str:
    """aria-labels say "9 AM to 5 PM"; the page shows "9 AM–5 PM"."""
    return re.sub(r"\s+to\s+", "–", norm_ws(text))


def parse_hours(raw: Optional[Dict[str, Any]]) -> Optional[List[List[str]]]:
    """What JS_HOURS returned → [[day, text]] Monday..Sunday, or None.

    None when any day is missing, or when Google is showing a one-off holiday
    schedule this week (we only want the regular week)."""
    if not raw:
        return None
    week: Dict[str, str] = {}

    if raw.get("rows"):
        for row in raw["rows"]:
            day_txt = norm_ws(" ".join(row.get("day") or []))
            day = next((d for d in DAYS if day_txt.startswith(d)), None)
            if not day or day in week:
                continue
            items = row.get("items") or []
            text, special = _hours_text(items)
            # A holiday name next to the day ("Tuesday (Melbourne Cup)") without
            # the "Hours might differ" hint = that date's special hours.
            extra = norm_ws(day_txt[len(day):])
            if special or (extra and not re.search(r"(?:might|may) differ", " ".join(items), re.I)):
                return None
            if text:
                week[day] = text

    elif raw.get("label"):
        # "Monday, 9 AM to 5 PM; Tuesday, …; Hide open hours for the week"
        for chunk in norm_ws(raw["label"]).split(";"):
            chunk = chunk.strip().rstrip(".")
            day = next((d for d in DAYS if chunk.startswith(d)), None)
            if not day or day in week:
                continue
            rest = re.sub(r",?\s*Copy open hours$", "", chunk[len(day):].lstrip(" ,"), flags=re.I)
            text, special = _hours_text([_aria_range(r) for r in rest.split(",") if r.strip()])
            if special:
                return None
            if text:
                week[day] = text

    elif raw.get("values"):
        for value in raw["values"]:
            value = norm_ws(value)
            day = next((d for d in DAYS if value.startswith(d + ",")), None)
            if not day or day in week:
                continue
            text, special = _hours_text([r for r in value[len(day) + 1:].split(",")])
            if special:
                return None
            if text:
                week[day] = text

    if any(d not in week for d in DAYS):
        return None
    return [[d, week[d]] for d in DAYS]


def first_name(author: Optional[str]) -> str:
    """'Michelle Gaeb' → 'Michelle'; 'kayli AB' → 'Kayli'; 'Dr. Sam Lee' → 'Sam'."""
    words = [w.strip(".,;:!?()[]\"'") for w in norm_ws(author).split(" ")]
    words = [w for w in words if w]
    if len(words) > 1 and words[0].lower() in ("dr", "mr", "mrs", "ms", "miss", "mx", "prof"):
        words = words[1:]
    word = words[0] if words else ""
    if word.islower() or (word.isupper() and len(word) > 2):
        word = word[:1].upper() + word[1:].lower()
    return word


def parse_stars(label: Optional[str]) -> Optional[int]:
    """'5 stars' / 'Rated 4.0 out of 5' / '5/5' → int, else None."""
    label = norm_ws(label)
    m = (re.search(r"(\d(?:[.,]\d)?)\s*/\s*5", label)
         or re.search(r"(\d(?:[.,]\d)?)\s*(?:out of 5|stars?)", label, re.I)
         or re.search(r"^(\d(?:[.,]\d)?)$", label))
    if not m:
        return None
    value = round(float(m.group(1).replace(",", ".")))
    return value if 1 <= value <= 5 else None


def trim_snippet(text: str, max_chars: int = MAX_CHARS) -> str:
    """At most `max_chars` (counting the "…"), ending on a whole word — at a
    sentence end if that still keeps at least half the budget."""
    text = norm_ws(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", cut)]
    if ends and ends[-1] >= max_chars * 0.5:
        body = cut[: ends[-1]]
    else:
        space = cut.rfind(" ", 0, max_chars - 1)
        body = cut[:space] if space > 0 else cut[: max_chars - 1]
    body = body.rstrip(" ,;:-–—(&.!?")
    return body[: max_chars - 1].rstrip() + "…"


# --- "is this safe to quote on their website?" ------------------------------

_PRICE = re.compile(
    r"[$€£]\s?\d|\d\s?(?:dollars?|bucks|aud|k)\b|\bprice[sdy]?\b|\bpricing\b|\bcosts?\b|\bcostly\b|"
    r"\bcheap\w*|\bexpensive\b|\boverpriced\b|\bafford\w*|\bvalue for money\b|\bfees?\b|"
    r"\bcharg(?:e|ed|es|ing)\b|\bquot(?:e|ed|es|ing)\b|\bdiscount\w*|\bpaid\b|\bbudget\b|\brates\b|"
    r"\binvoice\w*|\brefund\w*|\bbargain\w*",
    re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://|\bwww\.|\.com\b|\.au\b|\.net\b|\.org\b", re.I)
_PHONE_RUN = re.compile(r"\+?\(?\d[\d\s().-]{6,}\d")
_COMPARE = re.compile(
    r"\b(?:better than|compared (?:to|with)|unlike (?:the|other|most|many|some)|competitors?|elsewhere|"
    r"other (?:\w+ )?(?:salons?|places?|shops?|barbers?|vets?|clinics?|businesses|companies|stores?|"
    r"mechanics?|plumbers?|electricians?|hairdressers?|studios?|spas?|practices?|providers?)|"
    r"previous (?:\w+ )?(?:salon|barber|place|vet|clinic|mechanic|plumber|electrician|hairdresser|"
    r"company|shop|groomer|dentist|studio)|used to go to|switched from|instead of going|"
    r"went to (?:another|a different))\b",
    re.I)
_TITLE_NAME = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Miss|Doctor|Prof)\.?\s+[A-Z][\w'’-]+")
_CAP = r"[A-Z][a-z][a-z'’]*(?:-[A-Z][a-z]+)?"
_TWO_CAPS = re.compile(rf"\b({_CAP})\s+({_CAP})\b")
_BUSINESS_NOUN = (
    r"\b(?:Nails?|Salon|Spa|Beauty|Barbers?|Barbershop|Hair|Hairdressing|Clinic|Vets?|Veterinary|"
    r"Hospital|Plumbing|Electrical|Mechanics?|Auto(?:motive|s)?|Motors|Studio|Cafe|Bakery|Dental|Physio|"
    r"Pty|Ltd|Services|Group|Lashes|Brows|Grooming|Tattoo|Pharmacy|Fitness|Gym)\b")
_NAMED_BUSINESS = re.compile(rf"(?:\b{_CAP}\s+){{1,3}}{_BUSINESS_NOUN}")

# Capitalised words that are not part of a person's (or rival's) name. Lower-case.
COMMON_WORDS = set("""
i i'm i've i'd i'll im ive id a an the this that these those there here my our your his her their its we
she he they you it me us them who what when where why how which and but or so if then also very really
just only even still always never ever again highly definitely absolutely totally truly honestly
super extremely incredibly thank thanks thankyou cheers love loved lovely great good best better awesome
amazing excellent fantastic wonderful brilliant perfect beautiful happy friendly professional
recommend recommended recommending would will can could should did do does done had has have
got get gets went came come go going been was were is are am be being five star stars service
services staff team job work experience place shop salon store clinic customer customers quality
fast quick easy clean nice kind helpful polite welcoming outstanding top notch first time new old
all every everyone everything nothing no yes not well done many much more most some any one two three
after before during since today yesterday tonight morning afternoon evening week weekend month year
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december christmas easter mother's mothers father's fathers day
google maps review reviews australia australian victoria melbourne sydney geelong ballarat bendigo
cbd mum dad husband wife son daughter partner kids family friend friends
gel acrylic acrylics nails nail pedicure manicure shellac lash lashes brows haircut cut fade beard
dog dogs cat cats puppy vet vets mechanic plumber electrician car cars
""".split())


def _word(w: str) -> str:
    return w.lower().replace("’", "'")


def name_words(*texts: Optional[str]) -> List[str]:
    """Lower-case words of the business name / suburb / address — fine to mention."""
    words: List[str] = []
    for t in texts:
        words += [_word(w) for w in re.findall(r"[A-Za-z'’]+", t or "")]
    return words


def snippet_problem(text: str, own_words: Iterable[str] = ()) -> Optional[str]:
    """Why a review is unsafe to quote on the business's website, or None.

    `own_words`: lower-case words of this business's name/address, which a
    review may mention ("Got You Nails", "Diamond Creek")."""
    own = {_word(w) for w in own_words}
    if _EMAIL.search(text):
        return "email"
    if _URL.search(text):
        return "url"
    for m in _PHONE_RUN.finditer(text):
        if len(re.sub(r"\D", "", m.group(0))) >= 8:
            return "phone"
    if _PRICE.search(text):
        return "price"
    if _COMPARE.search(text):
        return "competitor"
    # "Pro Nails", "Smith's Barbers": a name in front of a business noun that
    # isn't this business's own name.
    for m in _NAMED_BUSINESS.finditer(text):
        words = [_word(w) for w in re.findall(r"[A-Za-z'’]+", m.group(0))][:-1]
        if any(w not in own and w not in COMMON_WORDS for w in words):
            return "competitor"
    if _TITLE_NAME.search(text):
        return "surname"
    # "Sophia Nguyen did my nails": two capitalised non-dictionary words in a row.
    for m in _TWO_CAPS.finditer(text):
        a, b = _word(m.group(1)), _word(m.group(2))
        if a in COMMON_WORDS or b in COMMON_WORDS or a in own or b in own:
            continue
        return "surname"
    return None


def pick_reviews(raw: Sequence[Dict[str, Any]], own_words: Iterable[str] = (),
                 limit: int = MAX_REVIEWS) -> Optional[List[Dict[str, Any]]]:
    """Raw review dicts (from JS_REVIEWS) → up to `limit` website-safe snippets.

    Best first: most stars (at least MIN_STARS), then reviews that fit without
    trimming, then Google's own "most relevant" order. One per reviewer."""
    own = list(own_words)
    candidates = []
    seen_text, seen_author = set(), set()
    for idx, r in enumerate(raw):
        stars = parse_stars(r.get("stars"))
        if stars is None or stars < MIN_STARS:
            continue
        lang = (r.get("lang") or "").lower()
        if lang and not lang.startswith("en"):
            continue
        text = norm_ws(r.get("text"))
        if not text or "(Translated by Google)" in text or "(Original)" in text:
            continue
        truncated = bool(r.get("truncated"))
        if truncated and text.endswith("…"):
            text = text[:-1].rstrip()
        if len(text) < MIN_CHARS or snippet_problem(text, own):
            continue
        author = first_name(r.get("author"))
        if not author or author.lower() in seen_author:
            continue
        if len(text) > MAX_CHARS:
            snippet = trim_snippet(text)
        elif truncated:  # "More" didn't expand, we only have the start of it
            snippet = text.rstrip(" ,;:-–—(&.") + "…"
        else:
            snippet = text
        if snippet.lower() in seen_text:
            continue
        seen_text.add(snippet.lower())
        seen_author.add(author.lower())
        candidates.append(((-stars, snippet != text, idx), {"text": snippet, "author": author, "stars": stars}))
    candidates.sort(key=lambda c: c[0])
    return [c[1] for c in candidates[:limit]] or None


def fallback_url(lead: Dict[str, Any]) -> str:
    query = " ".join(p for p in (lead.get("name"), lead.get("address")) if p)
    url = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(query)
    if lead.get("place_id"):
        url += "&query_place_id=" + urllib.parse.quote_plus(lead["place_id"])
    return url


def same_place(page_name: str, lead_name: str) -> bool:
    """Loose check that the page we landed on is this business."""
    def toks(s: str) -> set:
        return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) >= 3 or w.isdigit()}
    a, b = toks(page_name), toks(lead_name)
    if not a or not b:
        return True  # nothing comparable ("K&N") — don't block on it
    return bool(a & b)


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

async def _open(scraper: GoogleMapsScraper, page, url: str) -> Dict[str, Any]:
    """Navigate and wait for the place panel (or a results list)."""
    await page.goto(url, wait_until="domcontentloaded", timeout=settings.TIMEOUT_MS)
    await scraper._dismiss_consent(page)
    if "/sorry/" in page.url or "captcha" in page.url.lower():
        raise BlockedError("Google served a CAPTCHA (/sorry/).")
    try:
        await page.wait_for_selector('div[role="main"] h1, div[role="feed"]', timeout=15_000)
    except Exception:
        pass
    await _human_pause(0.8, 1.6)
    state = await page.evaluate(JS_PAGE_STATE)
    if state["blocked"] or "/sorry/" in state["url"]:
        raise BlockedError("Google is showing an 'unusual traffic' / captcha page.")
    return state


async def _open_place(scraper: GoogleMapsScraper, page, url: str) -> Dict[str, Any]:
    state = await _open(scraper, page, url)
    if not state["h1"] and state["feed"] and state["firstPlace"]:
        # A search URL that landed on a results list: take the top hit.
        state = await _open(scraper, page, state["firstPlace"])
    return state


async def _read_hours(page) -> Optional[List[List[str]]]:
    for attempt in range(2):
        try:
            hours = parse_hours(await page.evaluate(JS_HOURS))
        except Exception:
            hours = None
        if hours or attempt:
            return hours
        await asyncio.sleep(1.5)  # the info panel sometimes paints a beat later
    return None


async def _open_reviews_tab(page) -> bool:
    for sel in ('button[role="tab"][aria-label^="Reviews" i]',
                'button[role="tab"]:has-text("Reviews")',
                'button[aria-label^="More reviews" i]',
                'button:has-text("More reviews")'):
        try:
            el = page.locator(sel).first
            if await el.count():
                await el.click(timeout=5_000)
                await page.wait_for_selector("div.jftiEf[data-review-id], [data-review-id] .wiI7pd",
                                             timeout=10_000)
                return True
        except Exception:
            continue
    return False


async def _read_reviews(page, own_words: List[str]) -> Optional[List[Dict[str, Any]]]:
    on_tab = await _open_reviews_tab(page)  # if not, read the few shown on Overview
    await asyncio.sleep(random.uniform(1.2, 2.0))
    picks = None
    for round_no in range(SCROLL_ROUNDS + 1):
        try:
            if await page.evaluate(JS_EXPAND_REVIEWS):
                await asyncio.sleep(0.8)
            raw = await page.evaluate(JS_REVIEWS)
        except Exception:
            raw = []
        picks = pick_reviews(raw, own_words)
        ideal = [p for p in (picks or []) if p["stars"] == 5 and not p["text"].endswith("…")]
        if len(ideal) >= MAX_REVIEWS or not on_tab or round_no == SCROLL_ROUNDS:
            break
        try:
            if not await page.evaluate(JS_SCROLL_REVIEWS):
                break
        except Exception:
            break
        await asyncio.sleep(random.uniform(1.8, 2.6))
    return picks


async def _enrich_one(scraper: GoogleMapsScraper, page, lead: Dict[str, Any],
                      log: Callable[[str], Any]) -> Optional[Dict[str, Any]]:
    """→ {"hours": …, "reviews": …}, or None if the place page couldn't be read.
    Raises BlockedError when Google starts serving captchas."""
    try:
        state = await _open_place(scraper, page, lead.get("maps_url") or fallback_url(lead))
        if not state["h1"] and lead.get("maps_url"):
            log("    no place panel at maps_url — trying a search")
            state = await _open_place(scraper, page, fallback_url(lead))
    except BlockedError:
        raise
    except Exception as e:
        log(f"    couldn't open the page: {type(e).__name__}: {str(e)[:120]}")
        return None

    if not state["h1"]:
        log("    no place panel")
        return None
    if not same_place(state["h1"], lead["name"]):
        log(f"    page is {state['h1']!r}, not {lead['name']!r} — skipped")
        return None

    hours = await _read_hours(page)  # Overview tab: read before switching to Reviews
    own = name_words(lead.get("name"), state["h1"], lead.get("suburb"), lead.get("address"))
    try:
        reviews = await _read_reviews(page, own)
    except Exception as e:
        log(f"    reviews failed: {type(e).__name__}: {str(e)[:120]}")
        reviews = None
    return {"hours": hours, "reviews": reviews}


def _load_leads(slugs: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    with db.connect() as con:
        for slug in slugs:
            r = con.execute("SELECT slug, name, maps_url, place_id, address, suburb FROM leads WHERE slug = ?",
                            (slug,)).fetchone()
            if r:
                rows[slug] = dict(r)
    return rows


def _save(slug: str, hours, reviews) -> None:
    with db.connect() as con:
        con.execute("UPDATE leads SET hours_json = ?, reviews_json = ?, enriched_at = ? WHERE slug = ?",
                    (json.dumps(hours, ensure_ascii=False) if hours else None,
                     json.dumps(reviews, ensure_ascii=False) if reviews else None,
                     db.now(), slug))


async def enrich_async(slugs: Iterable[str], log: Callable[[str], Any] = print,
                       pace: float = 6.0) -> Dict[str, Any]:
    """Open each lead's Google Maps page (one at a time, `pace` s ±30% apart)
    and store opening hours + up to 3 review snippets on the lead.

    → {"done", "hours", "reviews", "failed": [slugs], "blocked": bool, "skipped": [slugs]}.
    Stops cleanly at the first captcha; leads not reached are in "skipped"."""
    slugs = list(dict.fromkeys(s for s in slugs if s))
    result: Dict[str, Any] = {"done": 0, "hours": 0, "reviews": 0, "failed": [],
                              "blocked": False, "skipped": []}
    leads = _load_leads(slugs)
    for slug in slugs:
        if slug not in leads:
            log(f"{slug}: not in the tracker")
            result["failed"].append(slug)
    todo = [s for s in slugs if s in leads]
    if not todo:
        return result

    async with GoogleMapsScraper() as scraper:
        page = await scraper._ctx.new_page()
        for i, slug in enumerate(todo, 1):
            lead = leads[slug]
            if i > 1:
                await asyncio.sleep(max(0.0, pace * random.uniform(0.7, 1.3)))
            log(f"[{i}/{len(todo)}] {lead['name']} ({slug})")
            try:
                got = await _enrich_one(scraper, page, lead, log)
            except BlockedError as e:
                result["blocked"] = True
                result["skipped"] = todo[i - 1:]
                log(f"  ✗ {e} Stopped after {result['done']} of {len(todo)}; "
                    f"{len(result['skipped'])} not done — try again later.")
                break
            except Exception as e:  # browser hiccup: fresh tab, carry on
                log(f"  ✗ {type(e).__name__}: {str(e)[:160]}")
                got = None
                try:
                    await page.close()
                except Exception:
                    pass
                page = await scraper._ctx.new_page()
            if got is None:
                result["failed"].append(slug)
                continue
            _save(slug, got["hours"], got["reviews"])
            result["done"] += 1
            result["hours"] += bool(got["hours"])
            result["reviews"] += bool(got["reviews"])
            n = len(got["reviews"] or [])
            log(f"  {'✓' if got['hours'] else '–'} hours, {n} review{'' if n == 1 else 's'}")
        try:
            await page.close()
        except Exception:
            pass
    return result


def enrich(slugs: Iterable[str], log: Callable[[str], Any] = print, pace: float = 6.0) -> Dict[str, Any]:
    return asyncio.run(enrich_async(slugs, log=log, pace=pace))


def pending(grades: Sequence[str] = ("Hot",), limit: Optional[int] = None, redo: bool = False) -> List[str]:
    """Slugs worth enriching next: best score first, not yet enriched."""
    sql = "SELECT slug FROM leads WHERE 1=1"
    args: List[Any] = []
    if grades:
        sql += f" AND grade IN ({','.join('?' * len(grades))})"
        args += list(grades)
    if not redo:
        sql += " AND enriched_at IS NULL"
    sql += " ORDER BY score DESC, reviews DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(int(limit))
    with db.connect() as con:
        return [r["slug"] for r in con.execute(sql, args)]


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(prog="python -m pipeline.enrich",
                                description="Add opening hours + review snippets from Google Maps to leads.")
    p.add_argument("slugs", nargs="*", help="leads to enrich (default: the next un-enriched ones)")
    p.add_argument("--grade", default="Hot", help="comma list, or 'all' (used when no slugs are given)")
    p.add_argument("--limit", type=int, default=20, help="how many leads when no slugs are given (default 20)")
    p.add_argument("--redo", action="store_true", help="include leads that were already enriched")
    p.add_argument("--pace", type=float, default=6.0, help="seconds between businesses, ±30%% (default 6)")
    a = p.parse_args()
    grades = [] if a.grade.lower() == "all" else [g.strip() for g in a.grade.split(",") if g.strip()]
    todo = a.slugs or pending(grades, a.limit, a.redo)
    print(f"Enriching {len(todo)} lead(s) → {db.DB_PATH}")
    print(json.dumps(enrich(todo, pace=a.pace), indent=2, ensure_ascii=False))
