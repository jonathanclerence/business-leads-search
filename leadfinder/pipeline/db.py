"""The tracker's database: one SQLite file next to the batches.

`leads` holds one row per business (scraped facts + where it is in the sales
pipeline). `events` is the history: every stage change, call and note, so you
can always see what happened and when.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parent.parent
# PIPELINE_DB points everything (CLI, tracker, publish) at another database —
# use it for experiments so the real pipeline is never touched.
DB_PATH = Path(os.getenv("PIPELINE_DB", str(ROOT / "batches" / "pipeline.db")))

# The sales pipeline, in order. The UI shows them left to right.
STAGES = [
    ("new", "New"),
    ("preview_created", "Preview created"),
    ("preview_hosted", "Preview live"),
    ("contacted", "Contacted"),
    ("follow_up", "Follow up"),
    ("interested", "Interested"),
    ("invoice_sent", "Invoice sent"),
    ("paid", "Payment received"),
    ("domain_selected", "Domain chosen"),
    ("site_hosted", "Site hosted"),
    ("live", "Website live"),
    ("not_interested", "Not interested"),
    ("do_not_contact", "Do not contact"),
]
STAGE_KEYS = [k for k, _ in STAGES]
STAGE_LABELS = dict(STAGES)
# A preview page exists on dunous.com for leads in these stages; anything else
# (not published yet, said no, asked us to stop, or has their own site now)
# is removed on the next publish.
PREVIEW_STAGES = {"preview_created", "preview_hosted", "contacted", "follow_up", "interested",
                  "invoice_sent", "paid", "domain_selected", "site_hosted"}

CALL_OUTCOMES = {
    "no_answer": "No answer",
    "voicemail": "Left voicemail",
    "gatekeeper": "Spoke to staff",
    "owner": "Spoke to owner",
    "sms": "Sent SMS",
    "email": "Sent email",
    "wrong_number": "Wrong number",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    slug          TEXT PRIMARY KEY,
    key           TEXT UNIQUE NOT NULL,   -- Google place id, else phone
    name          TEXT NOT NULL,
    category      TEXT,
    kind          TEXT,
    theme         TEXT,
    address       TEXT,
    suburb        TEXT,
    state         TEXT,
    postcode      TEXT,
    region        TEXT,
    phone         TEXT,                   -- E.164
    phone_display TEXT,
    mobile        INTEGER DEFAULT 0,
    rating        REAL,
    reviews       INTEGER,
    score         INTEGER,
    grade         TEXT,
    why           TEXT,
    maps_url      TEXT,
    place_id      TEXT,
    search_town   TEXT,
    search_type   TEXT,
    batch_id      TEXT,
    first_found   TEXT,

    stage         TEXT NOT NULL DEFAULT 'new',
    stage_at      TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_contact  TEXT,
    follow_up     TEXT,                   -- YYYY-MM-DD
    contact_name  TEXT,
    email         TEXT,
    price_quoted  INTEGER,
    price_agreed  INTEGER,
    domain        TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS leads_score ON leads(score DESC);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    slug    TEXT NOT NULL REFERENCES leads(slug),
    at      TEXT NOT NULL,
    kind    TEXT NOT NULL,                -- stage | call | note | edit | publish
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS events_slug ON events(slug, at);
"""

# Fields the tracker UI may edit directly.
EDITABLE = {"follow_up", "contact_name", "email", "price_quoted", "price_agreed", "domain", "notes"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def log(con: sqlite3.Connection, slug: str, kind: str, detail: str = "") -> None:
    con.execute("INSERT INTO events (slug, at, kind, detail) VALUES (?, ?, ?, ?)",
                (slug, now(), kind, detail))


def set_stage(con: sqlite3.Connection, slug: str, stage: str, note: str = "") -> bool:
    if stage not in STAGE_LABELS:
        raise ValueError(f"unknown stage {stage!r}")
    row = con.execute("SELECT stage FROM leads WHERE slug = ?", (slug,)).fetchone()
    if not row or row["stage"] == stage:
        return False
    ts = now()
    con.execute("UPDATE leads SET stage = ?, stage_at = ?, updated_at = ? WHERE slug = ?",
                (stage, ts, ts, slug))
    detail = f"{STAGE_LABELS[row['stage']]} → {STAGE_LABELS[stage]}"
    log(con, slug, "stage", f"{detail} — {note}" if note else detail)
    return True


def advance(con: sqlite3.Connection, slug: str, stage: str, note: str = "") -> bool:
    """Move forward to `stage` only if the lead is currently behind it."""
    row = con.execute("SELECT stage FROM leads WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return False
    order = STAGE_KEYS.index
    current = row["stage"]
    if current in ("not_interested", "do_not_contact") or order(current) >= order(stage):
        return False
    return set_stage(con, slug, stage, note)


def get(con: sqlite3.Connection, slug: str) -> Optional[Dict[str, Any]]:
    row = con.execute("SELECT * FROM leads WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def history(con: sqlite3.Connection, slug: str) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT at, kind, detail FROM events WHERE slug = ? ORDER BY id DESC",
                       (slug,)).fetchall()
    return [dict(r) for r in rows]


def stage_counts(con: sqlite3.Connection) -> Dict[str, int]:
    counts = {k: 0 for k in STAGE_KEYS}
    for r in con.execute("SELECT stage, COUNT(*) n FROM leads GROUP BY stage"):
        counts[r["stage"]] = r["n"]
    return counts
