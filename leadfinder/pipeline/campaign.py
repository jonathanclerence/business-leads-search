"""Previews in batches, start to finish.

    python -m pipeline campaign --kind blue-collar --batches 10 --size 100

For each batch: take the next leads `publish` would pick, add their opening
hours and review quotes (enrich), publish them, wait until dunous.com serves
them, then make each one's website pack PDF (exports/docs/<slug>/). Every
step saves as it goes, so a stopped campaign is picked up by running the same
command again: it simply carries on with the next leads.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Sequence

from . import db, documents, publish

Log = Callable[[str], None]


def wait_live(slugs: Sequence[str], log: Log = print, timeout: float = 20 * 60) -> List[str]:
    """Mark previews live as Cloudflare serves them; → the ones still not live at the deadline."""
    missing = list(slugs)
    deadline = time.time() + timeout
    time.sleep(60)  # a deploy never lands sooner
    while missing and time.time() < deadline:
        publish.verify(missing, log=log)
        with db.connect() as con:
            missing = [s for s in missing
                       if con.execute("SELECT stage FROM leads WHERE slug = ?", (s,)).fetchone()[0] == "preview_created"]
        if missing:
            time.sleep(45)
    return missing


def run(kinds: Sequence[str], grades: Sequence[str] = ("Hot", "Warm"), batches: int = 1, size: int = 100,
        enrich_first: bool = True, pace: float = 6.0, log: Log = print) -> List[Dict[str, Any]]:
    report = []
    for n in range(1, batches + 1):
        with db.connect() as con:
            picked = publish.select_new(con, grades, size, kinds=kinds)
            todo = [s for s in picked
                    if not con.execute("SELECT enriched_at FROM leads WHERE slug = ?", (s,)).fetchone()[0]]
        if not picked:
            log("No more leads to publish for these kinds and grades.")
            break
        log(f"── Batch {n}/{batches}: {len(picked)} leads ({len(todo)} to enrich)")
        if enrich_first and todo:
            from .enrich import enrich  # needs the scraper's browser; imported only when used
            got = enrich(todo, log=log, pace=pace)
            if got["blocked"]:
                log(f"Google is blocking lookups: {len(got['skipped'])} previews go out without hours and reviews.")
        res = publish.publish(grades=grades, limit=size, kinds=kinds, log=log)
        if not res["pushed"]:
            log("Nothing was pushed, so the campaign stops here.")
            break
        with db.connect() as con:
            fresh = [s for s in picked if con.execute("SELECT stage FROM leads WHERE slug = ?", (s,)).fetchone()[0]
                     in db.PREVIEW_STAGES]
        missing = wait_live(fresh, log=log)
        with db.connect() as con:
            leads = [db.get(con, s) for s in fresh]
        docs = documents.save_many([("pack", l) for l in leads], log=lambda m: None)
        report.append({"batch": n, "published": len(fresh), "not_live": missing,
                       "packs": len(docs["made"]), "pack_failed": docs["failed"]})
        log(f"── Batch {n}: {len(fresh) - len(missing)}/{len(fresh)} live, {len(docs['made'])} website packs"
            + (f", {len(docs['failed'])} packs failed" if docs["failed"] else ""))
    return report
