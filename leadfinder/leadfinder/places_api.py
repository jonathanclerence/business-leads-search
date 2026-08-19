"""Google Places API (New) provider — the reliable, TOS-clean alternative.

Setup
-----
1. https://console.cloud.google.com → create/select a project.
2. APIs & Services → Library → enable **"Places API (New)"**.
   (Note: the *old* "Places API" is a different product. You want the New one.)
3. APIs & Services → Credentials → Create credentials → API key.
4. Put it in `.env` as ``GOOGLE_MAPS_API_KEY=AIza...``.
5. Restrict the key to the Places API. Since this key is used **server-side**,
   use an IP restriction, not an HTTP-referrer restriction.

Billing is required, but Google includes a monthly free credit that covers a
lot of searching. Text Search (Pro SKU, the field set we request) is billed
per request, not per result.

Limits
------
``places:searchText`` returns at most 20 results per page and 3 pages total,
so **60 results is the hard ceiling per query**. To go past that, split the
search geographically ("a/c repair in Bondi", "…in Parramatta", …) or use the
Playwright provider.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import httpx

from .config import settings
from .models import Business
from .scraper import dedupe

ProgressFn = Callable[[str, dict], Awaitable[None]]

SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"

# Only pay for the fields we actually render. A wildcard field mask is the
# fastest way to run up a Google bill.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.primaryTypeDisplayName",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)

MAX_PAGE_SIZE = 20
MAX_PAGES = 3  # Google's hard cap → 60 results.


class PlacesAPIError(RuntimeError):
    pass


def _to_business(p: dict) -> Business:
    return Business(
        name=(p.get("displayName") or {}).get("text", "") or "",
        category=(p.get("primaryTypeDisplayName") or {}).get("text", "") or "",
        address=p.get("formattedAddress", "") or "",
        phone=p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber") or "",
        website=p.get("websiteUri", "") or "",
        rating=p.get("rating"),
        reviews=p.get("userRatingCount"),
        maps_url=p.get("googleMapsUri", "") or "",
        place_id=p.get("id", "") or "",
    )


async def search_places(
    full_query: str,
    max_results: int = 20,
    on_progress: ProgressFn | None = None,
    api_key: str | None = None,
) -> list[Business]:
    key = api_key or settings.GOOGLE_MAPS_API_KEY
    if not key:
        raise PlacesAPIError(
            "No GOOGLE_MAPS_API_KEY configured. Add it to .env, or switch the "
            "engine to the Playwright scraper (which needs no key)."
        )

    async def emit(event: str, **data):
        if on_progress:
            await on_progress(event, data)

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    results: list[Business] = []
    page_token: str | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page_no in range(MAX_PAGES):
            if len(results) >= max_results:
                break

            body: dict = {
                "textQuery": full_query,
                "pageSize": min(MAX_PAGE_SIZE, max_results - len(results)),
                "languageCode": settings.HL,
            }
            if page_token:
                body["pageToken"] = page_token

            await emit(
                "status",
                message=f"Places API — requesting page {page_no + 1}…",
                found=len(results),
                target=max_results,
            )

            resp = await client.post(SEARCH_TEXT_URL, headers=headers, json=body)
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except Exception:
                    detail = resp.text[:300]
                raise PlacesAPIError(
                    f"Places API returned {resp.status_code}: {detail or 'unknown error'}"
                )

            payload = resp.json()
            places = payload.get("places", []) or []
            for p in places:
                results.append(_to_business(p))
                await emit(
                    "progress",
                    processed=len(results),
                    target=max_results,
                    found=len(results),
                    item=results[-1].to_dict(),
                    message=f"Fetched {len(results)} businesses…",
                )

            page_token = payload.get("nextPageToken")
            if not page_token or not places:
                break
            # Google needs a beat before a page token becomes valid.
            await asyncio.sleep(2.0)

    return dedupe(results)[:max_results]
