"""Washing the call list against Australia's Do Not Call Register.

The Do Not Call Register Act covers telemarketing calls to Australian numbers
wherever they're made from. A number counts as checked for 30 days after a
wash, so wash before you call and again each month. Business lines can't be
registered, but plenty of sole traders use a personal mobile that is.

Washing needs your own account at donotcall.gov.au (subscription type A is
free for up to 500 numbers a year), so it isn't automatic:

  export()       writes the file to upload: one number per line, as the
                 register wants them (0412345678, 1300123456, 131450)
  load_results() reads the file the register gives back — the full list
                 with an indicator per number — and marks every lead:
                   Y  on the register → "Do not contact" (no calls, preview removed)
                   N  not on it       → fine to call for 30 days
                   I  invalid         → recorded, check the number
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db, publish
from .leads import normalise_phone

VALID_DAYS = 30
WASH_DIR = db.DB_PATH.parent / "dncr"
# Leads you're calling, or about to: they need a wash in the last 30 days.
CALL_STAGES = ("preview_created", "preview_hosted", "contacted", "follow_up", "interested")
CLOSED = ("not_interested", "do_not_contact", "live")
SCOPES = ("calling", "next", "all")


class WashError(ValueError):
    pass


def wash_number(e164: str) -> str:
    """+61412345678 → 0412345678; 1300/1800/13 numbers have no leading 0. "" if not Australian."""
    if not (e164 or "").startswith("+61"):
        return ""
    n = e164[3:]
    return n if n.startswith(("13", "18")) else "0" + n


def fresh_since(today: Optional[date] = None) -> str:
    return ((today or date.today()) - timedelta(days=VALID_DAYS - 1)).isoformat()


def due(con, scope: str = "calling", limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Leads whose number hasn't been washed in the last 30 days.

    calling: leads with a live preview you're working through
    next:    the next `limit` leads `publish` will pick (wash before you publish)
    all:     every open lead
    """
    if scope not in SCOPES:
        raise WashError(f"scope must be one of {', '.join(SCOPES)}")
    stale = "(dncr_at IS NULL OR dncr_at < ?)"
    if scope == "next":
        slugs = publish.select_new(con, [], limit or 100)
        if not slugs:
            return []
        rows = con.execute(f"SELECT slug, phone FROM leads WHERE slug IN ({','.join('?' * len(slugs))}) AND {stale}",
                           slugs + [fresh_since()]).fetchall()
        return [dict(r) for r in rows]
    if scope == "calling":
        where, args = f"stage IN ({','.join('?' * len(CALL_STAGES))})", list(CALL_STAGES)
    else:
        where, args = f"stage NOT IN ({','.join('?' * len(CLOSED))})", list(CLOSED)
    sql = f"SELECT slug, phone FROM leads WHERE {where} AND {stale} ORDER BY score DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in con.execute(sql, args + [fresh_since()])]


def wash_file(con, scope: str = "calling", limit: Optional[int] = None) -> str:
    """The upload file's contents: unique numbers, one per line, CRLF (as the register asks)."""
    numbers = dict.fromkeys(n for n in (wash_number(r["phone"]) for r in due(con, scope, limit)) if n)
    return "".join(f"{n}\r\n" for n in numbers)


def export(scope: str = "calling", limit: Optional[int] = None) -> Path:
    with db.connect() as con:
        text = wash_file(con, scope, limit)
    WASH_DIR.mkdir(parents=True, exist_ok=True)
    # The register only accepts letters, digits and underscores in file names.
    out = WASH_DIR / f"wash_{date.today():%Y%m%d}_{scope}.txt"
    out.write_bytes(text.encode("ascii"))  # keep the CRLFs as written
    return out


_NUMBER = re.compile(r"\+?\d[\d ()\-]{1,16}\d")
_FLAG = re.compile(r"(?<![A-Za-z])([YNI])(?![A-Za-z])", re.I)


def parse_results(text: str, registered_only: bool = False) -> Dict[str, str]:
    """{E.164 number: "Y" | "N" | "I"} from the register's results file.

    Expects the full list with an indicator per number (e.g. "0412345678,Y").
    A file that lists only the registered numbers needs registered_only=True,
    so a file without indicators is never mistaken for "all clear".
    """
    out: Dict[str, str] = {}
    flagged = 0
    for line in text.splitlines():
        # The phone number, not a row number or date that may sit in another column.
        m = next((m for m in _NUMBER.finditer(line) if normalise_phone(m.group()).startswith("+")), None)
        if not m:
            continue  # header or blank line
        number = normalise_phone(m.group())
        if registered_only:
            out[number] = "Y"
            continue
        flag = _FLAG.search(line[:m.start()] + " " + line[m.end():])
        if flag:
            out[number] = flag.group(1).upper()
            flagged += 1
    if out and not registered_only and not flagged:
        raise WashError("No Y/N/I indicators in this file. Download the results as the full list with an "
                        "indicator per number — or, if it only lists numbers that are on the register, "
                        "import it as “registered numbers only”.")
    if not out:
        raise WashError("No phone numbers found in this file.")
    return out


def load_results(text: str, registered_only: bool = False, washed_on: Optional[date] = None,
                 path: Optional[Path] = None) -> Dict[str, Any]:
    results = parse_results(text, registered_only)
    washed = (washed_on or date.today()).isoformat()
    counts = {"Y": 0, "N": 0, "I": 0}
    registered: List[str] = []
    unmatched = 0
    with db.connect(path) as con:
        for number, flag in results.items():
            leads = [r["slug"] for r in con.execute("SELECT slug FROM leads WHERE phone = ?", (number,))]
            if not leads:
                unmatched += 1
                continue
            for slug in leads:
                counts[flag] += 1
                con.execute("UPDATE leads SET dncr = ?, dncr_at = ?, updated_at = ? WHERE slug = ?",
                            (flag, washed, db.now(), slug))
                if flag == "Y":
                    registered.append(slug)
                    db.set_stage(con, slug, "do_not_contact", f"on the Do Not Call Register (washed {washed})")
                elif flag == "I":
                    db.log(con, slug, "dncr", f"Do Not Call Register says the number is invalid (washed {washed})")
    return {"numbers": len(results), "on_register": counts["Y"], "clear": counts["N"], "invalid": counts["I"],
            "unmatched": unmatched, "registered": registered[:50]}
