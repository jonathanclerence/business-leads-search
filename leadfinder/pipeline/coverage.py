"""Which towns × business types have been searched, by region — so you know
what's done and where to scrape next. Reads every batch's tasks.jsonl and the
town lists in data/towns_*.csv."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from . import db

ROOT = db.ROOT
DATA = ROOT / "data"
BATCHES = ROOT / "batches"


def _towns() -> Dict[str, Dict[str, str]]:
    """town (lower) → {town, region, state, file}."""
    out: Dict[str, Dict[str, str]] = {}
    for f in sorted(DATA.glob("towns_*.csv")):
        state = f.stem.replace("towns_", "").replace("_", " ").title()
        for row in csv.reader(f.read_text(encoding="utf-8-sig").splitlines()):
            if not row or not row[0].strip() or row[0].startswith("#") or row[0].lower() == "town":
                continue
            out.setdefault(row[0].strip().lower(), {
                "town": row[0].strip(), "region": (row[1].strip() if len(row) > 1 else "") or "Other",
                "state": state, "file": f.name})
    return out


def _types() -> List[str]:
    f = DATA / "business_types.csv"
    if not f.exists():
        return []
    rows = [r for r in csv.reader(f.read_text(encoding="utf-8-sig").splitlines()) if r and r[0].strip()]
    return [r[0].strip() for r in rows[1:] if not r[0].startswith("#")]


def _tasks() -> Dict[str, Dict[str, Any]]:
    """Latest status per "type|town" across every batch."""
    latest: Dict[str, Dict[str, Any]] = {}
    for f in sorted(BATCHES.glob("*/tasks.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = t.get("key") or f"{t.get('business_type', '').lower()}|{t.get('town', '').lower()}"
            if latest.get(key, {}).get("status") != "done":
                latest[key] = t
    return latest


def coverage() -> Dict[str, Any]:
    towns, types, tasks = _towns(), _types(), _tasks()
    done_by_town: Dict[str, set] = defaultdict(set)
    failed_by_town: Dict[str, set] = defaultdict(set)
    for t in tasks.values():
        town = (t.get("town") or "").strip().lower()
        (done_by_town if t.get("status") == "done" else failed_by_town)[town].add(
            (t.get("business_type") or "").lower())

    with db.connect() as con:
        leads_by_region = {r["region"] or "Other": r["n"]
                           for r in con.execute("SELECT region, COUNT(*) n FROM leads GROUP BY region")}

    regions: Dict[str, Dict[str, Any]] = {}
    for key, info in towns.items():
        r = regions.setdefault(info["region"], {"region": info["region"], "state": info["state"],
                                                "towns": 0, "towns_done": 0, "towns_partial": 0,
                                                "searches_done": 0, "searches_failed": 0,
                                                "todo": [], "leads": leads_by_region.get(info["region"], 0)})
        r["towns"] += 1
        n_done = len(done_by_town.get(key, ()))
        r["searches_done"] += n_done
        r["searches_failed"] += len(failed_by_town.get(key, set()) - done_by_town.get(key, set()))
        if types and n_done >= len(types):
            r["towns_done"] += 1
        elif n_done:
            r["towns_partial"] += 1
        else:
            r["todo"].append(info["town"])

    extra = sorted(t for t in done_by_town if t and t not in towns)
    rows = sorted(regions.values(), key=lambda r: (r["state"], r["region"]))
    for r in rows:
        total = r["towns"] * max(1, len(types))
        r["percent"] = round(100 * r["searches_done"] / total) if total else 0
    return {"types": len(types), "regions": rows, "searched_elsewhere": extra,
            "searches_done": sum(len(v) for v in done_by_town.values())}
