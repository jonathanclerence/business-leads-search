"""Playwright-based Google Maps scraper.

Strategy (this is the part that makes it reliable):

  1. Open the Maps *search* URL, dismiss the EU consent wall if it appears.
  2. Scroll the results feed (``div[role="feed"]``) until we have enough
     cards or Google tells us we hit the end of the list.
  3. Harvest every ``/maps/place/`` link out of the feed. Links are the most
     stable thing on the page — Google rewrites CSS class names constantly,
     but the URL scheme has been the same for years.
  4. Fan out: N worker tabs navigate straight to each place URL and read the
     detail panel. Navigating beats clicking-then-going-back — no lost state,
     no stale element handles, and it parallelises cleanly.

Every selector below has at least one fallback, and the final safety net is
regex over ``aria-label`` / ``data-item-id`` attributes, which Google keeps
stable for accessibility reasons.
"""

from __future__ import annotations

import asyncio
import random
import re
import urllib.parse
from typing import Awaitable, Callable, Iterable

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)

from .config import settings
from .models import Business

ProgressFn = Callable[[str, dict], Awaitable[None]]


class BlockedError(RuntimeError):
    """Google served a CAPTCHA / "unusual traffic" interstitial.

    Raised rather than returning zero results, so a long batch run can tell
    the difference between "this town genuinely has no dentists" and "we have
    been rate-limited and everything from here is garbage".
    """

# A current, ordinary desktop Chrome UA. Playwright's default UA contains
# "HeadlessChrome", which is the single easiest way to get flagged.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-features=IsolateOrigins,site-per-process",
    "--lang=en-US",
]

# Injected before any page script runs. Cheap, effective, well-understood.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
const _query = window.navigator.permissions && window.navigator.permissions.query;
if (_query) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _query(p);
}
"""

END_OF_LIST_MARKERS = (
    "You've reached the end of the list",
    "You have reached the end of the list",
)

CONSENT_SELECTORS = (
    'button[aria-label*="Accept all" i]',
    'button[aria-label*="Reject all" i]',
    'form[action*="consent"] button',
    'button:has-text("Accept all")',
    'button:has-text("I agree")',
)

# ---------------------------------------------------------------------------
# In-page extraction. Kept as JS strings so each place costs ONE round-trip
# instead of a dozen selector queries over the CDP wire.
# ---------------------------------------------------------------------------

JS_COLLECT_LINKS = """
() => {
  const feed = document.querySelector('div[role="feed"]')
            || document.querySelector('div[role="main"]');
  const scope = feed || document;
  const out = [];
  const seen = new Set();
  scope.querySelectorAll('a[href*="/maps/place/"]').forEach((a) => {
    const href = a.href;
    if (!href || seen.has(href)) return;
    seen.add(href);
    const card = a.closest('div[jsaction]') || a.parentElement;
    const cardText = card ? card.innerText : '';
    out.push({
      url: href,
      name: (a.getAttribute('aria-label') || '').trim(),
      // Does the card itself already show a "Website" button? Useful as a
      // cross-check against the detail panel.
      cardHasWebsite: !!(card && card.querySelector('a[data-value="Website"], a[aria-label^="Visit"]')),
      cardText: cardText,
    });
  });
  return out;
}
"""

JS_SCROLL_FEED = """
() => {
  const feed = document.querySelector('div[role="feed"]');
  if (feed) { feed.scrollTop = feed.scrollHeight; return true; }
  window.scrollTo(0, document.body.scrollHeight);
  return false;
}
"""

JS_EXTRACT_PLACE = r"""
() => {
  const q = (s) => document.querySelector(s);
  const txt = (el) => (el ? (el.textContent || '').trim() : '');
  const attr = (el, a) => (el ? (el.getAttribute(a) || '').trim() : '');

  // ---- name -------------------------------------------------------------
  const main = q('div[role="main"]') || document;
  let name = txt(main.querySelector('h1')) || txt(q('h1.DUwDvf')) || txt(q('h1'));
  if (/^Results$/i.test(name)) name = '';

  // ---- address ----------------------------------------------------------
  let address = '';
  const addrBtn = q('button[data-item-id="address"]');
  if (addrBtn) {
    address = attr(addrBtn, 'aria-label').replace(/^Address:\s*/i, '').trim();
    if (!address) address = txt(addrBtn.querySelector('.Io6YTe')) || txt(addrBtn);
  }
  if (!address) {
    const alt = q('[data-tooltip="Copy address"]');
    if (alt) address = attr(alt, 'aria-label').replace(/^Address:\s*/i, '').trim();
  }

  // ---- phone ------------------------------------------------------------
  let phone = '';
  const phoneBtn = q('button[data-item-id^="phone:tel:"]')
                || q('[data-tooltip="Copy phone number"]');
  if (phoneBtn) {
    phone = attr(phoneBtn, 'data-item-id').replace(/^phone:tel:/, '').trim();
    if (!phone) phone = attr(phoneBtn, 'aria-label').replace(/^Phone:\s*/i, '').trim();
    if (!phone) phone = txt(phoneBtn.querySelector('.Io6YTe'));
  }

  // ---- website ----------------------------------------------------------
  let website = '';
  const siteEl = q('a[data-item-id="authority"]')
              || q('a[data-tooltip="Open website"]')
              || q('a[aria-label^="Website:"]');
  if (siteEl) website = siteEl.href || '';
  // Guard: never report a Google URL as the business's own website.
  if (/^https?:\/\/(www\.)?google\.[a-z.]+\//i.test(website)) website = '';

  // ---- category ---------------------------------------------------------
  let category = txt(q('button[jsaction*="category"]')) || txt(q('.DkEaL'));

  // ---- rating + review count -------------------------------------------
  let rating = null, reviews = null;
  const block = q('div.F7nice') || main;
  const rEl = block.querySelector('span[aria-hidden="true"]');
  if (rEl) {
    const v = parseFloat(txt(rEl).replace(',', '.'));
    if (!isNaN(v) && v >= 0 && v <= 5) rating = v;
  }
  if (rating === null) {
    const stars = q('span[role="img"][aria-label*="star" i]')
               || q('[role="img"][aria-label*="star" i]');
    const m = attr(stars, 'aria-label').match(/([\d.,]+)/);
    if (m) {
      const v = parseFloat(m[1].replace(',', '.'));
      if (!isNaN(v) && v <= 5) rating = v;
    }
  }
  const revEl = block.querySelector('span[aria-label*="review" i]')
             || q('button[aria-label*="review" i]')
             || q('a[aria-label*="review" i]');
  if (revEl) {
    const raw = (attr(revEl, 'aria-label') || txt(revEl)).replace(/[,\s ]/g, '');
    const m = raw.match(/(\d+)/);
    if (m) reviews = parseInt(m[1], 10);
  }

  return { name, address, phone, website, category, rating, reviews, url: location.href };
}
"""

_PLACE_ID_RE = re.compile(r"!1s([^!?/]+)")
_HEX_ID_RE = re.compile(r"(0x[0-9a-f]+:0x[0-9a-f]+)", re.I)


def _extract_place_id(url: str) -> str:
    m = _HEX_ID_RE.search(url) or _PLACE_ID_RE.search(url)
    return urllib.parse.unquote(m.group(1)) if m else ""


def _clean_phone(raw: str) -> str:
    raw = (raw or "").replace("‪", "").replace("‬", "").strip()
    # Drop anything that clearly isn't a phone number.
    if raw and not re.search(r"\d", raw):
        return ""
    return re.sub(r"\s{2,}", " ", raw)


def build_search_url(query: str) -> str:
    q = urllib.parse.quote_plus(query)
    return (
        f"https://www.google.com/maps/search/{q}"
        f"?hl={settings.HL}&gl={settings.GL}&authuser=0"
    )


async def _human_pause(lo: float = 0.35, hi: float = 0.9) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


class GoogleMapsScraper:
    """Async context manager wrapping a browser + context.

    Usage::

        async with GoogleMapsScraper() as s:
            results = await s.search("a/c repair in Sydney, Australia", 50)
    """

    def __init__(
        self,
        headless: bool | None = None,
        concurrency: int | None = None,
        on_progress: ProgressFn | None = None,
    ) -> None:
        self.headless = settings.HEADLESS if headless is None else headless
        self.concurrency = concurrency or settings.CONCURRENCY
        self.on_progress = on_progress
        self._pw = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None

    # ------------------------------------------------------------- lifecycle
    async def __aenter__(self) -> "GoogleMapsScraper":
        self._pw = await async_playwright().start()
        launch_kwargs: dict = {"headless": self.headless, "args": LAUNCH_ARGS}
        if settings.CHROMIUM_PATH:
            launch_kwargs["executable_path"] = settings.CHROMIUM_PATH
        if settings.PROXY:
            launch_kwargs["proxy"] = {"server": settings.PROXY}
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._ctx = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale=settings.LOCALE,
            timezone_id=settings.TIMEZONE,
            geolocation=None,
            extra_http_headers={
                "Accept-Language": f"{settings.LOCALE},{settings.HL};q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Upgrade-Insecure-Requests": "1",
            },
        )
        self._ctx.set_default_timeout(settings.TIMEOUT_MS)
        await self._ctx.add_init_script(STEALTH_JS)
        return self

    async def __aexit__(self, *exc) -> None:
        for closer in (self._ctx, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception:
                pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

    # -------------------------------------------------------------- progress
    async def _emit(self, event: str, **data) -> None:
        if self.on_progress:
            await self.on_progress(event, data)

    # ----------------------------------------------------------------- steps
    async def _dismiss_consent(self, page: Page) -> None:
        """Google's EU cookie wall. Harmless no-op elsewhere."""
        if "consent." not in page.url and "/consent" not in page.url:
            # Consent can also render as an in-page dialog.
            try:
                if not await page.locator('form[action*="consent"]').count():
                    return
            except Exception:
                return
        for sel in CONSENT_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.count():
                    await el.click(timeout=4000)
                    await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    await _human_pause()
                    return
            except Exception:
                continue

    async def _scroll_feed(self, page: Page, target: int) -> list[dict]:
        """Scroll the results panel until we have ``target`` links or hit the end."""
        collected: list[dict] = []
        stagnant = 0
        last_count = 0
        # Google loads ~7 cards per "page"; give it generous headroom.
        max_rounds = max(12, target // 5 + 12)

        for round_no in range(max_rounds):
            try:
                collected = await page.evaluate(JS_COLLECT_LINKS)
            except Exception:
                collected = []

            await self._emit(
                "scrolling",
                found=len(collected),
                target=target,
                message=f"Loaded {len(collected)} listings…",
            )

            if len(collected) >= target:
                break

            body_text = ""
            try:
                body_text = await page.inner_text("body", timeout=5000)
            except Exception:
                pass
            if any(m in body_text for m in END_OF_LIST_MARKERS):
                break

            if len(collected) == last_count:
                stagnant += 1
                if stagnant >= 4:
                    break
            else:
                stagnant = 0
            last_count = len(collected)

            try:
                await page.evaluate(JS_SCROLL_FEED)
                # A nudge with the mouse wheel too — some builds only lazy-load
                # in response to a real wheel event.
                await page.mouse.move(500, 500)
                await page.mouse.wheel(0, 3000)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.9, 1.6))

        return collected

    async def _extract_place(self, page: Page, url: str, fallback_name: str) -> Business | None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.TIMEOUT_MS)
        except PWTimeout:
            return None
        except Exception:
            return None

        # Wait for the detail panel to actually paint.
        try:
            await page.wait_for_selector(
                'div[role="main"] h1, h1.DUwDvf, button[data-item-id="address"]',
                timeout=12_000,
            )
        except PWTimeout:
            pass
        await _human_pause(0.2, 0.55)

        try:
            data = await page.evaluate(JS_EXTRACT_PLACE)
        except Exception:
            return None

        name = (data.get("name") or fallback_name or "").strip()
        if not name:
            return None

        return Business(
            name=name,
            category=(data.get("category") or "").strip(),
            address=(data.get("address") or "").strip(),
            phone=_clean_phone(data.get("phone") or ""),
            website=(data.get("website") or "").strip(),
            rating=data.get("rating"),
            reviews=data.get("reviews"),
            maps_url=data.get("url") or url,
            place_id=_extract_place_id(data.get("url") or url),
        )

    # ------------------------------------------------------------------ main
    async def search(self, full_query: str, max_results: int = 20) -> list[Business]:
        assert self._ctx is not None, "use `async with GoogleMapsScraper() as s:`"
        max_results = max(1, min(int(max_results), 500))

        page = await self._ctx.new_page()
        await self._emit("status", message=f"Opening Google Maps for “{full_query}”…")

        await page.goto(
            build_search_url(full_query),
            wait_until="domcontentloaded",
            timeout=settings.TIMEOUT_MS,
        )
        await self._dismiss_consent(page)

        # Bail loudly if we've been rate-limited. Silently returning [] here
        # would poison an overnight batch with hundreds of empty "results".
        if "/sorry/" in page.url or "captcha" in page.url.lower():
            await page.close()
            raise BlockedError(
                "Google served a CAPTCHA (/sorry/index). Slow down, switch IP, "
                "or set HEADLESS=false and solve it once by hand."
            )

        # Two shapes are possible: a results feed, or (for a very specific
        # query) Maps jumps straight to a single place page.
        try:
            await page.wait_for_selector('div[role="feed"], div[role="main"] h1', timeout=20_000)
        except PWTimeout:
            await self._emit("status", message="Google Maps did not return a results panel.")

        has_feed = await page.locator('div[role="feed"]').count() > 0

        if not has_feed and "/maps/place/" in page.url:
            single = await self._extract_place(page, page.url, "")
            await page.close()
            return [single] if single else []

        await self._emit("status", message="Scrolling the results panel…")
        cards = await self._scroll_feed(page, max_results)
        cards = cards[:max_results]
        await page.close()

        if not cards:
            return []

        await self._emit(
            "status",
            message=f"Found {len(cards)} listings. Reading details…",
            found=len(cards),
            target=len(cards),
        )

        return await self._fetch_details(cards)

    async def _fetch_details(self, cards: Iterable[dict]) -> list[Business]:
        cards = list(cards)
        results: dict[int, Business] = {}
        sem = asyncio.Semaphore(self.concurrency)
        processed = 0
        lock = asyncio.Lock()

        # One reusable tab per worker slot — cheaper than a tab per place.
        pages: asyncio.Queue[Page] = asyncio.Queue()
        for _ in range(self.concurrency):
            await pages.put(await self._ctx.new_page())  # type: ignore[union-attr]

        async def worker(idx: int, card: dict) -> None:
            nonlocal processed
            async with sem:
                page = await pages.get()
                try:
                    biz = await self._extract_place(page, card["url"], card.get("name", ""))
                    if biz:
                        results[idx] = biz
                finally:
                    await pages.put(page)
                async with lock:
                    processed += 1
                    await self._emit(
                        "progress",
                        processed=processed,
                        target=len(cards),
                        found=len(results),
                        message=f"Read {processed}/{len(cards)} listings…",
                        item=results[idx].to_dict() if idx in results else None,
                    )
                await _human_pause(0.15, 0.5)

        await asyncio.gather(*(worker(i, c) for i, c in enumerate(cards)))

        while not pages.empty():
            try:
                await (await pages.get()).close()
            except Exception:
                pass

        # Preserve Google's ranking order, then drop duplicates.
        ordered = [results[i] for i in sorted(results)]
        return dedupe(ordered)


def dedupe(items: list[Business]) -> list[Business]:
    seen: set[str] = set()
    out: list[Business] = []
    for b in items:
        key = b.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


async def scrape(
    full_query: str,
    max_results: int = 20,
    on_progress: ProgressFn | None = None,
    headless: bool | None = None,
) -> list[Business]:
    """Convenience one-shot wrapper."""
    async with GoogleMapsScraper(headless=headless, on_progress=on_progress) as s:
        return await s.search(full_query, max_results)
