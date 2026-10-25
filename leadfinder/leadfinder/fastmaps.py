"""Fast Google Maps search over plain HTTP. No browser.

The Playwright scraper opens the results page, scrolls it, then opens every
listing one by one to read its phone and website: about 30 seconds and 21
page loads per search, which is why the 2026 Victoria sweep took four days.

The Maps web app fills its results list from one request,
``/search?tbm=map&q=…&pb=…``, and that response already carries everything
the detail pages do: name, categories, phone, website, rating, review count,
address, coordinates, opening hours and whether the owner has claimed the
listing. This module makes that request directly: one HTTP call per 20
businesses, about 0.7 seconds each.

``pb`` is the protobuf-ish parameter string the web app sends. Only the
query (``!1s``), the page size (``!7i``) and the offset (``!8i``) change
between calls; the rest asks for the fields we read below. Captured from
www.google.com/maps in October 2026. If Google changes the response shape,
``parse()`` returns nothing and ``tests/test_fastmaps.py`` fails on the saved
fixture's replacement; the Playwright provider still works meanwhile.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
import urllib.parse
from typing import Any, Callable, Iterable, List, Optional

import httpx

from . import geo
from .config import settings
from .models import Business
from .scraper import USER_AGENT, BlockedError

PAGE_SIZE = 20

# Everything after "!7i20" in the pb the web app sends: which fields to return.
PB_FIELDS = (
    "!10b1!12m58!1m5!18b1!30b1!31m1!1b1!34e1!2m4!5m1!6e2!20e3!39b1!6m29!32i1!49b1!63m0!66b1!85b1"
    "!114b1!149b1!206b1!209b1!212b1!215b1!216b1!222b1!223b1!234b1!235b1!239b1!246b1!253b1!260b1"
    "!262b1!266b1!270b1!271b1!273b1!281b1!294b1!302i300!303i100!10b1!12b1!13b1!14b1!16b1!17m1"
    "!3e1!20m3!5e2!6b1!14b1!46m1!1b0!96b1!97m1!2b1!99b1!19m4!2m3!1i360!2i120!4i8!20m57!2m2!1i203"
    "!2i100!3m2!2i4!5b1!6m6!1m2!1i86!2i86!1m2!1i408!2i240!7m33!1m3!1e1!2b0!3e3!1m3!1e2!2b1!3e2"
    "!1m3!1e2!2b0!3e3!1m3!1e8!2b0!3e3!1m3!1e10!2b0!3e3!1m3!1e10!2b1!3e2!1m3!1e10!2b0!3e4!1m3"
    "!1e9!2b1!3e2!2b1!9b0!15m8!1m7!1m2!1m1!1e2!2m2!1i195!2i195!3i20!24m107!1m25!13m9!2b1!3b1"
    "!4b1!6i1!8b1!9b1!14b1!20b1!25b1!18m14!3b1!4b1!5b1!6b1!13b1!14b1!17b1!21b1!22b1!32b1!33m1"
    "!1b1!34b1!36e2!10m1!8e3!11m1!3e1!17b1!20m2!1e3!1e6!24b1!25b1!26b1!27b1!29b1!30m1!2b1!36b1"
    "!37b1!39m3!2m2!2i1!3i1!43b1!52b1!54m1!1b1!55b1!56m1!1b1!61m2!1m1!1e1!65m5!3m4!1m3!1m2!1i224"
    "!2i298!72m22!1m8!2b1!5b1!7b1!12m4!1b1!2b1!4m1!1e1!4b1!8m10!1m6!4m1!1e1!4m1!1e3!4m1!1e4"
    "!3sother_user_google_review_posts__and__hotel_and_vr_partner_review_posts!6m1!1e1!9b1!89b1"
    "!90m2!1m1!1e2!98m3!1b1!2b1!3b1!103b1!113b1!114m3!1b1!2m1!1b1!117b1!122m1!1b1!126b1!127b1"
    "!128m1!1b1!26m4!2m3!1i80!2i92!4i8!30m28!1m6!1m2!1i0!2i0!2m2!1i530!2i768!1m6!1m2!1i974!2i0"
    "!2m2!1i1024!2i768!1m6!1m2!1i0!2i0!2m2!1i1024!2i20!1m6!1m2!1i0!2i748!2m2!1i1024!2i768!34m19"
    "!2b1!3b1!4b1!6b1!8m6!1b1!3b1!4b1!5b1!6b1!7b1!9b1!12b1!14b1!20b1!23b1!25b1!26b1!31b1!37m1"
    "!1e81!42b1!49m10!3b1!6m2!1b1!2b1!7m2!1e3!2b1!8b1!9b1!10e2!50m3!2e2!3m1!3b1!61b1!67m5!7b1"
    "!10b1!14b1!15m1!1b0!69i800!77b1"
)

SEARCH_URL = "https://www.google.com/search"

STATE_ABBR = {
    "new south wales": "NSW", "victoria": "VIC", "queensland": "QLD", "south australia": "SA",
    "western australia": "WA", "tasmania": "TAS", "australian capital territory": "ACT",
    "northern territory": "NT",
}
_ADDR_TAIL = re.compile(r"(?:^|,\s*)([^,]*?)\s+(VIC|NSW|QLD|SA|WA|TAS|ACT|NT)\s+(\d{4})\s*$")


def build_pb(query: str, offset: int = 0) -> str:
    # "!" and "*" are the format's own delimiter and escape; a query never needs them.
    q = re.sub(r"[!*]", " ", query).strip()
    return f"!1s{q}!7i{PAGE_SIZE}" + (f"!8i{offset}" if offset else "") + PB_FIELDS


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def _g(x: Any, *path: int) -> Any:
    for i in path:
        if not isinstance(x, list) or i >= len(x):
            return None
        x = x[i]
    return x


def _looks_like_place(x: Any) -> bool:
    return (isinstance(x, list) and len(x) > 80 and isinstance(_g(x, 11), str)
            and isinstance(_g(x, 10), str) and _g(x, 10).startswith("0x"))


def _place_arrays(data: Any) -> List[list]:
    """The per-business arrays, in Google's ranking order."""
    rows = _g(data, 64)
    if isinstance(rows, list) and rows and all(_looks_like_place(_g(r, 1)) for r in rows):
        return [r[1] for r in rows]
    # The layout moved: fall back to finding them anywhere in the payload.
    found: List[list] = []

    def walk(x: Any, depth: int) -> None:
        if depth > 6 or not isinstance(x, list):
            return
        if _looks_like_place(x):
            found.append(x)
            return
        for y in x:
            walk(y, depth + 1)

    walk(data, 0)
    return found


def decode(text: str) -> Any:
    """Strip Google's anti-JSON-hijacking prefix and parse."""
    if text.startswith(")]}'"):
        text = text[text.index("\n") + 1:]
    return json.loads(text)


def maps_url(name: str, hex_id: str, lat: Optional[float], lng: Optional[float],
             kg_id: str = "", google_id: str = "") -> str:
    """Same shape as the URLs the Playwright scraper records, so the pipeline's
    ``place_id()`` (``!19sChIJ…``) and the enricher's page visits keep working."""
    name_part = urllib.parse.quote_plus(name or "place")
    data = f"!4m7!3m6!1s{hex_id}"
    if lat is not None and lng is not None:
        data += f"!8m2!3d{lat}!4d{lng}"
    if kg_id:
        data += "!16s" + urllib.parse.quote(kg_id, safe="")
    if google_id:
        data += f"!19s{google_id}"
    return f"https://www.google.com/maps/place/{name_part}/data={data}?authuser=0&hl=en"


def _closed_flag(info: list) -> str:
    """"permanently" / "temporarily" / "". Google states it in a short text
    field of the listing; we look for the words rather than trust an index."""
    for i in (88, 203, 34):
        blob = json.dumps(_g(info, i)) if _g(info, i) is not None else ""
        low = blob.lower()
        if "permanently closed" in low:
            return "permanently"
        if "temporarily closed" in low:
            return "temporarily"
    return ""


def place_to_business(info: list) -> Optional[Business]:
    name = (_g(info, 11) or "").strip()
    hex_id = _g(info, 10) or ""
    if not name or not hex_id:
        return None
    categories = [c for c in (_g(info, 13) or []) if isinstance(c, str)]
    lat, lng = _g(info, 9, 2), _g(info, 9, 3)
    google_id = _g(info, 78) or ""
    kg_id = _g(info, 89) or ""

    phone = _g(info, 178, 0, 0) or _g(info, 178, 0, 3) or ""
    website = _g(info, 7, 0) or ""
    if website.startswith("/url?"):
        website = urllib.parse.parse_qs(urllib.parse.urlparse(website).query).get("q", [""])[0]

    rating = _g(info, 4, 7)
    reviews = _g(info, 4, 8)

    street_address = (_g(info, 39) or "").strip()
    parts = _g(info, 183, 1) or []
    suburb = (_g(parts, 3) or "").strip()
    postcode = (_g(parts, 4) or "").strip()
    state = STATE_ABBR.get((_g(parts, 5) or "").strip().lower(), "")
    m = _ADDR_TAIL.search(street_address)
    if m:
        suburb = suburb or m.group(1).strip()
        state = state or m.group(2)
        postcode = postcode or m.group(3)

    service_area = not street_address
    if service_area and lat is not None and lng is not None:
        near = geo.nearest(lat, lng)
        if near:
            suburb, state, postcode = near["locality"], near["state"], near["postcode"]
    if street_address:
        address = f"{street_address}, Australia" if state else street_address
    elif suburb and state:
        # No street address on the listing (a mobile or home-based business):
        # the nearest locality, so a rep knows where they are.
        address = f"{suburb} {state} {postcode}".strip() + ", Australia"
    else:
        address = ""

    return Business(
        name=name,
        category=categories[0] if categories else "",
        address=address,
        phone=phone.replace("‪", "").replace("‬", "").strip(),
        website=website.strip(),
        rating=float(rating) if isinstance(rating, (int, float)) else None,
        reviews=int(reviews) if isinstance(reviews, (int, float)) else None,
        maps_url=maps_url(name, hex_id, lat, lng, kg_id, google_id),
        place_id=hex_id,
        google_id=google_id,
        lat=lat,
        lng=lng,
        suburb=suburb,
        state=state,
        postcode=postcode,
        service_area=service_area,
        # An unclaimed listing carries a "Claim this business" link here.
        claimed="claimbz" not in json.dumps(_g(info, 49) or "") and _g(info, 49, 1) != "Claim this business",
        has_hours=_g(info, 203) is not None,
        closed=_closed_flag(info),
        categories=categories,
    )


def parse(text: str) -> List[Business]:
    out: List[Business] = []
    for info in _place_arrays(decode(text)):
        b = place_to_business(info)
        if b:
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class RateLimiter:
    """At most ``rate`` requests a second across every worker, jittered so
    the rhythm doesn't look machine-made. ``slow_down()`` after a block makes
    the rest of the run gentler."""

    def __init__(self, rate: float) -> None:
        self.interval = 1.0 / max(0.05, rate)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = time.monotonic() + self.interval * random.uniform(0.6, 1.4)

    def slow_down(self, factor: float = 1.5, floor_rate: float = 0.2) -> None:
        self.interval = min(self.interval * factor, 1.0 / floor_rate)

    @property
    def rate(self) -> float:
        return 1.0 / self.interval


KeepGoing = Callable[[List[Business]], bool]


class FastMapsClient:
    """Async context manager, shaped like ``GoogleMapsScraper``::

        async with FastMapsClient(rate=1.5) as c:
            results = await c.search("plumber in Dubbo, NSW, Australia", 40)
    """

    def __init__(self, rate: float = 1.5, timeout: float = 30.0) -> None:
        self.limiter = RateLimiter(rate)
        self.timeout = timeout
        self.requests = 0
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "FastMapsClient":
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": f"{settings.LOCALE},{settings.HL};q=0.9",
                "Referer": "https://www.google.com/maps",
            },
            timeout=self.timeout,
            follow_redirects=True,
            proxy=settings.PROXY,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_page(self, query: str, offset: int = 0) -> List[Business]:
        assert self._client is not None, "use `async with FastMapsClient() as c:`"
        await self.limiter.wait()
        params = {"tbm": "map", "authuser": "0", "hl": settings.HL, "gl": settings.GL,
                  "q": query, "pb": build_pb(query, offset)}
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = await self._client.get(SEARCH_URL, params=params)
                break
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                await asyncio.sleep(2 + attempt * 3)
        else:
            raise RuntimeError(f"network error: {last_exc}")
        self.requests += 1

        url = str(r.url)
        if r.status_code == 429 or "/sorry/" in url or "unusual traffic" in r.text[:5000].lower():
            raise BlockedError("Google is rate-limiting this IP (HTTP %s, %s)." % (r.status_code, url[:80]))
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} from Google Maps search")
        if not r.text.startswith(")]}'"):
            # A consent page, a captcha page, or a format change. Treat as a
            # block: the runner backs off and retries rather than recording
            # an empty result for this town.
            raise BlockedError("Google returned a page instead of search results.")
        return parse(r.text)

    async def search(self, query: str, max_results: int = PAGE_SIZE,
                     keep_going: Optional[KeepGoing] = None) -> List[Business]:
        """Up to ``max_results`` businesses, a page (20) at a time.

        ``keep_going(page)`` decides whether the next page is worth a request;
        without it, pages are fetched until ``max_results`` or the list ends.
        """
        out: List[Business] = []
        seen: set = set()
        offset = 0
        while offset < max_results:
            page = await self.fetch_page(query, offset)
            fresh = [b for b in page if b.dedupe_key not in seen]
            seen.update(b.dedupe_key for b in fresh)
            out.extend(fresh)
            offset += PAGE_SIZE
            if len(page) < PAGE_SIZE or not fresh:
                break
            if keep_going is not None and not keep_going(fresh):
                break
        return out[:max_results]


def unique(items: Iterable[Business]) -> List[Business]:
    seen: set = set()
    out = []
    for b in items:
        if b.dedupe_key not in seen:
            seen.add(b.dedupe_key)
            out.append(b)
    return out
