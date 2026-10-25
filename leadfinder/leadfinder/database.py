"""Batches → one Australia-wide lead database: SQLite plus CSVs for the reps.

    python batch_cli.py database <batch> [<batch> …] -o exports/australia

Keeps every business with a phone and no website of its own (none, a social
page, a directory or booking link, or a dead link; see websites.py) plus the
ones on a free-builder subdomain, which are listed separately as upgrade
leads. Merges the same business across batches (same Google place, or same
phone), re-scores everything with the current scoring, and marks the leads the
sales tracker (batches/pipeline.db) already has, so the CSV is only new
businesses. The tracker is opened read-only and never written.

Writes into the output folder:

    au_leads.db               every kept lead, one table `leads`
    au-no-website-leads.csv   new no-website leads, best first: the call list
    au-weak-website-leads.csv new leads on a free Wix/Square/GoDaddy subdomain
    by-state/<STATE>.csv      the call list split by state
    summary.json              counts by state, grade, trade and website status
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import geo, websites
from .batch import in_country
from .scoring import score_lead
from .store import BatchStore

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DB = ROOT / "batches" / "pipeline.db"

COLUMNS = [
    ("key", "TEXT PRIMARY KEY"), ("name", "TEXT"), ("category", "TEXT"), ("kind", "TEXT"),
    ("blue_collar", "INTEGER"), ("phone", "TEXT"), ("phone_e164", "TEXT"), ("mobile", "INTEGER"),
    ("website", "TEXT"), ("website_status", "TEXT"), ("address", "TEXT"), ("suburb", "TEXT"),
    ("state", "TEXT"), ("postcode", "TEXT"), ("region", "TEXT"), ("lat", "REAL"), ("lng", "REAL"),
    ("service_area", "INTEGER"), ("rating", "REAL"), ("reviews", "INTEGER"), ("claimed", "INTEGER"),
    ("has_hours", "INTEGER"), ("score", "INTEGER"), ("grade", "TEXT"), ("why", "TEXT"),
    ("maps_url", "TEXT"), ("google_id", "TEXT"), ("search_town", "TEXT"), ("search_type", "TEXT"),
    ("times_seen", "INTEGER"), ("branches", "INTEGER"), ("chain", "INTEGER"), ("batch_id", "TEXT"),
    ("first_found", "TEXT"), ("in_pipeline", "INTEGER"), ("pipeline_stage", "TEXT"),
]

CSV_HEADERS = [
    "Score", "Grade", "Business Name", "Phone", "Mobile?", "Category", "Trade", "Website Status",
    "Website / Page", "Suburb", "State", "Postcode", "Region", "Address", "Rating", "Reviews",
    "Listing Claimed?", "Why This Lead", "Google Maps URL", "Search Town", "Search Business Type",
]

_AU_TAIL = re.compile(r"(?:^|,\s*)([^,]*?)\s+(VIC|NSW|QLD|SA|WA|TAS|ACT|NT)\s+(\d{4})\b")


def _parse_suburb(address: str) -> Tuple[str, str, str]:
    a = re.sub(r",?\s*Australia\s*$", "", address or "")
    m = None
    for m in _AU_TAIL.finditer(a):
        pass
    return (m.group(1).strip(), m.group(2), m.group(3)) if m else ("", "", "")


def _town_regions() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for f in sorted((ROOT / "data").glob("towns_*.csv")):
        for row in csv.reader(f.read_text(encoding="utf-8-sig").splitlines()):
            if len(row) >= 2 and row[0] and not row[0].startswith("#") and row[0].lower() != "town":
                out.setdefault(row[0].strip().lower(), row[1].strip())
    return out


def _pipeline_index(path: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """place id → stage and phone → stage for every lead already in the tracker."""
    by_pid: Dict[str, str] = {}
    by_phone: Dict[str, str] = {}
    if not path.exists():
        return by_pid, by_phone
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for key, place_id, phone, stage in con.execute("SELECT key, place_id, phone, stage FROM leads"):
            for k in (key or "", place_id or ""):
                if k.startswith("pid:"):
                    k = k[4:]
                if k:
                    by_pid[k] = stage
            if phone:
                by_phone[phone] = stage
    finally:
        con.close()
    return by_pid, by_phone


def _google_id(lead: Dict[str, Any]) -> str:
    if lead.get("google_id"):
        return lead["google_id"]
    m = re.search(r"!19s(ChIJ[\w-]+)", lead.get("maps_url") or "")
    return m.group(1) if m else ""


def normalise(lead: Dict[str, Any], batch_id: str, regions: Dict[str, str]) -> Optional[Dict[str, Any]]:
    # The sales pipeline's own helpers, so phones, trades and chains match the tracker exactly.
    from pipeline.content import KIND_GROUPS
    from pipeline.leads import classify, display_phone, is_chain, is_mobile, normalise_phone

    phone = normalise_phone(lead.get("phone") or "")
    if not phone.startswith("+61"):
        return None
    status = websites.classify(lead.get("website") or "")
    if status not in websites.NO_SITE and status != "builder":
        return None
    if lead.get("closed") == "permanently":
        return None
    if not in_country(lead, "Australia") or not geo.in_australia(lead.get("lat"), lead.get("lng")):
        return None
    name = (lead.get("name") or "").strip()
    if not name:
        return None

    address = re.sub(r",?\s*Australia\s*$", "", (lead.get("address") or "").strip())
    suburb, state, postcode = lead.get("suburb") or "", lead.get("state") or "", lead.get("postcode") or ""
    if not state:
        suburb, state, postcode = _parse_suburb(address)
    town = (lead.get("search_town") or "").strip()
    region = ""
    if lead.get("lat") is not None and lead.get("lng") is not None:
        near = geo.nearest(lead["lat"], lead["lng"])
        region = near["region"] if near else ""
    region = region or regions.get(town.lower(), "")
    if not state and "," in town:
        # A pin miles from any town and no address: the state that was searched.
        state = town.split(",", 1)[1].split()[0].upper()
    elif not state:
        state = "VIC"  # the 2026 Victoria sweep searched bare town names

    search_type = lead.get("search_business_type") or lead.get("search_type") or ""
    kind = classify(lead.get("category") or "", search_type, name)
    scored = score_lead(lead)
    return {
        "key": f"pid:{lead['place_id']}" if lead.get("place_id") else f"tel:{phone}",
        "name": name,
        "category": lead.get("category") or "",
        "kind": kind,
        "blue_collar": 1 if kind in KIND_GROUPS["blue-collar"] else 0,
        "phone": display_phone(phone),
        "phone_e164": phone,
        "mobile": 1 if is_mobile(phone) else 0,
        "website": lead.get("website") or "",
        "website_status": status,
        "address": address,
        "suburb": suburb or town.split(",")[0],
        "state": state,
        "postcode": postcode,
        "region": region,
        "lat": lead.get("lat"),
        "lng": lead.get("lng"),
        "service_area": 1 if lead.get("service_area") else 0,
        "rating": lead.get("rating"),
        "reviews": lead.get("reviews"),
        "claimed": None if lead.get("claimed") is None else int(bool(lead["claimed"])),
        "has_hours": None if lead.get("has_hours") is None else int(bool(lead["has_hours"])),
        "score": scored["score"],
        "grade": scored["grade"],
        "why": scored["why"],
        "maps_url": lead.get("maps_url") or "",
        "google_id": _google_id(lead),
        "search_town": town,
        "search_type": search_type,
        "times_seen": int(lead.get("times_seen") or 1),
        "branches": 1,
        "chain": 1 if is_chain(name) else 0,
        "batch_id": batch_id,
        "first_found": (lead.get("first_found") or "")[:19],
        "in_pipeline": 0,
        "pipeline_stage": "",
    }


def merge(leads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per business: same place id or same phone number = same lead."""
    by_key: Dict[str, Dict[str, Any]] = {}
    by_phone: Dict[str, str] = {}
    for lead in leads:
        key = by_phone.get(lead["phone_e164"], lead["key"])
        best = by_key.get(key)
        if best is None:
            by_key[lead["key"]] = lead
            by_phone.setdefault(lead["phone_e164"], lead["key"])
            continue
        seen = best["times_seen"] + lead["times_seen"]
        if lead["score"] > best["score"]:
            lead = dict(lead, key=best["key"])
            by_key[best["key"]] = lead
        by_key[best["key"]]["times_seen"] = seen
    return list(by_key.values())


def build(batch_dirs: List[Path], out_dir: Path, pipeline_db: Path = PIPELINE_DB,
          log=print) -> Dict[str, Any]:
    from pipeline.leads import business_key

    regions = _town_regions()
    rows: List[Dict[str, Any]] = []
    read = 0
    for d in batch_dirs:
        store = BatchStore.open(d)
        bid = store.manifest.get("batch_id", d.name)
        for lead in store.leads:
            read += 1
            n = normalise(lead, bid, regions)
            if n:
                rows.append(n)
        log(f"  {bid}: {len(store.leads):,} businesses read")
    leads = merge(rows)

    # Several locations under one name: a franchise or a business with a head
    # office (and usually a website there).
    names = Counter(business_key(l["name"], l["suburb"]) for l in leads)
    for l in leads:
        l["branches"] = names[business_key(l["name"], l["suburb"])]

    by_pid, by_phone = _pipeline_index(pipeline_db)
    for l in leads:
        pid = l["key"][4:] if l["key"].startswith("pid:") else ""
        stage = by_pid.get(pid) or by_pid.get(l["google_id"]) or by_phone.get(l["phone_e164"])
        if stage:
            l["in_pipeline"], l["pipeline_stage"] = 1, stage

    leads.sort(key=lambda l: (-l["score"], -(l["reviews"] or 0), l["name"].lower()))

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "au_leads.db"
    tmp = db_path.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    cols = [c for c, _ in COLUMNS]
    con.execute(f"CREATE TABLE leads ({', '.join(f'{c} {t}' for c, t in COLUMNS)})")
    con.executemany(f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    [[l[c] for c in cols] for l in leads])
    for c in ("state", "score", "kind", "website_status", "in_pipeline"):
        con.execute(f"CREATE INDEX leads_{c} ON leads({c})")
    con.execute("""CREATE VIEW call_list AS
        SELECT * FROM leads
        WHERE in_pipeline = 0 AND chain = 0 AND branches < 3
          AND website_status IN ('none', 'social', 'directory', 'booking', 'dead')
        ORDER BY score DESC, reviews DESC""")
    con.commit()
    con.close()
    tmp.replace(db_path)

    def callable_(l: Dict[str, Any]) -> bool:
        return not l["in_pipeline"] and not l["chain"] and l["branches"] < 3

    call_list = [l for l in leads if callable_(l) and l["website_status"] in websites.NO_SITE]
    weak = [l for l in leads if callable_(l) and l["website_status"] == "builder"]

    def write(path: Path, items: List[Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel opens it cleanly
            w = csv.writer(fh, lineterminator="\r\n")
            w.writerow(CSV_HEADERS)
            for l in items:
                w.writerow([
                    l["score"], l["grade"], l["name"], l["phone"], "Yes" if l["mobile"] else "No",
                    l["category"], l["kind"], websites.LABELS[l["website_status"]], l["website"],
                    l["suburb"], l["state"], l["postcode"], l["region"], l["address"],
                    l["rating"] if l["rating"] is not None else "",
                    l["reviews"] if l["reviews"] is not None else "",
                    {1: "Yes", 0: "No"}.get(l["claimed"], ""), l["why"], l["maps_url"],
                    l["search_town"], l["search_type"],
                ])

    write(out_dir / "au-no-website-leads.csv", call_list)
    write(out_dir / "au-weak-website-leads.csv", weak)
    states = sorted({l["state"] for l in call_list if l["state"]})
    for st in states:
        write(out_dir / "by-state" / f"{st}.csv", [l for l in call_list if l["state"] == st])

    summary = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "batches": [str(d.name) for d in batch_dirs],
        "businesses_read": read,
        "kept": len(leads),
        "already_in_pipeline": sum(l["in_pipeline"] for l in leads),
        "chains_or_multi_branch": sum(1 for l in leads if l["chain"] or l["branches"] >= 3),
        "call_list": len(call_list),
        "weak_website": len(weak),
        "call_list_by_state": dict(Counter(l["state"] for l in call_list).most_common()),
        "call_list_by_grade": dict(Counter(l["grade"] for l in call_list).most_common()),
        "call_list_by_website_status": dict(Counter(l["website_status"] for l in call_list).most_common()),
        "call_list_mobile": sum(l["mobile"] for l in call_list),
        "call_list_blue_collar": sum(l["blue_collar"] for l in call_list),
        "call_list_by_trade": dict(Counter(l["kind"] for l in call_list).most_common(40)),
        "files": {"db": str(db_path), "csv": str(out_dir / "au-no-website-leads.csv")},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
