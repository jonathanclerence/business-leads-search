"""Offline tests for the parts that break silently: DOM extraction, dedupe,
CSV shape, and the HTTP surface.

These run against local HTML fixtures that mirror Google Maps' actual DOM
(the accessibility attributes Google keeps stable), so they can run in CI with
no network and no Google quota.

    python tests/test_extraction.py
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from leadfinder.exporters import to_csv_string  # noqa: E402
from leadfinder.models import CSV_HEADERS, Business, SearchRequest  # noqa: E402
from leadfinder.scraper import (  # noqa: E402
    JS_COLLECT_LINKS,
    JS_EXTRACT_PLACE,
    _clean_phone,
    _extract_place_id,
    build_search_url,
    dedupe,
)

FIX = Path(__file__).parent / "fixtures"
PASS, FAIL = [], []


def check(label: str, got, want) -> None:
    if got == want:
        PASS.append(label)
        print(f"  \033[32m✓\033[0m {label}")
    else:
        FAIL.append(label)
        print(f"  \033[31m✗\033[0m {label}\n      got:  {got!r}\n      want: {want!r}")


# ---------------------------------------------------------------- pure python
def test_pure() -> None:
    print("\nPure-python helpers")
    check("place id from hex url",
          _extract_place_id("https://www.google.com/maps/place/X/data=!4m5!3m4!1s0x6b12:0x9f8e!8m2"),
          "0x6b12:0x9f8e")
    check("place id absent", _extract_place_id("https://www.google.com/maps"), "")
    check("phone keeps digits", _clean_phone("  +61 2 9000 1234 "), "+61 2 9000 1234")
    check("phone strips bidi marks", _clean_phone("‪0412 555 888‬"), "0412 555 888")
    check("phone rejects text", _clean_phone("Add phone number"), "")

    check("search url encodes slash",
          build_search_url("a/c repair in Sydney"),
          "https://www.google.com/maps/search/a%2Fc+repair+in+Sydney?hl=en&gl=us&authuser=0")

    check("query joins location",
          SearchRequest(query="a/c repair", location="Sydney, Australia").full_query,
          "a/c repair in Sydney, Australia")
    check("query avoids duplicating location",
          SearchRequest(query="dentists in Sydney", location="Sydney").full_query,
          "dentists in Sydney")

    a = Business(name="X", address="1 A St", place_id="pid1")
    b = Business(name="X", address="1 A St", place_id="pid1")
    c = Business(name="X", address="1 A St")           # no id
    d = Business(name="x", address="1 a st.")          # same, differently cased
    check("dedupe by place id", len(dedupe([a, b])), 1)
    check("dedupe by name+address fallback", len(dedupe([c, d])), 1)
    check("distinct businesses survive",
          len(dedupe([a, Business(name="Y", address="2 B St", place_id="pid2")])), 2)

    check("has_website false on empty", Business(name="X").has_website, False)
    check("has_website false on whitespace", Business(name="X", website="  ").has_website, False)
    check("has_website true", Business(name="X", website="https://a.com").has_website, True)


# -------------------------------------------------------------------- csv
def test_csv() -> None:
    print("\nCSV export")
    items = [
        Business(name="Cool Air", address="12 Kent St", phone="+61 2 9000 1234",
                 website="https://coolair.com.au", rating=4.7, reviews=1284,
                 category="AC repair", maps_url="https://maps.google/x"),
        Business(name='Bob "Chill" Aircon, Ltd', address="5/88 George St", phone="0412 555 888"),
    ]
    text = to_csv_string(items)
    parsed = list(csv.reader(io.StringIO(text)))
    check("header row", parsed[0], CSV_HEADERS)
    check("website flag yes", parsed[1][4], "Yes")
    check("website flag no", parsed[2][4], "No")
    check("missing website is N/A", parsed[2][5], "N/A")
    check("commas and quotes survive round-trip", parsed[2][0], 'Bob "Chill" Aircon, Ltd')
    check("rating column", parsed[1][6], "4.7")
    check("column count", len(parsed[1]), len(CSV_HEADERS))
    check("crlf line endings (Excel)", text.count("\r\n"), 3)

    # Round-trip through the dict shape the browser POSTs back.
    dict_rows = [i.to_dict() for i in items]
    check("export accepts dict rows", list(csv.reader(io.StringIO(to_csv_string(dict_rows))))[1][0], "Cool Air")


# -------------------------------------------------------------------- DOM
async def test_dom() -> None:
    from playwright.async_api import async_playwright

    from leadfinder.config import settings

    print("\nDOM extraction (local fixtures mirroring Google Maps markup)")
    launch: dict = {"headless": True}
    if settings.CHROMIUM_PATH:
        launch["executable_path"] = settings.CHROMIUM_PATH

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch)
        page = await browser.new_page()

        # --- full place page ---
        await page.goto((FIX / "place_with_site.html").as_uri())
        d = await page.evaluate(JS_EXTRACT_PLACE)
        check("name", d["name"], "Cool Air Sydney")
        check("address strips 'Address:' prefix", d["address"], "12 Kent St, Sydney NSW 2000, Australia")
        check("phone from data-item-id", d["phone"], "+61 2 9000 1234")
        check("website href", d["website"], "https://coolairsydney.com.au/")
        check("category", d["category"], "Air conditioning repair service")
        check("rating", d["rating"], 4.7)
        check("review count strips comma", d["reviews"], 1284)

        # --- no website / no rating ---
        await page.goto((FIX / "place_no_site.html").as_uri())
        d = await page.evaluate(JS_EXTRACT_PLACE)
        check("name unescapes entities", d["name"], "Bob's Aircon & Refrigeration")
        check("address without inner div", d["address"], "5/88 George St, Parramatta NSW 2150")
        check("phone without +", d["phone"], "0412 555 888")
        check("website empty when absent", d["website"], "")
        check("rating None when unrated", d["rating"], None)

        # --- google.com must never count as "has a website" ---
        await page.goto((FIX / "place_google_site.html").as_uri())
        d = await page.evaluate(JS_EXTRACT_PLACE)
        check("google.com rejected as website", d["website"], "")
        check("comma decimal rating parsed", d["rating"], 3.9)

        # --- feed link harvesting ---
        await page.goto((FIX / "feed.html").as_uri())
        links = await page.evaluate(JS_COLLECT_LINKS)
        check("harvests place links only", len(links), 2)
        check("card name from aria-label", links[0]["name"], "Cool Air Sydney")
        check("detects website button on card", links[0]["cardHasWebsite"], True)
        check("no website button on second card", links[1]["cardHasWebsite"], False)
        check("all links are place urls",
              all("/maps/place/" in l["url"] for l in links), True)

        await browser.close()


# ------------------------------------------------------------------- HTTP
def test_http() -> None:
    from fastapi.testclient import TestClient

    import app as app_module

    print("\nHTTP endpoints")
    client = TestClient(app_module.app)

    check("health", client.get("/api/health").json()["ok"], True)
    check("index renders", client.get("/").status_code, 200)
    check("index contains form", "searchForm" in client.get("/").text, True)
    check("config shape", sorted(client.get("/api/config").json().keys()),
          ["concurrency", "headless", "places_api_available", "sheets_available", "version"])

    check("empty query rejected",
          client.post("/api/search", json={"query": "", "location": "x"}).status_code, 422)
    check("max_results ceiling enforced",
          client.post("/api/search", json={"query": "x", "max_results": 9999}).status_code, 422)
    check("bad provider rejected",
          client.post("/api/search", json={"query": "x", "provider": "nope"}).status_code, 422)
    check("places_api without key rejected",
          client.post("/api/search", json={"query": "x", "provider": "places_api"}).status_code, 400)

    check("unknown job 404", client.get("/api/results/deadbeef").status_code, 404)
    check("unknown stream 404", client.get("/api/stream/deadbeef").status_code, 404)
    check("empty export rejected",
          client.post("/api/export/csv", json={"rows": []}).status_code, 400)

    rows = [Business(name="Cool Air", phone="0412", website="https://a.com").to_dict(),
            Business(name="No Site Co").to_dict()]
    r = client.post("/api/export/csv", json={"rows": rows, "filename": "leads"})
    check("csv download status", r.status_code, 200)
    check("csv filename gets .csv", 'filename="leads.csv"' in r.headers["content-disposition"], True)
    check("csv has BOM for Excel", r.content[:3], b"\xef\xbb\xbf")
    check("csv body rows", r.content.decode("utf-8-sig").strip().count("\r\n"), 2)


def main() -> int:
    test_pure()
    test_csv()
    asyncio.run(test_dom())
    test_http()
    print(f"\n{'─' * 60}")
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 60}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
