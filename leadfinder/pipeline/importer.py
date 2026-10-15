"""batches/*/leads.csv → the clean call list + the tracker database.

Keeps a lead only if it is in Australia, has no website and has a phone
number; merges duplicates (same Google place, or same phone) keeping the best
score. Re-running is safe: scraped facts are refreshed, but a lead's stage,
notes and history are never touched, and its preview URL never changes.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from . import db
from .leads import (classify, clean_category, display_phone, is_australian, is_mobile,
                    normalise_phone, parse_address, place_id, short_address, slugify, theme_for,
                    to_float, to_int)

ROOT = db.ROOT
BATCH_ROOT = ROOT / "batches"
CLEAN_DIR = BATCH_ROOT / "clean"
CLEAN_CSV = CLEAN_DIR / "au-no-website.csv"
TOWN_FILES = ROOT / "data"
PREVIEW_BASE = "https://www.dunous.com/previewsite/"

CLEAN_HEADERS = [
    "Score", "Grade", "Business Name", "Phone", "Mobile?", "Category", "Suburb", "State",
    "Region", "Address", "Rating", "Reviews", "Why This Lead", "Preview URL", "Stage",
    "Google Maps URL", "Search Town", "Search Business Type",
]


def town_regions() -> Dict[str, str]:
    """town (lower-case) → region, from every data/towns_*.csv."""
    out: Dict[str, str] = {}
    for f in sorted(TOWN_FILES.glob("towns_*.csv")):
        for row in csv.reader(f.read_text(encoding="utf-8-sig").splitlines()):
            if len(row) >= 2 and row[0] and not row[0].startswith("#") and row[0].lower() != "town":
                out.setdefault(row[0].strip().lower(), row[1].strip())
    return out


def batch_csvs() -> List[Path]:
    return sorted(p for p in BATCH_ROOT.glob("*/leads.csv") if p.parent.name != "clean")


def read_rows(paths: Iterable[Path]) -> Iterable[Tuple[str, Dict[str, str]]]:
    csv.field_size_limit(10**8)
    for p in paths:
        with p.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                yield p.parent.name, row


def normalise(batch_id: str, row: Dict[str, str], regions: Dict[str, str]) -> Dict[str, Any] | None:
    address = (row.get("Full Address") or "").strip()
    phone = normalise_phone(row.get("Phone Number") or "")
    if not phone or (row.get("Website Available?") or "").strip().lower() != "no":
        return None
    if not is_australian(address, phone):
        return None
    name = (row.get("Business Name") or "").strip()
    if not name:
        return None

    street, suburb, state, postcode = parse_address(address)
    town = (row.get("Search Town") or "").strip()
    kind = classify(row.get("Category", ""), row.get("Search Business Type", ""), name)
    pid = place_id(row.get("Google Maps URL", ""))
    return {
        "key": f"pid:{pid}" if pid else f"tel:{phone}",
        "name": name,
        "category": clean_category(row.get("Category", ""), kind),
        "kind": kind,
        "theme": theme_for(kind),
        "address": short_address(address),
        "suburb": suburb or town,
        "state": state or "VIC",
        "postcode": postcode,
        "region": regions.get(town.lower(), ""),
        "phone": phone,
        "phone_display": display_phone(phone),
        "mobile": 1 if is_mobile(phone) else 0,
        "rating": to_float(row.get("Rating")),
        "reviews": to_int(row.get("Review Count")),
        "score": to_int(row.get("Score")) or 0,
        "grade": (row.get("Grade") or "").strip(),
        "why": (row.get("Why This Lead") or "").strip(),
        "maps_url": (row.get("Google Maps URL") or "").strip(),
        "place_id": pid,
        "search_town": town,
        "search_type": (row.get("Search Business Type") or "").strip(),
        "batch_id": batch_id,
        "first_found": (row.get("First Found") or "").strip(),
    }


def dedupe(leads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per business: same place id or same phone number = same lead."""
    by_key: Dict[str, Dict[str, Any]] = {}
    by_phone: Dict[str, str] = {}
    for lead in leads:
        key = by_phone.get(lead["phone"], lead["key"])
        best = by_key.get(key)
        if best is None or lead["score"] > best["score"]:
            lead = dict(lead, key=best["key"] if best else lead["key"])
            by_key[lead["key"]] = lead
            key = lead["key"]
        by_phone.setdefault(lead["phone"], key)
    return sorted(by_key.values(), key=lambda d: (-d["score"], -(d["reviews"] or 0), d["name"]))


SCRAPED = ["name", "category", "kind", "theme", "address", "suburb", "state", "postcode", "region",
           "phone", "phone_display", "mobile", "rating", "reviews", "score", "grade", "why",
           "maps_url", "place_id", "search_town", "search_type", "batch_id", "first_found"]


def unique_slug(con: sqlite3.Connection, lead: Dict[str, Any]) -> str:
    base = slugify(lead["name"])
    for candidate in (base, f"{base}-{slugify(lead['suburb'], 24)}"):
        if not con.execute("SELECT 1 FROM leads WHERE slug = ?", (candidate,)).fetchone():
            return candidate
    n = 2
    while con.execute("SELECT 1 FROM leads WHERE slug = ?", (f"{base}-{n}",)).fetchone():
        n += 1
    return f"{base}-{n}"


def upsert(con: sqlite3.Connection, leads: List[Dict[str, Any]]) -> Tuple[int, int]:
    added = updated = 0
    ts = db.now()
    for lead in leads:
        row = con.execute("SELECT slug FROM leads WHERE key = ? OR phone = ? LIMIT 1",
                          (lead["key"], lead["phone"])).fetchone()
        if row:
            sets = ", ".join(f"{c} = ?" for c in SCRAPED if c != "name")
            con.execute(f"UPDATE leads SET {sets}, updated_at = ? WHERE slug = ?",
                        [lead[c] for c in SCRAPED if c != "name"] + [ts, row["slug"]])
            updated += 1
            continue
        slug = unique_slug(con, lead)
        cols = ["slug", "key"] + SCRAPED + ["stage", "stage_at", "created_at", "updated_at"]
        vals = [slug, lead["key"]] + [lead[c] for c in SCRAPED] + ["new", ts, ts, ts]
        con.execute(f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        db.log(con, slug, "stage", f"Imported from batch {lead['batch_id']}")
        added += 1
    return added, updated


def write_clean_csv(con: sqlite3.Connection, path: Path = CLEAN_CSV) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = con.execute("SELECT * FROM leads ORDER BY score DESC, reviews DESC, name").fetchall()
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel opens it cleanly
        w = csv.writer(fh)
        w.writerow(CLEAN_HEADERS)
        for r in rows:
            w.writerow([r["score"], r["grade"], r["name"], r["phone_display"],
                        "Yes" if r["mobile"] else "No", r["category"], r["suburb"], r["state"],
                        r["region"], r["address"], r["rating"] if r["rating"] is not None else "",
                        r["reviews"] if r["reviews"] is not None else "", r["why"],
                        PREVIEW_BASE + r["slug"], db.STAGE_LABELS[r["stage"]], r["maps_url"],
                        r["search_town"], r["search_type"]])
    return len(rows)


def run(paths: List[Path] | None = None) -> Dict[str, Any]:
    paths = paths or batch_csvs()
    regions = town_regions()
    raw = 0
    kept: List[Dict[str, Any]] = []
    for batch_id, row in read_rows(paths):
        raw += 1
        lead = normalise(batch_id, row, regions)
        if lead:
            kept.append(lead)
    leads = dedupe(kept)
    with db.connect() as con:
        added, updated = upsert(con, leads)
        total = write_clean_csv(con)
    return {"files": [str(p) for p in paths], "rows_read": raw, "matched": len(kept),
            "unique": len(leads), "added": added, "updated": updated, "tracker_total": total,
            "csv": str(CLEAN_CSV)}
