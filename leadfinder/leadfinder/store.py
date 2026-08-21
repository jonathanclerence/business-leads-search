"""Crash-safe, append-only batch store. No database.

You asked for files rather than a database, and a 500-search sweep runs for
hours — so "files" has to also mean "survives the laptop going to sleep at
hour six". Append-only JSONL gets you both:

* every completed search is one ``fsync``-ed line, so a kill -9 loses at most
  the search that was in flight;
* resume is just "read which query keys are already in ``tasks.jsonl`` and skip
  them" — no schema, no migrations;
* a half-written final line (the classic crash artifact) is skipped on load
  instead of poisoning the file;
* you can ``grep``, ``wc -l``, ``tail -f`` and open any of it in a text editor.

Layout, one directory per batch::

    batches/2026-08-19-victoria-sweep/
      manifest.json    config + live counters (atomic replace, never appended)
      tasks.jsonl      one line per finished search — the resume log
      leads.jsonl      one line per unique business — the data
      leads.csv        regenerated on export; the sales hand-off
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .scoring import apply_score, summarise

# Column order of the sales hand-off CSV. Score first: the whole point is that
# a rep can open this and start dialling from row 2 without sorting anything.
SALES_HEADERS: List[str] = [
    "Score",
    "Grade",
    "Business Name",
    "Phone Number",
    "Category",
    "Full Address",
    "Search Town",
    "Search Business Type",
    "Website Available?",
    "Website URL",
    "Rating",
    "Review Count",
    "Why This Lead",
    "Google Maps URL",
    "Times Seen",
    "Also Found In",
    "First Found",
    # Blank columns for your reps to fill in.
    "Status",
    "Assigned To",
    "Last Contacted",
    "Notes",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen] or "batch"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL file, tolerating a truncated last line from a hard crash."""
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Only ever the final line, and only after an unclean exit.
                continue
    return out


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write-temp-then-rename so the manifest is never observed half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def task_key(town: str, business_type: str) -> str:
    """Stable identity for one search in the cross-product."""
    return f"{(business_type or '').strip().lower()}|{(town or '').strip().lower()}"


def lead_key(lead: Dict[str, Any]) -> str:
    """Global dedupe identity.

    Prefers Google's place id. Falls back to a normalised name+address, which
    matters because the same shop legitimately appears in both
    "pet groomers in Geelong" and "pet groomers in Highton" — Highton is a
    Geelong suburb, and without this your reps ring it twice.
    """
    pid = (lead.get("place_id") or "").strip()
    if pid:
        return f"pid:{pid}"
    norm = re.sub(r"[^a-z0-9]+", "", f"{lead.get('name', '')}{lead.get('address', '')}".lower())
    return f"na:{norm}"


class BatchStore:
    """Append-only store for one batch run."""

    def __init__(self, batch_dir: Path) -> None:
        self.dir = Path(batch_dir)
        self.manifest_path = self.dir / "manifest.json"
        self.tasks_path = self.dir / "tasks.jsonl"
        self.leads_path = self.dir / "leads.jsonl"

        self.manifest: Dict[str, Any] = {}
        self.done_tasks: Dict[str, Dict[str, Any]] = {}
        self.leads: List[Dict[str, Any]] = []
        self._seen: Dict[str, int] = {}  # lead_key -> index into self.leads

        self._tasks_fh = None
        self._leads_fh = None

    # ------------------------------------------------------------- lifecycle
    @classmethod
    def create(cls, root: Path, name: str, config: Dict[str, Any]) -> "BatchStore":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        batch_id = f"{stamp}-{slugify(name)}"
        store = cls(Path(root) / batch_id)
        store.dir.mkdir(parents=True, exist_ok=True)
        store.manifest = {
            "batch_id": batch_id,
            "name": name,
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "status": "created",
            "config": config,
            "counts": {"tasks_total": 0, "tasks_done": 0, "tasks_failed": 0,
                       "leads_total": 0, "leads_no_website": 0, "duplicates": 0},
        }
        store.save_manifest()
        return store

    @classmethod
    def open(cls, batch_dir: Path) -> "BatchStore":
        store = cls(batch_dir)
        store.load()
        return store

    def load(self) -> "BatchStore":
        if self.manifest_path.exists():
            try:
                self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.manifest = {}
        self.manifest.setdefault("batch_id", self.dir.name)
        self.manifest.setdefault("counts", {})

        for row in _read_jsonl(self.tasks_path):
            if row.get("key"):
                self.done_tasks[row["key"]] = row

        # leads.jsonl holds two kinds of line: full lead records, and compact
        # "seen again" markers appended when the same business turns up in a
        # later search. Folding the markers in on load is what makes
        # times_seen survive a crash — an in-memory counter would not, because
        # the lead's own line was written before the re-sighting happened.
        self.leads = []
        self._seen = {}
        sightings: Dict[str, List[str]] = {}
        for row in _read_jsonl(self.leads_path):
            marker = row.get("_seen")
            if marker:
                sightings.setdefault(marker, []).append(row.get("query", ""))
                continue
            key = row.get("_key") or lead_key(row)
            if key in self._seen:
                continue
            self._seen[key] = len(self.leads)
            self.leads.append(row)

        for key, queries in sightings.items():
            idx = self._seen.get(key)
            if idx is None:
                continue
            lead = self.leads[idx]
            lead["times_seen"] = int(lead.get("times_seen", 1)) + len(queries)
            extra = [q for q in queries if q]
            if extra:
                lead["also_found_in"] = sorted(set(lead.get("also_found_in", []) + extra))
        return self

    def open_for_append(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._tasks_fh = self.tasks_path.open("a", encoding="utf-8")
        self._leads_fh = self.leads_path.open("a", encoding="utf-8")

    def close(self) -> None:
        for fh in (self._tasks_fh, self._leads_fh):
            try:
                if fh:
                    fh.flush()
                    os.fsync(fh.fileno())
                    fh.close()
            except Exception:
                pass
        self._tasks_fh = self._leads_fh = None

    def __enter__(self) -> "BatchStore":
        self.open_for_append()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------------------------------------------------- write
    def _append(self, fh, payload: Dict[str, Any]) -> None:
        if fh is None:
            raise RuntimeError("BatchStore is not open for append — use `with store:`")
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())  # the line that makes a crash cost one search

    def is_done(self, town: str, business_type: str) -> bool:
        row = self.done_tasks.get(task_key(town, business_type))
        return bool(row) and row.get("status") == "done"

    def record_task(
        self,
        town: str,
        business_type: str,
        query: str,
        status: str,
        found: int = 0,
        new_leads: int = 0,
        error: str = "",
        seconds: float = 0.0,
    ) -> None:
        row = {
            "key": task_key(town, business_type),
            "town": town,
            "business_type": business_type,
            "query": query,
            "status": status,          # done | failed | blocked | skipped
            "found": found,
            "new_leads": new_leads,
            "duplicates": max(0, found - new_leads),
            "error": error,
            "seconds": round(seconds, 1),
            "at": utcnow(),
        }
        self.done_tasks[row["key"]] = row
        self._append(self._tasks_fh, row)

    def add_leads(
        self,
        businesses: Iterable[Dict[str, Any]],
        town: str,
        business_type: str,
    ) -> int:
        """Append only leads we've never seen in this batch. Returns how many
        were new. Re-sightings bump ``times_seen`` in memory (and are written
        on the next manifest save) rather than duplicating a row."""
        new = 0
        query = f"{business_type} in {town}"
        for biz in businesses:
            lead = dict(biz)
            key = lead_key(lead)
            if key in self._seen:
                existing = self.leads[self._seen[key]]
                existing["times_seen"] = int(existing.get("times_seen", 1)) + 1
                existing["also_found_in"] = sorted(
                    set(existing.get("also_found_in", []) + [query])
                )
                # Persist the re-sighting as its own line rather than rewriting
                # the lead — this file is append-only by design.
                self._append(self._leads_fh, {"_seen": key, "query": query, "at": utcnow()})
                continue
            lead["_key"] = key
            lead["search_town"] = town
            lead["search_business_type"] = business_type
            lead["times_seen"] = 1
            lead["first_found"] = utcnow()
            apply_score(lead)
            self._seen[key] = len(self.leads)
            self.leads.append(lead)
            self._append(self._leads_fh, lead)
            new += 1
        return new

    # ------------------------------------------------------------- manifest
    def refresh_counts(self) -> Dict[str, Any]:
        done = [t for t in self.done_tasks.values() if t.get("status") == "done"]
        failed = [t for t in self.done_tasks.values() if t.get("status") in ("failed", "blocked")]
        counts = {
            "tasks_total": int(self.manifest.get("counts", {}).get("tasks_total", 0)),
            "tasks_done": len(done),
            "tasks_failed": len(failed),
            "leads_total": len(self.leads),
            "leads_no_website": sum(1 for l in self.leads if not l.get("has_website")),
            "duplicates": sum(int(t.get("duplicates", 0)) for t in self.done_tasks.values()),
            "grades": summarise(self.leads),
        }
        self.manifest["counts"] = counts
        return counts

    def save_manifest(self, **updates: Any) -> None:
        self.manifest.update(updates)
        self.manifest["updated_at"] = utcnow()
        _atomic_write_json(self.manifest_path, self.manifest)

    def checkpoint(self, **updates: Any) -> None:
        self.refresh_counts()
        self.save_manifest(**updates)

    # ---------------------------------------------------------------- export
    def filtered(
        self,
        no_website_only: bool = False,
        min_score: int = 0,
        grades: Optional[List[str]] = None,
        towns: Optional[List[str]] = None,
        business_types: Optional[List[str]] = None,
        require_phone: bool = False,
    ) -> List[Dict[str, Any]]:
        out = []
        gset = {g.lower() for g in grades} if grades else None
        tset = {t.lower() for t in towns} if towns else None
        bset = {b.lower() for b in business_types} if business_types else None
        for lead in self.leads:
            if no_website_only and lead.get("has_website"):
                continue
            if require_phone and not (lead.get("phone") or "").strip():
                continue
            if int(lead.get("score", 0)) < min_score:
                continue
            if gset and (lead.get("grade") or "").lower() not in gset:
                continue
            if tset and (lead.get("search_town") or "").lower() not in tset:
                continue
            if bset and (lead.get("search_business_type") or "").lower() not in bset:
                continue
            out.append(lead)
        out.sort(key=lambda l: (-int(l.get("score", 0)), -(l.get("reviews") or 0),
                                (l.get("name") or "").lower()))
        return out

    @staticmethod
    def to_sales_row(lead: Dict[str, Any]) -> List[Any]:
        return [
            lead.get("score", ""),
            lead.get("grade", ""),
            lead.get("name", ""),
            lead.get("phone", ""),
            lead.get("category", ""),
            lead.get("address", ""),
            lead.get("search_town", ""),
            lead.get("search_business_type", ""),
            "Yes" if lead.get("has_website") else "No",
            lead.get("website") or "N/A",
            lead.get("rating") if lead.get("rating") is not None else "",
            lead.get("reviews") if lead.get("reviews") is not None else "",
            lead.get("why", ""),
            lead.get("maps_url", ""),
            lead.get("times_seen", 1),
            "; ".join(lead.get("also_found_in", [])[:5]),
            (lead.get("first_found") or "")[:10],
            "New",   # Status — your reps overwrite this
            "",      # Assigned To
            "",      # Last Contacted
            "",      # Notes
        ]

    def export_csv(self, path: Optional[Path] = None, **filters: Any) -> Path:
        rows = self.filtered(**filters)
        path = Path(path) if path else (self.dir / "leads.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig + CRLF so Excel opens accented names correctly on a
        # double-click, and Sheets imports it without a dialog fight.
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, lineterminator="\r\n")
            w.writerow(SALES_HEADERS)
            for lead in rows:
                w.writerow(self.to_sales_row(lead))
        return path

    def export_csv_string(self, **filters: Any) -> str:
        import io

        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(SALES_HEADERS)
        for lead in self.filtered(**filters):
            w.writerow(self.to_sales_row(lead))
        return buf.getvalue()

    # ------------------------------------------------------------- reporting
    def summary(self) -> Dict[str, Any]:
        counts = self.refresh_counts()
        by_town: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for lead in self.leads:
            if lead.get("has_website"):
                continue
            by_town[lead.get("search_town", "?")] = by_town.get(lead.get("search_town", "?"), 0) + 1
            bt = lead.get("search_business_type", "?")
            by_type[bt] = by_type.get(bt, 0) + 1
        return {
            "batch_id": self.manifest.get("batch_id"),
            "name": self.manifest.get("name"),
            "status": self.manifest.get("status"),
            "created_at": self.manifest.get("created_at"),
            "updated_at": self.manifest.get("updated_at"),
            "counts": counts,
            "top_towns": sorted(by_town.items(), key=lambda kv: -kv[1])[:15],
            "top_types": sorted(by_type.items(), key=lambda kv: -kv[1])[:15],
        }


def list_batches(root: Path) -> List[Dict[str, Any]]:
    """Newest first. Cheap — reads manifests only, not the JSONL bodies."""
    root = Path(root)
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir() or not (d / "manifest.json").exists():
            continue
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "batch_id": m.get("batch_id", d.name),
            "name": m.get("name", d.name),
            "status": m.get("status", "unknown"),
            "created_at": m.get("created_at", ""),
            "updated_at": m.get("updated_at", ""),
            "counts": m.get("counts", {}),
            "dir": str(d),
        })
    return out
