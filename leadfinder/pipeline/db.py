"""The tracker's database.

`leads` holds one row per business (scraped facts + where it is in the sales
pipeline). `events` is the history: every stage change, call and note, so you
can always see what happened and when.

Two homes for the same tables:
  Postgres (DATABASE_URL, e.g. Neon) — the shared database the team's tracker
    on Vercel uses. Put the same URL in .env on your Mac and the CLI (import,
    enrich, publish, Do Not Call Register…) works on the same data.
  SQLite (batches/pipeline.db) — when DATABASE_URL isn't set, and always for
    tests and experiments (PIPELINE_DB), so they never touch the real pipeline.

The rest of the pipeline writes SQLite-flavoured SQL ("?" placeholders and
all); on Postgres it's translated on the way through (`_pg_sql`).
"""

from __future__ import annotations

import atexit
import functools
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from . import config  # noqa: F401 — loads .env, where DATABASE_URL lives

ROOT = Path(__file__).resolve().parent.parent
# PIPELINE_DB points everything (CLI, tracker, publish) at another database —
# use it for experiments so the real pipeline is never touched.
DB_PATH = Path(os.getenv("PIPELINE_DB", str(ROOT / "batches" / "pipeline.db")))
DATABASE_URL = "" if os.getenv("PIPELINE_DB") else os.getenv("DATABASE_URL", "").strip()

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
    detail  TEXT,
    actor   TEXT                          -- username of who did it (NULL = the pipeline)
);
CREATE INDEX IF NOT EXISTS events_slug ON events(slug, at);
CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,             -- what they sign in with
    name       TEXT NOT NULL,                -- shown in the tracker and history
    role       TEXT NOT NULL DEFAULT 'rep',  -- rep | admin
    pw_hash    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Stages a sales rep may move their lead to. The rest are set by the pipeline
# itself (previews, payments) or by an admin (domain, hosting, live).
REP_STAGES = {"contacted", "follow_up", "interested", "invoice_sent", "not_interested", "do_not_contact"}
CLOSED_STAGES = ("not_interested", "do_not_contact", "live")

# Fields the tracker UI may edit directly.
EDITABLE = {"follow_up", "contact_name", "email", "price_quoted", "price_agreed", "domain", "notes",
            "accent", "type_style", "paper", "corners"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect(path: Optional[Path] = None) -> Iterator[Any]:
    """A connection that commits when the block ends (rolls back on an error).
    Postgres when DATABASE_URL is set, unless you ask for a SQLite file by path."""
    if DATABASE_URL and path is None:
        with _pg_connect() as con:
            yield con
        return
    if config.CLOUD:  # Vercel's disk is read-only and forgets everything between requests
        raise RuntimeError("Set DATABASE_URL in the Vercel project (the shared Postgres database).")
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    _migrate(con)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# Columns added after the first release; created on demand so old databases upgrade.
LATE_COLUMNS = {
    "hours_json": "TEXT",      # [["Monday", "9 am–5 pm"], …] from the Google Maps place page
    "reviews_json": "TEXT",    # [{"text": "...", "author": "Sam", "stars": 5}, …] short snippets
    "enriched_at": "TEXT",
    "accent": "TEXT",          # client's chosen colour, e.g. "#2f6f62" (else the theme's)
    "type_style": "TEXT",      # "serif" | "grotesk" | "sans" (else the theme's)
    "paper": "TEXT",           # "light" | "warm" | "dark" (else the theme's)
    "corners": "TEXT",         # "sharp" | "soft" | "round" (default round)
    "dncr": "TEXT",            # Do Not Call Register wash: "Y" on it | "N" not | "I" invalid
    "dncr_at": "TEXT",         # date of that wash (YYYY-MM-DD); good for 30 days
    "owner": "TEXT",           # username of the rep it belongs to (NULL = anyone can take it)
    "working_since": "TEXT",   # set while the owner is working it; a rep has at most one
}


# One lead at a time: the database itself refuses a second one per rep.
ONE_AT_A_TIME = "CREATE UNIQUE INDEX IF NOT EXISTS leads_working ON leads(owner) WHERE working_since IS NOT NULL"


def _migrate(con: sqlite3.Connection) -> None:
    have = {r["name"] for r in con.execute("PRAGMA table_info(leads)")}
    for col, kind in LATE_COLUMNS.items():
        if col not in have:
            con.execute(f"ALTER TABLE leads ADD COLUMN {col} {kind}")
    events = {r["name"] for r in con.execute("PRAGMA table_info(events)")}
    if "by" in events:  # its first name, but BY is a reserved word in Postgres
        con.execute('ALTER TABLE events RENAME COLUMN "by" TO actor')
    elif "actor" not in events:
        con.execute("ALTER TABLE events ADD COLUMN actor TEXT")
    con.execute(ONE_AT_A_TIME)


# ---- Postgres ---------------------------------------------------------------

try:
    import psycopg
    IntegrityError: tuple = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:  # SQLite only (psycopg is in requirements.txt for the shared database)
    IntegrityError = (sqlite3.IntegrityError,)

_POOL = None
_PG_READY = False


class Row(dict):
    """Like sqlite3.Row: row["name"] and row[0] both work, and dict(row) is a plain dict."""
    __slots__ = ("_values",)

    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)

    def __iter__(self):  # values, as sqlite3.Row: tuple(row) and `a, b = row` work the same
        return iter(self._values)


def _rows(cursor):
    names = [c.name for c in cursor.description or ()]
    return lambda values: Row(names, values)


@functools.lru_cache(maxsize=1024)
def _pg_sql(sql: str, with_params: bool) -> str:
    """SQLite-flavoured SQL → Postgres: ? placeholders, case-insensitive LIKE (as
    SQLite's is), blanks last when sorting high-to-low (as SQLite does), and
    "today in Melbourne"."""
    if with_params:
        sql = sql.replace("%", "%%").replace("?", "%s")
    sql = sql.replace("date('now', '+11 hours')", "to_char(now() AT TIME ZONE 'Australia/Melbourne', 'YYYY-MM-DD')")
    sql = re.sub(r"\bLIKE\b", "ILIKE", sql)
    return re.sub(r"\bDESC\b", "DESC NULLS LAST", sql)


class _Pg:
    """The few sqlite3 connection methods the pipeline uses, on a psycopg connection."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params=()):
        params = list(params) if params else None
        return self.raw.execute(_pg_sql(sql, params is not None), params)

    def executemany(self, sql: str, rows):
        cur = self.raw.cursor()
        cur.executemany(_pg_sql(sql, True), rows)
        return cur


def _pg_schema() -> List[str]:
    ddl = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace(" REAL,", " DOUBLE PRECISION,")
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    statements += [f"ALTER TABLE leads ADD COLUMN IF NOT EXISTS {c} {k}" for c, k in LATE_COLUMNS.items()]
    return statements + ["ALTER TABLE events ADD COLUMN IF NOT EXISTS actor TEXT", ONE_AT_A_TIME]


@contextmanager
def _pg_connect() -> Iterator[_Pg]:
    global _POOL, _PG_READY
    if _POOL is None:
        from psycopg_pool import ConnectionPool
        # A few connections kept open per process: Vercel reuses warm instances,
        # so most requests skip the TLS handshake. prepare_threshold=None because
        # Neon's pooled endpoint (PgBouncer) shares server connections.
        _POOL = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=True, check=ConnectionPool.check_connection,
                               kwargs={"prepare_threshold": None, "row_factory": _rows})
        atexit.register(_POOL.close)
    with _POOL.connection() as raw:   # commits at the end of the block, rolls back on an error
        if not _PG_READY:
            for statement in _pg_schema():
                raw.execute(statement)
            raw.commit()
            _PG_READY = True
        yield _Pg(raw)


def log(con, slug: str, kind: str, detail: str = "", by: str = "") -> None:
    """`by` is the username of whoever did it (blank for the pipeline itself)."""
    con.execute("INSERT INTO events (slug, at, kind, detail, actor) VALUES (?, ?, ?, ?, ?)",
                (slug, now(), kind, detail, by or None))


def set_stage(con: sqlite3.Connection, slug: str, stage: str, note: str = "", by: str = "") -> bool:
    if stage not in STAGE_LABELS:
        raise ValueError(f"unknown stage {stage!r}")
    row = con.execute("SELECT stage FROM leads WHERE slug = ?", (slug,)).fetchone()
    if not row or row["stage"] == stage:
        return False
    ts = now()
    con.execute("UPDATE leads SET stage = ?, stage_at = ?, updated_at = ? WHERE slug = ?",
                (stage, ts, ts, slug))
    detail = f"{STAGE_LABELS[row['stage']]} → {STAGE_LABELS[stage]}"
    log(con, slug, "stage", f"{detail} — {note}" if note else detail, by)
    return True


def advance(con: sqlite3.Connection, slug: str, stage: str, note: str = "", by: str = "") -> bool:
    """Move forward to `stage` only if the lead is currently behind it."""
    row = con.execute("SELECT stage FROM leads WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return False
    order = STAGE_KEYS.index
    current = row["stage"]
    if current in ("not_interested", "do_not_contact") or order(current) >= order(stage):
        return False
    return set_stage(con, slug, stage, note, by)


def get(con: sqlite3.Connection, slug: str) -> Optional[Dict[str, Any]]:
    row = con.execute("SELECT * FROM leads WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def history(con: sqlite3.Connection, slug: str) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT e.at, e.kind, e.detail, COALESCE(u.name, e.actor) AS who FROM events e "
                       "LEFT JOIN users u ON u.username = e.actor WHERE e.slug = ? ORDER BY e.id DESC", (slug,)).fetchall()
    return [dict(r) for r in rows]


# ---- Who's working what -----------------------------------------------------
# A rep takes ("claims") a lead and it becomes theirs: nobody else sees it in
# their list. While they're working it they can't see or take another; once
# they've logged a call or moved its stage they mark it done and pick the next.
# It stays theirs afterwards, so call-backs come back to the same person.

class ClaimError(Exception):
    pass


def working(con: sqlite3.Connection, username: str) -> Optional[Dict[str, Any]]:
    row = con.execute("SELECT * FROM leads WHERE owner = ? AND working_since IS NOT NULL", (username,)).fetchone()
    return dict(row) if row else None


def claim(con: sqlite3.Connection, slug: str, username: str, name: str, open_sql: str) -> None:
    """Make `slug` the rep's current lead. `open_sql` is the condition an unowned lead must meet."""
    current = working(con, username)
    if current:
        if current["slug"] == slug:
            return
        raise ClaimError(f"Finish {current['name']} first — mark it done, then take the next one.")
    ts = now()
    try:
        cur = con.execute(f"UPDATE leads SET owner = ?, working_since = ?, updated_at = ? WHERE slug = ? "
                          f"AND ((owner IS NULL AND {open_sql}) OR (owner = ? AND stage NOT IN {CLOSED_STAGES}))",
                          (username, ts, ts, slug, username))
    except IntegrityError:   # took another one in a second tab a moment ago
        raise ClaimError("You're already working on another lead.")
    if not cur.rowcount:
        raise ClaimError("Someone else just took that one — pick another.")
    log(con, slug, "claim", f"Taken by {name}", username)


def finish(con: sqlite3.Connection, slug: str, username: str, name: str) -> None:
    """The rep is done with their current lead; it stays theirs."""
    row = con.execute("SELECT working_since FROM leads WHERE slug = ? AND owner = ? AND working_since IS NOT NULL",
                      (slug, username)).fetchone()
    if not row:
        raise ClaimError("That isn't the lead you're working on.")
    acted = con.execute("SELECT COUNT(*) FROM events WHERE slug = ? AND actor = ? AND at >= ? AND kind IN ('call', 'stage')",
                        (slug, username, row["working_since"])).fetchone()[0]
    if not acted:
        raise ClaimError("Log the call (or change the stage) before marking it done.")
    con.execute("UPDATE leads SET working_since = NULL, updated_at = ? WHERE slug = ?", (now(), slug))
    log(con, slug, "claim", f"Done for now — {name}", username)


def assign(con: sqlite3.Connection, slug: str, username: Optional[str], by: str) -> None:
    """Admin: give a lead to a rep (they'll find it under My leads), or back to everyone (None).
    `by` is the admin's username."""
    if username:
        user = con.execute("SELECT name FROM users WHERE username = ?", (username,)).fetchone()
        if not user:
            raise ClaimError(f"No user {username!r}")
    row = con.execute("SELECT owner FROM leads WHERE slug = ?", (slug,)).fetchone()
    if not row or row["owner"] == username:
        return
    con.execute("UPDATE leads SET owner = ?, working_since = NULL, updated_at = ? WHERE slug = ?",
                (username, now(), slug))
    log(con, slug, "claim", f"Assigned to {user['name']}" if username else "Back in the pool for anyone", by)


def stage_counts(con: sqlite3.Connection) -> Dict[str, int]:
    counts = {k: 0 for k in STAGE_KEYS}
    for r in con.execute("SELECT stage, COUNT(*) n FROM leads GROUP BY stage"):
        counts[r["stage"]] = r["n"]
    return counts
