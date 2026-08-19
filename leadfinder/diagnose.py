"""Selector diagnostic — run this when the scraper suddenly returns blanks.

Google reshuffles Google Maps' markup every few months. When that happens the
symptom is always the same: rows come back with names but empty phone/address/
website columns. This script tells you *which* selector broke, in one pass, so
you can patch `leadfinder/scraper.py` instead of guessing.

    python diagnose.py                              # default query
    python diagnose.py "dentists in Melbourne"      # your own query
    python diagnose.py "plumbers in Leeds" --show   # watch the browser work

It prints a live/broken verdict per selector, and saves a screenshot plus the
raw HTML of the first place page to ./exports/ so you can inspect the DOM.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.async_api import async_playwright  # noqa: E402

from leadfinder.config import settings  # noqa: E402
from leadfinder.scraper import (  # noqa: E402
    JS_COLLECT_LINKS,
    JS_EXTRACT_PLACE,
    LAUNCH_ARGS,
    STEALTH_JS,
    USER_AGENT,
    build_search_url,
)

# selector -> what it feeds
PROBES: list[tuple[str, str]] = [
    ('div[role="feed"]', "results panel (scrolling)"),
    ('a[href*="/maps/place/"]', "listing links"),
    ('div[role="main"] h1', "business name"),
    ('button[data-item-id="address"]', "address"),
    ('button[data-item-id^="phone:tel:"]', "phone number"),
    ('a[data-item-id="authority"]', "website URL"),
    ("div.F7nice", "rating + review count"),
    ("button.DkEaL, button[jsaction*='category']", "category"),
]


def ok(flag: bool) -> str:
    return "\033[32mLIVE  \033[0m" if flag else "\033[31mBROKEN\033[0m"


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    query = args[0] if args else "a/c repair in Sydney, Australia"
    headless = "--show" not in sys.argv

    launch: dict = {"headless": headless, "args": LAUNCH_ARGS}
    if settings.CHROMIUM_PATH:
        launch["executable_path"] = settings.CHROMIUM_PATH

    out = settings.EXPORT_DIR
    print(f"\nQuery: {query!r}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch)
        ctx = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        await ctx.add_init_script(STEALTH_JS)
        page = await ctx.new_page()

        # ---------------- search page ----------------
        await page.goto(build_search_url(query), wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        if "consent" in page.url or "sorry/index" in page.url:
            print("\033[33m!\033[0m Google served a consent or CAPTCHA page.")
            print(f"  URL: {page.url}")
            print("  Re-run with --show and solve it manually, or set SCRAPER_PROXY.\n")

        print("Search results page")
        for sel, label in PROBES[:2]:
            n = await page.locator(sel).count()
            print(f"  {ok(n > 0)} {label:<26} {n:>4} match(es)   {sel}")

        links = await page.evaluate(JS_COLLECT_LINKS)
        print(f"  {ok(bool(links))} link harvester            {len(links):>4} listing(s)")

        await page.screenshot(path=str(out / "diagnose-search.png"), full_page=False)

        if not links:
            print(f"\n  Screenshot: {out / 'diagnose-search.png'}")
            print("  No listings found — check the screenshot for a CAPTCHA or a "
                  "location Google didn't recognise.\n")
            await browser.close()
            return 1

        # ---------------- detail page ----------------
        await page.goto(links[0]["url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)

        print(f"\nDetail page — {links[0]['name'] or '(unnamed)'}")
        for sel, label in PROBES[2:]:
            n = await page.locator(sel).count()
            print(f"  {ok(n > 0)} {label:<26} {n:>4} match(es)   {sel}")

        data = await page.evaluate(JS_EXTRACT_PLACE)
        print("\nExtracted record")
        for k in ("name", "category", "address", "phone", "website", "rating", "reviews"):
            v = data.get(k)
            print(f"  {ok(v not in (None, '', 0))} {k:<10} {v!r}")

        (out / "diagnose-place.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(out / "diagnose-place.png"), full_page=False)

        print(f"\nSaved for inspection:")
        print(f"  {out / 'diagnose-search.png'}")
        print(f"  {out / 'diagnose-place.png'}")
        print(f"  {out / 'diagnose-place.html'}\n")

        await browser.close()

    broken = [k for k in ("name", "address") if not data.get(k)]
    if broken:
        print(f"\033[31mCore fields missing: {broken}. "
              f"Patch JS_EXTRACT_PLACE in leadfinder/scraper.py.\033[0m\n")
        return 1
    print("\033[32mCore selectors are healthy.\033[0m\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
