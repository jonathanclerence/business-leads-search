"""Admin-only Sri Lanka prospect pipeline, physically separate from Australia.

    python -m pipeline.sri_lanka sync       # import new finder results
    python -m pipeline.sri_lanka segment    # tag every lead Tourism/Other + tourism category
    python -m pipeline.sri_lanka pairs      # write the tourism sweep's town × search pairs

Uses the existing batch finder output, but its own geography, phones, ranking,
database, stages and exports. No Australian previews, pricing or call queue.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import auth, config, db, documents, leads as lead_tools, offer

ROOT = config.ROOT
DB_PATH = Path(os.getenv('SRI_LANKA_DB', str(ROOT / 'batches/sri-lanka/pipeline.db')))
STAGES = {'new': 'New', 'preview_created': 'Preview built', 'preview_hosted': 'Preview live',
          'researching': 'Researching', 'contacted': 'Contacted',
          'follow_up': 'Follow up', 'interested': 'Interested', 'proposal': 'Proposal sent',
          'won': 'Won', 'not_interested': 'Not interested', 'do_not_contact': 'Do not contact'}
SECTORS = [
    ('Beauty & bridal', r'beaut|hair|salon|bridal|make.?up|nail|barber|lash|brow|spa'),
    ('Tourism & stays', r'hotel|guest.?house|homestay|villa|lodg|resort|hostel|tour|travel|safari|surf|diving|scuba|whale|holiday|vacation|bed.*breakfast'),
    ('Events & creative', r'photo|video|wedding|event|florist|cater|party|bridal'),
    ('Food & hospitality', r'cafe|café|coffee|restaurant|cake|bakery|bistro|patisser|dessert'),
    ('Fitness & wellness', r'fitness|gym|yoga|pilates|personal train|dance|wellness'),
    ('Retail & lifestyle', r'boutique|clothing|fashion|jewel|dress|apparel'),
    ('Pets', r'pet groom|dog groom|pet board|pet sitter'),
]

# Tourism segment, after the South Coast / Hill Country inspiration brief.
# (category, pattern, anywhere): Google categories are read in order (primary
# first) and the first rule matching one wins. `anywhere` rules are tourism
# wherever the business is; the rest (cafés, spas, gem shops…) count only in a
# tourist town from data/towns_sri_lanka_tourism.csv (not Colombo, the airport
# or the regional hubs, where most such places serve locals).
TOURISM = 'Tourism'
TOURISM_RULES = [
    ('Surf camps & surf schools', r'surf(ing)? ?(school|camp|lesson|coach|club|retreat)|kite ?surf', True),
    ('Surf shops & board rental', r'surf ?shop|surfboard|board rental|shaper|water sports equipment', True),
    ('Hostels & surf hostels', r'hostel|backpacker', True),
    ('Whale watching, boat & lagoon tours', r'whale|dolphin|boat (tour|trip|ride|rental|safari|charter)|lagoon|river safari'
                                            r'|mangrove|canoe|kayak|catamaran|cruise|fishing charter', True),
    ('Diving & snorkelling', r'\bdiv(e|ing)\b|scuba|snorkel', True),
    ('Safari jeep operators', r'safari|\bjeep|wildlife', True),
    ('Tea estate tours & trekking', r'tea (factory|estate|plantation|tour|museum)|\btrek|\bhik(e|ing)|mountaineer'
                                    r'|camp ?site|campground|camping', True),
    ('Cooking classes & local experiences', r'village tour|stilt|turtle|hatchery'
                                            r'|spice garden|herbal garden|elephant|outdoor activit|adventure|rafting'
                                            r'|zip ?line|paraglid|hot air balloon|canyon|tourist attraction', True),
    ('Scooter, tuk-tuk & airport transfers', r'scooter|motor ?bike|motorcycle rental|bicycle rental|bike rental|tuk'
                                             r'|car rental|van rental|vehicle rental|airport|chauffeur|private driver'
                                             r'|tour driver', True),
    ('Yoga, Ayurveda & spas', r'yoga retreat|retreat cent|wellness (hotel|resort|retreat)|ayurved(a|ic) (resort|retreat|hotel)', True),
    ('Resorts & boutique hotels', r'resort|hotel|motel|\binn\b|lodge|lodging|serviced accommodation|glamp', True),
    ('Villas & holiday rentals', r'villa|holiday (home|apartment|rental|house)|vacation|cottage|bungalow|chalet|cabin'
                                 r'|group accommodation|apartment rental|beach house', True),
    ('Guest houses & homestays', r'guest ?house|home ?stay|bed (&|and) breakfast|rest house', True),
    ('Tour operators & travel agents', r'\btour|travel|sightseeing|tourist information|airline ticket', True),
    ('Coworking & coliving', r'co-?working|co-?living', False),
    ('Cooking classes & local experiences', r'cooking (class|school)|culinary', False),
    ('Yoga, Ayurveda & spas', r'yoga|ayurved|meditation|retreat|wellness|\bspa\b|massage|panchakarma', False),
    ('Restaurants & beach clubs', r'restaurant|beach club|\bbar\b|\bpub\b|grill|diner|bistro|eatery|cocktail|brewery'
                                  r'|night ?club', False),
    ('Cafés', r'caf[eé]|coffee|tea house|tea room|juice|smoothie|brunch|ice cream|gelato|dessert', False),
    ('Gem, jewellery & souvenir shops', r'\bgem|moonstone|jewel|souvenir|handicraft|batik|gift shop|art gallery|antique'
                                        r'|\bmasks?\b|tea store|spice (shop|store)', False),
    ('Wedding venues & photographers', r'wedding|banquet|event venue', False),
    ('Tattoo, laundry & traveller services', r'tattoo|laundr|dry clean|currency exchange|money exchange', False),
    ('Scooter, tuk-tuk & airport transfers', r'taxi|transportation service|transfer service', False),
]
TOURISM_CATEGORIES = list(dict.fromkeys(label for label, _, _ in TOURISM_RULES))
# Legacy sector for tourism businesses no SECTORS pattern recognises.
TOURISM_SECTOR = {'Yoga, Ayurveda & spas': 'Fitness & wellness', 'Restaurants & beach clubs': 'Food & hospitality',
                  'Cafés': 'Food & hospitality', 'Gem, jewellery & souvenir shops': 'Retail & lifestyle',
                  'Surf shops & board rental': 'Retail & lifestyle', 'Wedding venues & photographers': 'Events & creative',
                  'Tattoo, laundry & traveller services': 'Retail & lifestyle'}
# Google's catch-all categories: only these fall back to reading the name.
LOCAL_TAGS = {'city', 'airport', 'hub'}
GENERIC_CATEGORIES = {'', 'service establishment', 'store', 'corporate office', 'company', 'business center',
                      'establishment', 'point of interest'}


def tourist_towns() -> dict:
    """Towns from the tourism sweep, keyed like `search_town`, minus Colombo, the airport and regional hubs."""
    path = ROOT / 'data/towns_sri_lanka_tourism.csv'
    if not path.exists():
        return {}
    with path.open(newline='') as f:
        rows = list(csv.DictReader(f))
    return {r['town']: r for r in rows if not LOCAL_TAGS & set((r.get('tags') or '').split())}


ACCOMMODATION = {'Hostels & surf hostels', 'Resorts & boutique hotels', 'Villas & holiday rentals',
                 'Guest houses & homestays'}
TOUR_AGENTS = 'Tour operators & travel agents'
# Specialists (surf, whale, safari, dive, tea…): a "Travel agency" that also
# lists "Wildlife and safari park" is a safari operator.
NICHE_RULES = [r for r in TOURISM_RULES if r[2] and r[0] not in ACCOMMODATION and r[0] != TOUR_AGENTS]
STRICT_RULES = [r for r in TOURISM_RULES if r[2]]


def tourism_segment(categories, name: str = '', search_town: str = '', tourist: Optional[dict] = None):
    """('Tourism', category) when the business serves travellers, else ('Other', '').

    Primary accommodation category wins; then any specialist category; then the
    primary category; then a secondary one that is tourism anywhere. Generic
    tour agencies and catch-all listings are refined by the business name."""
    if isinstance(categories, str):
        categories = [categories]
    cats = [c for c in (categories or []) if c]
    in_tourist_town = search_town in (tourist_towns() if tourist is None else tourist)

    def first(texts, rules):
        for text in texts:
            for label, pattern, anywhere in rules:
                if (anywhere or in_tourist_town) and re.search(pattern, text, re.I):
                    return label
        return ''

    primary = first(cats[:1], TOURISM_RULES)
    if primary in ACCOMMODATION:
        return TOURISM, primary
    label = first(cats, NICHE_RULES) or primary or first(cats[1:], STRICT_RULES)
    if label in ('', TOUR_AGENTS) and (label or all(c.lower() in GENERIC_CATEGORIES for c in cats)):
        label = first([name or ''], NICHE_RULES) or label
    return (TOURISM, label) if label else ('Other', '')


LEAD_COLS = ('id', 'country', 'name', 'category', 'sector', 'industry', 'tourism_category', 'address', 'search_town',
             'search_district', 'search_province', 'phone', 'owner_phone', 'website', 'website_status',
             'maps_url', 'rating', 'reviews', 'score', 'why', 'batch_id', 'found_at',
             'imported_at', 'stage', 'notes', 'contact_name', 'follow_up', 'updated_at',
             'slug', 'code', 'owner', 'attempts', 'last_contact')
CLOSED_STAGES = ('won', 'not_interested', 'do_not_contact')
QUEUE_SQL = ("stage NOT IN ('won', 'not_interested', 'do_not_contact') AND COALESCE(attempts, 0) < 4 "
             "AND (follow_up IS NULL OR follow_up <= date('now', '+5 hours'))")
DUE_SQL = ("follow_up IS NOT NULL AND follow_up <= date('now', '+5 hours') "
           "AND stage NOT IN ('won', 'not_interested', 'do_not_contact')")
MINE_SQL = "owner = ? AND stage NOT IN ('won', 'not_interested', 'do_not_contact')"
CALL_OUTCOMES = {
    'no_answer': 'No answer',
    'voicemail': 'Left voicemail',
    'gatekeeper': 'Spoke to staff',
    'owner': 'Spoke to owner',
    'whatsapp': 'Sent WhatsApp',
    'wrong_number': 'Wrong number',
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
 id TEXT PRIMARY KEY, country TEXT NOT NULL DEFAULT 'LK' CHECK(country='LK'),
 name TEXT NOT NULL, category TEXT, sector TEXT, address TEXT,
 search_town TEXT, search_district TEXT, search_province TEXT,
 phone TEXT NOT NULL UNIQUE CHECK(phone LIKE '+94%'), website TEXT, website_status TEXT,
 maps_url TEXT, rating REAL, reviews INTEGER, score INTEGER, why TEXT,
 batch_id TEXT, found_at TEXT, imported_at TEXT,
 stage TEXT NOT NULL DEFAULT 'new', notes TEXT NOT NULL DEFAULT '',
 contact_name TEXT NOT NULL DEFAULT '', follow_up TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lk_score ON leads(score DESC, reviews DESC);
CREATE INDEX IF NOT EXISTS lk_stage ON leads(stage);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, lead_id TEXT REFERENCES leads(id), at TEXT, detail TEXT
);
"""


def _use_pg() -> bool:
    return bool(db.DATABASE_URL) and not os.getenv('SRI_LANKA_DB')


def _tables():
    return ('lk_leads', 'lk_events') if _use_pg() else ('leads', 'events')


@contextmanager
def connect():
    if _use_pg():
        with db.connect() as con:
            yield con
        return
    if config.CLOUD:
        raise HTTPException(503, 'Set DATABASE_URL in the Vercel project.')
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript(SCHEMA)
    have = {r['name'] for r in con.execute('PRAGMA table_info(leads)')}
    for col, col_type in db.LK_LATE_COLUMNS.items():
        if col not in have:
            con.execute(f'ALTER TABLE leads ADD COLUMN {col} {col_type}')
    ev_have = {r['name'] for r in con.execute('PRAGMA table_info(events)')}
    for col in ('kind', 'actor'):
        if col not in ev_have:
            con.execute(f'ALTER TABLE events ADD COLUMN {col} TEXT')
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS leads_working ON leads(owner) WHERE working_since IS NOT NULL')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def phone_lk(raw):
    phone = re.sub(r'[^\d+]', '', raw or '')
    if phone.startswith('0094'):
        phone = '+' + phone[2:]
    elif re.fullmatch(r'0\d{9}', phone):
        phone = '+94' + phone[1:]
    elif re.fullmatch(r'94\d{9}', phone):
        phone = '+' + phone
    return phone if re.fullmatch(r'\+94\d{9}', phone) else ''


def site_status(url):
    from leadfinder import websites
    host = urlparse(url if '://' in (url or '') else 'https://' + (url or '')).hostname or ''
    for domain in ('booking.com', 'agoda.com', 'airbnb.com', 'tripadvisor.com', 'tripadvisor.co.uk',
                   'tripadvisor.in', 'ikman.lk', 'findglocal.com'):
        if host == domain or host.endswith('.' + domain):
            return 'directory'
    return websites.classify(url)


def towns():
    found = {}
    for name in ('towns_sri_lanka.csv', 'towns_sri_lanka_tourism.csv'):
        path = ROOT / 'data' / name
        if path.exists():
            with path.open(newline='') as f:
                found.update({r['town']: r for r in csv.DictReader(f)})
    return found


def tourism_pairs() -> list:
    """Town × search-term pairs for the tourism sweep: niche searches (surf,
    whale, safari, tea…) only run in towns tagged for them."""
    with (ROOT / 'data/towns_sri_lanka_tourism.csv').open(newline='') as f:
        town_rows = list(csv.DictReader(f))
    with (ROOT / 'data/business_types_sri_lanka_tourism.csv').open(newline='') as f:
        type_rows = [r for r in csv.DictReader(f) if r['type'] and not r['type'].startswith('#')]
    pairs = []
    for t in type_rows:
        where = set(t['where'].split())
        for town in town_rows:
            tags = set((town.get('tags') or '').split())
            if 'all' in where or ('tourist' in where and not LOCAL_TAGS & tags) or where & tags:
                pairs.append({'town': town['town'], 'business_type': t['type']})
    return pairs


def candidate(raw, batch_id, areas, tourist: Optional[dict] = None):
    from leadfinder import websites
    from leadfinder.batch import in_country
    phone = phone_lk(raw.get('phone'))
    if not phone or not in_country(dict(raw, phone=phone), 'Sri Lanka') or raw.get('closed'):
        return None
    # A Sri Lankan phone plus address or a local map pin: never infer country
    # merely from the town that was searched.
    if raw.get('lat') is None and raw.get('lng') is None and 'sri lanka' not in (raw.get('address') or '').lower():
        return None
    status = site_status(raw.get('website') or '')
    if status not in websites.NO_SITE:
        return None
    categories = raw.get('categories') or [raw.get('category') or '']
    category = ' '.join(categories)
    sector = next((label for label, pattern in SECTORS if re.search(pattern, category, re.I)), None)
    industry, tourism_category = tourism_segment(categories, raw.get('name') or '', raw.get('search_town') or '', tourist)
    if industry == TOURISM:  # e.g. "Coworking space" would otherwise read as a spa
        sector = TOURISM_SECTOR.get(tourism_category, 'Tourism & stays')
    if not sector or not raw.get('name'):
        return None
    area = areas.get(raw.get('search_town'), {})
    reviews, rating = int(raw.get('reviews') or 0), float(raw.get('rating') or 0)
    score = 40 + (20 if status in ('social', 'booking', 'directory') else 8)
    score += 15 if reviews >= 50 else 10 if reviews >= 10 else 5 if reviews else 0
    score += 5 if rating >= 4 else 0
    score += 5 if raw.get('claimed') else 0
    score += 5 if raw.get('has_hours') else 0
    score += 10  # verified +94 phone format; not a claim that it was dialled
    why = [(f'Tourism · {tourism_category}' if industry == TOURISM else sector) + ': visual portfolio, enquiries or bookings fit',
           websites.LABELS[status]]
    if status == 'social':
        why.append('Already using a social page as its website link')
    if reviews:
        why.append(f'{reviews} Google reviews')
    if raw.get('claimed'):
        why.append('Claimed Google listing')
    return dict(id='lk:' + (raw.get('place_id') or raw.get('google_id') or phone), country='LK',
                name=raw['name'], category=raw.get('category') or '', sector=sector,
                industry=industry, tourism_category=tourism_category, address=raw.get('address') or '', search_town=raw.get('search_town') or '',
                search_district=area.get('district', ''), search_province=area.get('province', ''),
                phone=phone, website=raw.get('website') or '', website_status=status,
                maps_url=raw.get('maps_url') or '', rating=raw.get('rating'), reviews=reviews,
                score=score, why=' · '.join(why), batch_id=batch_id, found_at=raw.get('first_found') or '')


def batches():
    found = []
    for p in sorted((ROOT / 'batches').glob('*/manifest.json')):
        data = json.loads(p.read_text())
        if data.get('config', {}).get('country', '').lower() == 'sri lanka':
            found.append((p.parent, data))
    return found


def sync(tourism_only: bool = True):
    """Add new finder results. The Sri Lanka pipeline is tourism-focused, so by
    default only Tourism businesses come in; older non-tourism leads stay."""
    from leadfinder.store import BatchStore
    areas, tourist, scanned, eligible = towns(), tourist_towns(), 0, 0
    tbl, ev_tbl = _tables()
    with connect() as con:
        known_ids = {r[0] for r in con.execute(f'SELECT id FROM {tbl}')}
        known_phones = {r[0] for r in con.execute(f'SELECT phone FROM {tbl}')}
    # Read and filter everything first, then write in bulk: one short
    # transaction, so the live tracker is never stuck behind a slow import.
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    new = []
    for folder, manifest in batches():
        for raw in BatchStore.open(folder).leads:
            scanned += 1
            lead = candidate(raw, manifest['batch_id'], areas, tourist)
            if not lead or (tourism_only and lead['industry'] != TOURISM):
                continue
            eligible += 1
            if lead['id'] in known_ids or lead['phone'] in known_phones:
                continue
            lead.update(imported_at=ts, updated_at=ts)
            new.append(lead)
            known_ids.add(lead['id'])
            known_phones.add(lead['phone'])
    with connect() as con:
        if new:
            cols = list(new[0])
            con.executemany(f"INSERT INTO {tbl} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                            [[r[c] for c in cols] for r in new])
            con.executemany(f'INSERT INTO {ev_tbl} (lead_id, at, detail) VALUES (?, ?, ?)',
                            [(r['id'], ts, 'Imported as New from Sri Lanka finder') for r in new])
        added = len(new)
        total = con.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
        tourism = con.execute(f'SELECT COUNT(*) FROM {tbl} WHERE industry = ?', (TOURISM,)).fetchone()[0]
    return dict(scanned=scanned, eligible=eligible, added=added, total=total, tourism=tourism)


def segment_all(apply: bool = True) -> dict:
    """Tag every lead Tourism/Other with its tourism category, using the full
    Google category list from the finder batches where we still have it.
    Only `industry` and `tourism_category` are written."""
    from leadfinder.store import BatchStore
    full = {}
    for folder, _ in batches():
        for raw in BatchStore.open(folder).leads:
            cats = raw.get('categories') or [raw.get('category') or '']
            for key in (raw.get('place_id'), raw.get('google_id')):
                if key:
                    full['lk:' + key] = cats
    tourist, tbl = tourist_towns(), _tables()[0]
    with connect() as con:
        rows = [dict(r) for r in con.execute(f'SELECT id, name, category, search_town, industry, tourism_category FROM {tbl}')]
        changes = []
        for r in rows:
            seg = tourism_segment(full.get(r['id']) or [r['category'] or ''], r['name'], r['search_town'] or '', tourist)
            if (r['industry'], r['tourism_category'] or '') != seg:
                changes.append((seg[0], seg[1], r['id']))
        if apply and changes:
            con.executemany(f'UPDATE {tbl} SET industry = ?, tourism_category = ? WHERE id = ?', changes)
        after = {r['id']: (r['industry'], r['tourism_category'] or '') for r in rows}
        after.update({lid: (i, c) for i, c, lid in changes})
        counts = {}
        for industry, cat in after.values():
            counts[cat or industry] = counts.get(cat or industry, 0) + 1
    return dict(total=len(rows), changed=len(changes), applied=apply,
                tourism=sum(1 for i, _ in after.values() if i == TOURISM),
                by_category=dict(sorted(counts.items(), key=lambda kv: -kv[1])))


def display_phone_lk(raw: str) -> str:
    m = re.fullmatch(r'\+94(\d{2})(\d{3})(\d{4})', raw or '')
    return f'0{m.group(1)} {m.group(2)} {m.group(3)}' if m else (raw or '')


def doc_lead(row: dict) -> dict:
    name = row.get('name') or 'Business'
    town = (row.get('search_town') or '').split(',')[0].strip()
    kind = lead_tools.classify(row.get('category') or '', row.get('sector') or '', name)
    slug = row.get('slug') or lead_tools.slugify(f'{name}-{town}' if town else name)
    stem = lead_tools.slugify(name, 30).replace('-', '')
    return {
        **row,
        'country': 'LK',
        'slug': slug,
        'kind': kind,
        'category': lead_tools.clean_category(row.get('category') or '', kind),
        'theme': lead_tools.theme_for(kind),
        'suburb': town,
        'state': row.get('search_district') or '',
        'phone_display': display_phone_lk(row.get('phone') or ''),
        'domain': f'{stem}.lk' if stem else '',
        'preview_url': config.preview_url(slug) if row.get('slug') else '',
    }


def publish_previews(limit: int = 100, push: bool = True, reset_worktree: bool = True, log=print) -> dict:
    """Pick the next `limit` Sri Lanka leads, assign each a unique slug and
    dunous.com preview code, render their personalised preview websites into
    the marketing site worktree alongside the Australian previews, and push."""
    from . import publish as pub

    tbl, ev_tbl = _tables()
    with connect() as con:
        taken_slugs = {r[0] for r in con.execute(f'SELECT slug FROM {tbl} WHERE slug IS NOT NULL')}
        taken_codes = {r[0] for r in con.execute(f'SELECT code FROM {tbl} WHERE code IS NOT NULL')}
        try:
            taken_slugs |= {r[0] for r in con.execute('SELECT slug FROM leads WHERE slug IS NOT NULL')}
            taken_codes |= {r[0] for r in con.execute('SELECT code FROM leads WHERE code IS NOT NULL')}
        except Exception:  # noqa: BLE001
            pass

        active_rows = con.execute(f'SELECT name, search_town FROM {tbl} WHERE slug IS NOT NULL').fetchall()
        seen_keys = {lead_tools.business_key(r['name'], (r['search_town'] or '').split(',')[0]) for r in active_rows}

        candidates = con.execute(
            f"SELECT id, name, category, sector, search_town FROM {tbl} WHERE stage = 'new' AND slug IS NULL ORDER BY (CASE WHEN industry = 'Tourism' THEN 0 ELSE 1 END), score DESC, reviews DESC, id LIMIT ?",
            (limit * 4,),
        ).fetchall()

        picked = []
        for r in candidates:
            row = dict(r)
            town = (row.get('search_town') or '').split(',')[0].strip()
            kind = lead_tools.classify(row.get('category') or '', row.get('sector') or '', row.get('name') or '')
            if kind == 'local' or lead_tools.is_chain(row['name']):
                continue
            bkey = lead_tools.business_key(row['name'], town)
            if bkey in seen_keys:
                continue
            seen_keys.add(bkey)

            base_slug = lead_tools.slugify(f"{row['name']}-{town}" if town else row['name'])
            slug = base_slug
            n = 2
            while slug in taken_slugs:
                slug = f'{base_slug[:42]}-{n}'
                n += 1
            taken_slugs.add(slug)

            code = lead_tools.preview_code(row['name'], taken_codes)
            taken_codes.add(code)
            picked.append((row['id'], slug, code, row['name']))
            if len(picked) >= limit:
                break

        if not picked:
            log('No more eligible Sri Lanka leads to publish.')
            return {'new': 0, 'pushed': False, 'codes': []}

        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        con.executemany(
            f"UPDATE {tbl} SET slug = ?, code = ?, stage = 'preview_hosted', updated_at = ? WHERE id = ?",
            [(slug, code, ts, lid) for lid, slug, code, _ in picked],
        )
        con.executemany(
            f'INSERT INTO {ev_tbl} (lead_id, at, detail) VALUES (?, ?, ?)',
            [(lid, ts, f'Published preview {config.preview_url(slug)} (code: {code})') for lid, slug, code, _ in picked],
        )

        target = pub.prepare_worktree(log) if reset_worktree else config.PUBLISH_WORKTREE
        if reset_worktree:
            pub.refresh_info_pack(log)
        all_leads = pub.active_leads(con) + pub.active_lk_leads(con)
        log(f'Rendering {len(all_leads)} total preview pages (+{len(picked)} new Sri Lanka sites)…')
        stats = pub.write_site_files(target, all_leads)
        msg = f"Sri Lanka previews: +{len(picked)} new ({len(all_leads)} total live)"
        committed = pub.commit_and_push(target, msg, push, log)

    return {
        'new': len(picked),
        **stats,
        'pushed': committed and push,
        'sample': [{'id': lid, 'name': name, 'slug': slug, 'code': code, 'url': config.preview_url(slug)}
                   for lid, slug, code, name in picked[:10]],
    }


router = APIRouter(prefix='/pipeline/sri-lanka', dependencies=[Depends(auth.can_sri_lanka)])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _log_event(con, lead_id: str, kind: str, detail: str, actor: str = '') -> None:
    _, ev_tbl = _tables()
    con.execute(f'INSERT INTO {ev_tbl} (lead_id, at, kind, detail, actor) VALUES (?, ?, ?, ?, ?)',
                (lead_id, _now(), kind, detail, actor or None))


def working(con, username: str) -> Optional[dict]:
    if not username:
        return None
    tbl, _ = _tables()
    row = con.execute(f'SELECT * FROM {tbl} WHERE owner = ? AND working_since IS NOT NULL', (username,)).fetchone()
    return dict(row) if row else None


def _lead_or_404(con, lead_id: str, u: Optional[dict] = None) -> dict:
    tbl, _ = _tables()
    row = con.execute(f'SELECT * FROM {tbl} WHERE id=?', (lead_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'No Sri Lanka lead with that ID')
    lead = dict(row)
    if u and auth.is_rep(u) and not (lead.get('owner') == u['username'] and lead.get('working_since')):
        raise HTTPException(403, 'Take this business first (you can work on one at a time).')
    return lead


def _detail(con, lead_id: str) -> dict:
    tbl, ev_tbl = _tables()
    lead = _lead_or_404(con, lead_id)
    lead['preview_url'] = config.preview_url(lead['slug']) if lead.get('slug') else ''
    evs = con.execute(
        f'SELECT id, at, kind, detail, actor FROM {ev_tbl} WHERE lead_id = ? ORDER BY id DESC LIMIT 30',
        (lead_id,),
    ).fetchall()
    lead['history'] = [dict(e) for e in evs]
    return lead


@router.get('')
def page():
    return FileResponse(Path(__file__).parent / 'ui/sri_lanka.html', headers={'Cache-Control': 'no-store'})


@router.get('/api/meta')
def meta(request: Request):
    tbl, _ = _tables()
    u = auth.user(request)
    rep = auth.is_rep(u)
    uname = u['username'] if u else ''
    with connect() as con:
        counts = {r[0]: r[1] for r in con.execute(f'SELECT stage, COUNT(*) FROM {tbl} GROUP BY stage')}
        districts = [r[0] for r in con.execute(f"SELECT DISTINCT search_district FROM {tbl} WHERE search_district != '' ORDER BY 1")]
        social = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE website_status='social'").fetchone()[0]
        tourism = {r[0]: r[1] for r in con.execute(
            f'SELECT tourism_category, COUNT(*) FROM {tbl} WHERE industry = ? GROUP BY tourism_category', (TOURISM,))}
        previews = con.execute(f'SELECT COUNT(*) FROM {tbl} WHERE slug IS NOT NULL AND code IS NOT NULL').fetchone()[0]
        current = working(con, uname) if uname else None
        available = con.execute(f'SELECT COUNT(*) FROM {tbl} WHERE owner IS NULL AND {QUEUE_SQL}').fetchone()[0]
        mine_count = con.execute(f'SELECT COUNT(*) FROM {tbl} WHERE {MINE_SQL}', (uname,)).fetchone()[0] if uname else 0
        due_clause = (' AND owner = ?', [uname]) if rep else ('', [])
        due = con.execute(f'SELECT COUNT(*) FROM {tbl} WHERE {DUE_SQL}{due_clause[0]}', due_clause[1]).fetchone()[0]
    searches = [dict(id=m['batch_id'], status=m.get('status'), counts=m.get('counts', {}), updated_at=m.get('updated_at')) for _, m in batches()]
    team = [] if rep else [m for m in auth.team() if m['role'] in ('admin', 'lk_rep')]
    return dict(
        total=sum(counts.values()), counts=counts, social=social, previews=previews, stages=STAGES,
        outcomes=CALL_OUTCOMES, available=available, mine=mine_count, follow_ups_due=due,
        working={'id': current['id'], 'name': current['name']} if current else None,
        team=team,
        sectors=[s[0] for s in SECTORS], districts=districts,
        tourism=sum(tourism.values()),
        tourism_categories=[[c, tourism.get(c, 0)] for c in TOURISM_CATEGORIES], searches=searches, cloud=config.CLOUD,
        site_url=config.SITE_URL,
        user={k: u[k] for k in ('username', 'name', 'role')} if u else None,
        offer=dict(
            currency='LKR',
            packages=[dict(p) for p in offer.LK_PACKAGES],
            enterprise=offer.LK_ENTERPRISE,
            hourly_rate=offer.LK_HOURLY_RATE,
            hosting=dict(offer.LK_HOSTING),
        ),
    )


def filters(q='', stage='', sector='', district='', presence='', preview='', owner='', mine=False, due=False, u=None, con=None,
            industry='', tourism_category=''):
    clauses, values = [], []
    if u and auth.is_rep(u):
        current = working(con, u['username']) if con else None
        if current:
            return ' WHERE id = ?', [current['id']]
        clauses.append(MINE_SQL if mine else f'owner IS NULL AND {QUEUE_SQL}')
        if mine:
            values.append(u['username'])
    elif owner == 'none':
        clauses.append('owner IS NULL')
    elif owner:
        clauses.append('owner = ?')
        values.append(owner)
    if due:
        clauses.append(DUE_SQL)
    for col, value in [('stage', stage), ('sector', sector), ('search_district', district), ('website_status', presence),
                       ('tourism_category', tourism_category)]:
        if value:
            clauses.append(col + ' = ?')
            values.append(value)
    if industry == TOURISM:
        clauses.append('industry = ?')
        values.append(TOURISM)
    elif industry == 'Other':
        clauses.append("COALESCE(industry, '') != ?")
        values.append(TOURISM)
    if preview == 'live':
        clauses.append('slug IS NOT NULL AND code IS NOT NULL')
    elif preview == 'none':
        clauses.append('slug IS NULL')
    if q:
        clauses.append('(name LIKE ? OR address LIKE ? OR phone LIKE ? OR code LIKE ? OR contact_name LIKE ?)')
        values += ['%' + q + '%'] * 5
    return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), values


@router.get('/api/leads')
def leads(request: Request, q: str = '', stage: str = '', sector: str = '', district: str = '',
          presence: str = '', preview: str = '', owner: str = '', mine: bool = False, due: bool = False,
          industry: str = '', tourism_category: str = '',
          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    tbl, _ = _tables()
    u = auth.user(request)
    rep = auth.is_rep(u)
    with connect() as con:
        where, args = filters(q, stage, sector, district, presence, preview, owner, mine, due, u, con,
                              industry, tourism_category)
        total = con.execute(f'SELECT COUNT(*) FROM {tbl}' + where, args).fetchone()[0]
        rows = [dict(r) for r in con.execute(
            f'SELECT * FROM {tbl}' + where + " ORDER BY (CASE WHEN slug IS NOT NULL THEN 0 ELSE 1 END), (CASE WHEN industry = 'Tourism' THEN 0 ELSE 1 END), score DESC, reviews DESC, id LIMIT ? OFFSET ?",
            args + [limit, offset],
        )]
    for r in rows:
        r['preview_url'] = config.preview_url(r['slug']) if r.get('slug') else ''
        if rep and not r.get('working_since'):
            r['phone'] = ''
            r['owner_phone'] = ''
    return dict(total=total, leads=rows)


@router.get('/api/leads/{lead_id}')
def get_lead(lead_id: str, request: Request):
    u = auth.user(request)
    with connect() as con:
        _lead_or_404(con, lead_id, u)
        return _detail(con, lead_id)


@router.post('/api/leads/{lead_id}/claim')
def claim_lead(lead_id: str, request: Request):
    """A Sri Lanka rep takes a business: it's theirs and the only one they can see until they log & mark it done."""
    u = auth.user(request)
    if not u or not u.get('username'):
        raise HTTPException(400, 'Sign-in is required to claim a business.')
    tbl, _ = _tables()
    with connect() as con:
        _lead_or_404(con, lead_id)
        current = working(con, u['username'])
        if current:
            if current['id'] == lead_id:
                return _detail(con, lead_id)
            raise HTTPException(409, f"Finish {current['name']} first — log the call and mark it done, then take the next one.")
        ts = _now()
        try:
            cur = con.execute(
                f"UPDATE {tbl} SET owner = ?, working_since = ?, updated_at = ? WHERE id = ? "
                f"AND ((owner IS NULL AND {QUEUE_SQL}) OR (owner = ? AND stage NOT IN ('won', 'not_interested', 'do_not_contact')))",
                (u['username'], ts, ts, lead_id, u['username']),
            )
        except db.IntegrityError:
            raise HTTPException(409, "You're already working on another business.")
        if not cur.rowcount:
            raise HTTPException(409, 'Someone else just took that business — pick another.')
        _log_event(con, lead_id, 'claim', f"Taken by {u['name']}", u['username'])
        return _detail(con, lead_id)


@router.post('/api/leads/{lead_id}/done')
def finish_lead(lead_id: str, request: Request):
    u = auth.user(request)
    tbl, ev_tbl = _tables()
    with connect() as con:
        row = con.execute(
            f'SELECT working_since FROM {tbl} WHERE id = ? AND owner = ? AND working_since IS NOT NULL',
            (lead_id, u['username']),
        ).fetchone()
        if not row:
            raise HTTPException(409, "That isn't the business you're currently working on.")
        acted = con.execute(
            f"SELECT COUNT(*) FROM {ev_tbl} WHERE lead_id = ? AND actor = ? AND at >= ? AND kind IN ('call', 'stage', 'update')",
            (lead_id, u['username'], row['working_since']),
        ).fetchone()[0]
        if not acted:
            raise HTTPException(409, 'Log the call (or update the stage/notes) before marking it done.')
        con.execute(f'UPDATE {tbl} SET working_since = NULL, updated_at = ? WHERE id = ?', (_now(), lead_id))
        _log_event(con, lead_id, 'claim', f"Done for now — {u['name']}", u['username'])
    return {'ok': True}


class CallLogBody(BaseModel):
    outcome: str
    note: str = Field('', max_length=2000)
    follow_up: Optional[date] = None
    contact_name: Optional[str] = Field(None, max_length=200)
    owner_phone: Optional[str] = Field(None, max_length=60)


@router.post('/api/leads/{lead_id}/call')
def log_call(lead_id: str, body: CallLogBody, request: Request):
    u = auth.user(request)
    if body.outcome not in CALL_OUTCOMES:
        raise HTTPException(422, 'Unknown call outcome')
    tbl, _ = _tables()
    with connect() as con:
        lead = _lead_or_404(con, lead_id, u)
        ts = _now()
        updates = {
            'attempts': int(lead.get('attempts') or 0) + 1,
            'last_contact': ts,
            'updated_at': ts,
        }
        if not lead.get('owner') and u.get('username'):
            updates['owner'] = u['username']
        if body.contact_name is not None and body.contact_name.strip():
            updates['contact_name'] = body.contact_name.strip()
        if body.owner_phone is not None and body.owner_phone.strip():
            updates['owner_phone'] = body.owner_phone.strip()
        if body.note.strip():
            existing_notes = (lead.get('notes') or '').strip()
            stamp = ts[:10]
            line = f"[{stamp} · {CALL_OUTCOMES[body.outcome]}] {body.note.strip()}"
            updates['notes'] = f"{line}\n{existing_notes}".strip() if existing_notes else line
        if body.follow_up:
            updates['follow_up'] = body.follow_up.isoformat()
            if lead['stage'] not in ('interested', 'proposal', 'won', 'do_not_contact', 'not_interested'):
                updates['stage'] = 'follow_up'
        elif body.outcome == 'wrong_number':
            updates['stage'] = 'do_not_contact'
        elif body.outcome in ('gatekeeper', 'owner', 'whatsapp', 'voicemail', 'no_answer'):
            if lead['stage'] in ('new', 'preview_created', 'preview_hosted', 'researching'):
                updates['stage'] = 'contacted'
        con.execute(
            f"UPDATE {tbl} SET {', '.join(k + '=?' for k in updates)} WHERE id=?",
            list(updates.values()) + [lead_id],
        )
        detail = CALL_OUTCOMES[body.outcome] + (f' — {body.note.strip()}' if body.note.strip() else '')
        _log_event(con, lead_id, 'call', detail, u.get('username', ''))
        return _detail(con, lead_id)


class OwnerBody(BaseModel):
    owner: Optional[str] = Field(None, max_length=32)


@router.post('/api/leads/{lead_id}/owner', dependencies=[Depends(auth.admin_only)])
def set_owner(lead_id: str, body: OwnerBody, request: Request):
    tbl, _ = _tables()
    u = auth.user(request)
    new_owner = (body.owner or '').strip() or None
    with connect() as con:
        lead = _lead_or_404(con, lead_id)
        owner_label = 'Back in the pool for anyone'
        if new_owner:
            usr = auth.get_user(new_owner)
            if not usr:
                raise HTTPException(400, f'No user {new_owner!r}')
            owner_label = f"Assigned to {usr['name']}"
        if lead.get('owner') != new_owner:
            con.execute(f'UPDATE {tbl} SET owner=?, working_since=NULL, updated_at=? WHERE id=?',
                        (new_owner, _now(), lead_id))
            _log_event(con, lead_id, 'claim', owner_label, u.get('username', ''))
        return _detail(con, lead_id)


@router.get('/api/export.csv', dependencies=[Depends(auth.admin_only)])
def export(q: str = '', stage: str = '', sector: str = '', district: str = '', presence: str = '', preview: str = '', owner: str = '',
           industry: str = '', tourism_category: str = ''):
    tbl, _ = _tables()
    where, args = filters(q, stage, sector, district, presence, preview, owner,
                          industry=industry, tourism_category=tourism_category)
    with connect() as con:
        rows = con.execute(f'SELECT {", ".join(LEAD_COLS)} FROM {tbl}' + where + " ORDER BY (CASE WHEN industry = 'Tourism' THEN 0 ELSE 1 END), score DESC, reviews DESC", args).fetchall()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(LEAD_COLS)
    # Spreadsheet formulas must not execute when scraped names/notes are opened.
    writer.writerows([("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v) for v in row] for row in rows)
    return Response('\ufeff' + out.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="sri-lanka-prospects.csv"'})


class Update(BaseModel):
    stage: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=10000)
    contact_name: Optional[str] = Field(None, max_length=200)
    owner_phone: Optional[str] = Field(None, max_length=60)
    follow_up: Optional[date] = None


@router.patch('/api/leads/{lead_id}')
def update(lead_id: str, body: Update, request: Request):
    tbl, _ = _tables()
    u = auth.user(request)
    changes = body.model_dump(exclude_unset=True)
    if 'stage' in changes and changes['stage'] not in STAGES:
        raise HTTPException(422, 'Unknown stage')
    if any(changes.get(k) is None for k in ('notes', 'contact_name', 'owner_phone') if k in changes):
        raise HTTPException(422, 'Text fields cannot be null')
    if changes.get('follow_up'):
        changes['follow_up'] = changes['follow_up'].isoformat()
    with connect() as con:
        old = _lead_or_404(con, lead_id, u)
        if changes:
            if not old.get('owner') and u.get('username'):
                changes['owner'] = u['username']
            changes['updated_at'] = _now()
            con.execute(f'UPDATE {tbl} SET ' + ','.join(k + '=?' for k in changes) + ' WHERE id=?', list(changes.values()) + [lead_id])
            ev_kind = 'stage' if 'stage' in changes and changes['stage'] != old.get('stage') else 'update'
            _log_event(con, lead_id, ev_kind, 'Updated ' + ', '.join(k for k in changes if k != 'updated_at'), u.get('username', ''))
        return _detail(con, lead_id)


@router.get('/api/leads/{lead_id}/docs/{kind}.pdf')
def lead_doc(lead_id: str, kind: str, request: Request):
    if kind not in documents.DOCUMENTS:
        raise HTTPException(404, 'Unknown document')
    u = auth.user(request)
    with connect() as con:
        row = _lead_or_404(con, lead_id, u)
    lead = doc_lead(dict(row))
    try:
        pdf = documents.build(kind, lead, log=lambda *_: None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Couldn't build PDF ({exc}).")
    with connect() as con:
        _log_event(con, lead_id, 'doc', f"Built {documents.DOCUMENTS[kind]['title'].lower()} PDF (LKR)", u.get('username', ''))
    name = documents.filename(kind, lead)
    return Response(pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store'})


@router.get('/api/docs/{kind}.pdf')
def generic_doc(kind: str):
    if kind not in documents.DOCUMENTS:
        raise HTTPException(404, 'Unknown document')
    try:
        pdf = documents.build(kind, {'country': 'LK'}, log=lambda *_: None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Couldn't build PDF ({exc}).")
    name = documents.filename(kind)
    return Response(pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store'})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['sync', 'publish', 'segment', 'pairs'])
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--batches', type=int, default=1)
    parser.add_argument('--no-push', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='segment: report without writing')
    parser.add_argument('--all-industries', action='store_true', help='sync: also import non-tourism businesses')
    parser.add_argument('-o', '--output', default=str(ROOT / 'data/pairs_sri_lanka_tourism.csv'), help='pairs: CSV to write')
    args = parser.parse_args()
    if args.action == 'sync':
        print(json.dumps(sync(tourism_only=not args.all_industries), indent=2))
    elif args.action == 'segment':
        print(json.dumps(segment_all(apply=not args.dry_run), indent=2, ensure_ascii=False))
    elif args.action == 'pairs':
        pairs = tourism_pairs()
        with open(args.output, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['town', 'business_type'])
            w.writeheader()
            w.writerows(pairs)
        print(f'{len(pairs)} town × search pairs → {args.output}')
    else:
        for b in range(1, args.batches + 1):
            print(f'=== Sri Lanka Batch {b}/{args.batches} (limit={args.limit}) ===', flush=True)
            res = publish_previews(
                limit=args.limit,
                push=(not args.no_push and b == args.batches),
                reset_worktree=(b == 1),
            )
            print(json.dumps(res, indent=2), flush=True)
            if not res['new']:
                break
