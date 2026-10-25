"""The single shared record shape. Both the Playwright scraper and the
Places API provider emit exactly this, so the frontend and the exporters
never need to know where the data came from."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from . import websites

# Column order used by the table, the CSV and the Google Sheet.
CSV_HEADERS: list[str] = [
    "Business Name",
    "Category",
    "Full Address",
    "Phone Number",
    "Website Available?",
    "Website URL",
    "Rating",
    "Review Count",
    "Google Maps URL",
]


@dataclass
class Business:
    name: str = ""
    category: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    rating: float | None = None
    reviews: int | None = None
    maps_url: str = ""
    place_id: str = ""

    # Filled by the fast HTTP engine (fastmaps.py), which gets them for free
    # in the search response. The Playwright scraper leaves them empty.
    google_id: str = ""            # ChIJ… place id
    lat: float | None = None
    lng: float | None = None
    suburb: str = ""
    state: str = ""
    postcode: str = ""
    service_area: bool = False     # no street address: works from home / on the road
    claimed: bool | None = None    # the owner has claimed the Google listing
    has_hours: bool | None = None  # opening hours are filled in
    closed: str = ""               # "permanently" / "temporarily" when Google says so
    categories: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers
    @property
    def website_status(self) -> str:
        """none / social / directory / booking / dead / builder / real — see websites.py."""
        return websites.classify(self.website)

    @property
    def has_website(self) -> bool:
        """A site of their own. A Facebook page or a Fresha booking link is not one."""
        return self.website_status not in websites.NO_SITE

    @property
    def dedupe_key(self) -> str:
        """Prefer a real place id; fall back to a normalised name+address."""
        if self.place_id:
            return f"pid:{self.place_id}"
        norm = re.sub(r"[^a-z0-9]+", "", f"{self.name}{self.address}".lower())
        return f"na:{norm}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["has_website"] = self.has_website
        d["website_status"] = self.website_status
        return d

    def to_row(self) -> list[Any]:
        return [
            self.name or "",
            self.category or "",
            self.address or "",
            self.phone or "",
            "Yes" if self.has_website else "No",
            self.website or "N/A",
            self.rating if self.rating is not None else "",
            self.reviews if self.reviews is not None else "",
            self.maps_url or "",
        ]


@dataclass
class SearchRequest:
    query: str
    location: str
    max_results: int = 20
    provider: str = "playwright"  # "playwright" | "places_api"
    only_without_website: bool = False

    @property
    def full_query(self) -> str:
        q = self.query.strip()
        loc = self.location.strip()
        if not loc:
            return q
        if loc.lower() in q.lower():
            return q
        return f"{q} in {loc}"


@dataclass
class JobProgress:
    status: str = "queued"  # queued|running|done|error|cancelled
    message: str = ""
    found: int = 0
    processed: int = 0
    target: int = 0
    error: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
