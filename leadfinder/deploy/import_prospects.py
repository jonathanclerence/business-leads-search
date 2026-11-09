"""Import the curated Australia call list into the local tracker, add-only.

Preview: .venv/bin/python deploy/import_prospects.py
Apply:   .venv/bin/python deploy/import_prospects.py --apply

The source export stays a dated snapshot. Re-running checks the current tracker
and skips existing businesses, regardless of the snapshot's in_pipeline flag.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import db, importer
from pipeline.leads import clean_category, slugify, theme_for


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def plan(source, current):
    keys = {r['key'] for r in current}
    phones = {r['phone'] for r in current if r['phone']}
    places = {r['place_id'] for r in current if r['place_id']}
    slugs = {r['slug'] for r in current}
    result = []
    for r in source:
        pid = r['google_id'] or importer.place_id(r['maps_url'])
        phone = r['phone_e164']
        if r['key'] in keys or phone in phones or (pid and pid in places):
            continue
        assert phone.startswith('+61') and r['name'] and r['state']
        base = slugify(r['name'])
        slug = base
        if slug in slugs:
            slug = f"{base}-{slugify(r['suburb'], 24)}"
        n = 2
        while slug in slugs:
            slug = f'{base}-{n}'
            n += 1
        lead = {c: r[c] for c in importer.SCRAPED if c in r}
        lead.update(slug=slug, key=r['key'], phone=phone,
                    phone_display=r['phone'], place_id=pid,
                    category=clean_category(r['category'], r['kind']),
                    theme=theme_for(r['kind']),
                    notes=(f"Existing web presence at import ({r['website_status']}): {r['website']}"
                           if r['website'] else None))
        assert all(c in lead for c in importer.SCRAPED)
        result.append(lead)
        keys.add(r['key'])
        phones.add(phone)
        if pid:
            places.add(pid)
        slugs.add(slug)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--source', type=Path, default=ROOT / 'exports/australia/au_leads.db')
    args = parser.parse_args()
    if db.DATABASE_URL:
        parser.error('This tool is for the local SQLite tracker; Postgres is not supported.')
    with sqlite3.connect(args.source.resolve().as_uri() + '?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        candidates = [dict(r) for r in source.execute('SELECT * FROM call_list')]
    target = db.DB_PATH.resolve()
    con = sqlite3.connect(target.as_uri() + ('?mode=rw' if args.apply else '?mode=ro'), uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    backup = None
    try:
        if args.apply:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = ROOT / 'batches/snapshots' / f'pipeline-before-prospects-{stamp}.db'
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backup) as snapshot:
                con.backup(snapshot)
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('BEGIN IMMEDIATE')
        before = [dict(r) for r in con.execute('SELECT * FROM leads ORDER BY slug')]
        additions = plan(candidates, before)
        report = {'source': str(args.source), 'source_candidates': len(candidates),
                  'existing_total': len(before), 'additions': len(additions),
                  'skipped_duplicates': len(candidates) - len(additions),
                  'resulting_total': len(before) + len(additions), 'applied': args.apply}
        if args.apply:
            ts = db.now()
            cols = ['slug', 'key'] + importer.SCRAPED + ['notes', 'stage', 'stage_at', 'created_at', 'updated_at']
            con.executemany(f"INSERT INTO leads ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                            [[r[c] for c in cols[:-4]] + ['new', ts, ts, ts] for r in additions])
            con.executemany('INSERT INTO events (slug, at, kind, detail) VALUES (?, ?, ?, ?)',
                            [(r['slug'], ts, 'stage', f"Imported from Australia prospect database; batch {r['batch_id']}")
                             for r in additions])
            old_slugs = {r['slug'] for r in before}
            after = [dict(r) for r in con.execute('SELECT * FROM leads ORDER BY slug')]
            assert digest(before) == digest([r for r in after if r['slug'] in old_slugs]), 'Existing leads changed'
            assert len(after) == report['resulting_total']
            assert all(r['stage'] == 'new' and r['owner'] is None and r['attempts'] == 0
                       for r in after if r['slug'] not in old_slugs)
            assert not plan(candidates, after), 'Repeat import would add duplicates'
            assert con.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            con.commit()
            report.update(backup=str(backup), existing_leads_unchanged=True,
                          repeat_import_additions=0, stage_counts=dict(con.execute('SELECT stage, COUNT(*) FROM leads GROUP BY stage')))
            report_path = backup.with_suffix('.report.json')
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            importer.write_clean_csv(con)
        print(json.dumps(report, indent=2))
    finally:
        con.close()


if __name__ == '__main__':
    main()
