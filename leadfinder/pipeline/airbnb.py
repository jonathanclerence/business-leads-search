"""Which Sri Lanka stays with a preview site are also on Airbnb?

    python -m pipeline.airbnb check [--limit N] [--redo]   # look each stay up (slow, polite)
    python -m pipeline.airbnb report                       # counts + exports/airbnb_matches.csv
    python -m pipeline.airbnb rank [--apply] [--undo]      # move sure matches up the call list
    python -m pipeline.airbnb details                      # read each sure match's listing page
    python -m pipeline.airbnb photos                       # download and compress its photos
    python -m pipeline.airbnb names [--apply]              # host's first name -> the lead's contact name
    python -m pipeline.airbnb publish [--no-push]          # re-render the preview sites and push

For every stay (resort, villa, guest house, hostel) that has a preview site,
`check` opens Airbnb's public map search around the business's Google
coordinates and compares listing titles with the business name. Airbnb
listings are named by the host, so a business only counts as a match when its
own distinctive name appears in a listing title a short distance away:

  match     every distinctive word of the name is in the title
  possible  about half of them are, or only common words line up (check by eye)
  none      nothing nearby carries the name (it may still be listed under
            another title, so "none" means "not found", not "not on Airbnb")

`rank` adds RANK_BONUS to the score of every sure match and notes the listing
in the lead's "why" line (a business already taking bookings through Airbnb,
with no site of its own, has the most to gain). Without --apply it only shows
what would change; --undo takes the bonus and the note off again.

Results live in batches/sri-lanka/airbnb/<place>.json: the listing links,
title, rating, nightly price and photo links Airbnb shows in search.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from . import config
from . import tourism_data as td

OUT = config.ROOT / 'batches/sri-lanka/airbnb'
STAY_CATEGORIES = ('Resorts & boutique hotels', 'Villas & holiday rentals',
                   'Guest houses & homestays', 'Hostels & surf hostels')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
BOX = 0.01           # degrees each way: about 1.1 km
MAX_PAGES = 3
PAUSE = 1.0          # seconds a worker waits between requests
WORKERS = 3

# Words that say what kind of place it is, not which place.
GENERIC = set('''
hotel hotels villa villas guest guests house houses guesthouse home homes homestay homestays stay stays
resort resorts inn lodge rest hostel hostels cabana cabanas bungalow bungalows cottage cottages
residence residences residency residencies room rooms apartment apartments suite suites
beach sea ocean bay lake river lagoon hill hills mountain view views garden gardens nature eco
surf holiday holidays tourist travellers travelers family place palace paradise heaven
the and by at in of on for with a an de la le sri lanka lankan ceylon new old city town
airport transit fort peak heights
boutique luxury private pool restaurant cafe bar spa safari camp camping park hideaway retreat
'''.split())


def tokens(text: str) -> List[str]:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return re.findall(r'[a-z0-9]+', text.replace("'", ''))


_PLACES: Optional[set] = None


def place_words() -> set:
    """Words that are Sri Lankan place names: they say where, not who."""
    global _PLACES
    if _PLACES is None:
        words = set('sigiri sigiriya hiriketiya hiriketiy madiha polhena sinharaja hikka trinco kandyan nuwaraeliya '
                    'arugambay adams dalawella kabalana midigama dikwella talalla bolgoda hanthana riverston'.split())
        for f in ('towns_sri_lanka.csv', 'towns_sri_lanka_tourism.csv'):
            path = config.ROOT / 'data' / f
            if path.exists():
                with path.open(encoding='utf-8') as fh:
                    for row in csv.DictReader(fh):
                        for value in row.values():
                            if value and not re.search(r'\d', value):
                                words.update(t for t in tokens(value) if len(t) >= 4)
        _PLACES = words - {'house', 'villa', 'hotel'}
    return _PLACES


def distinctive(name: str, town: str = '') -> List[str]:
    town_words = set(tokens(town)) | place_words()
    out: List[str] = []
    for t in tokens(name):
        if t in GENERIC or t in town_words:
            continue
        if len(t) >= 3 and not t.isdigit() and t not in out:
            out.append(t)
    return out


_JOINERS = ('the', 'and', 'by', 'at', 'in', 'of')


def judge(name: str, town: str, title: str) -> str:
    """'match', 'possible' or '' for one Airbnb title against one business."""
    want = distinctive(name, town)
    have = tokens(title)
    joined = set(have) | {a + b for a, b in zip(have, have[1:])}  # "Sky Lark" is "SkyLark"
    words = [t for t in tokens(name) if t not in _JOINERS]
    spoken = ' ' + ' '.join(t for t in have if t not in _JOINERS) + ' '
    if not want:
        # A name made only of common words ("River Cottage"): the same words
        # in the same order is worth a look, never a sure match.
        words = [t for t in words if t not in set(tokens(town))]
        return 'possible' if len(words) >= 2 and f' {" ".join(words)} ' in spoken else ''
    hit = [t for t in want if t in joined]
    if not hit:
        return ''
    if len(want) > 1 and len(hit) == len(want):
        return 'match'
    # One distinctive word can be a neighbourhood or an adjective ("Polhena",
    # "Sunny"), so it also needs its neighbour: "Amara Guest", "Misty Villa".
    pairs = [f' {a} {b} ' for a, b in zip(words, words[1:]) if a in hit or b in hit]
    if any(p in spoken for p in pairs):
        return 'match'
    if len(hit) * 2 >= len(want) and max(len(t) for t in hit) >= 4:
        return 'possible'
    return ''


def _results(html: str) -> Dict[str, Any]:
    m = re.search(r'<script id="data-deferred-state-0"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError('Airbnb page had no search data (blocked or layout changed)')
    found: Dict[str, Dict[str, Any]] = {}
    cursors: List[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if x.get('__typename') == 'StaySearchResult':
                listing = x.get('demandStayListing') or {}
                try:
                    number = base64.b64decode(listing.get('id') or '').decode().split(':')[-1]
                except Exception:
                    number = ''
                coord = (listing.get('location') or {}).get('coordinate') or {}
                if number and number not in found:
                    price = ((x.get('structuredDisplayPrice') or {}).get('primaryLine') or {})
                    found[number] = {
                        'id': number,
                        'url': f'https://www.airbnb.com/rooms/{number}',
                        'name': ((x.get('nameLocalized') or {}).get('localizedStringWithTranslationPreference')
                                 or x.get('subtitle') or ''),
                        'kind': x.get('title') or '',
                        'rating': x.get('avgRatingLocalized') or '',
                        'price': price.get('discountedPrice') or price.get('price') or price.get('accessibilityLabel') or '',
                        'lat': coord.get('latitude'), 'lng': coord.get('longitude'),
                        'photos': [p.get('picture') for p in (x.get('contextualPictures') or []) if p.get('picture')],
                    }
            if isinstance(x.get('pageCursors'), list):
                cursors.extend(c for c in x['pageCursors'] if c not in cursors)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads(m.group(1)))
    return {'listings': list(found.values()), 'cursors': cursors}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode('utf-8', 'ignore')


def around(lat: float, lng: float, town: str) -> Iterator[Dict[str, Any]]:
    """Airbnb listings shown on the map around a point, page by page."""
    place = urllib.parse.quote(f'{town}, Sri Lanka')
    query = dict(ne_lat=lat + BOX, ne_lng=lng + BOX, sw_lat=lat - BOX, sw_lng=lng - BOX, zoom=15, search_by_map='true')
    base = f'https://www.airbnb.com/s/{place}/homes?' + urllib.parse.urlencode(query)
    seen: set = set()
    cursors: List[str] = ['']
    for page in range(MAX_PAGES):
        if page >= len(cursors):
            return
        data = _results(_get(base + (f'&cursor={urllib.parse.quote(cursors[page])}' if cursors[page] else '')))
        time.sleep(PAUSE)
        if page == 0:
            cursors = data['cursors'] or ['']
        fresh = [x for x in data['listings'] if x['id'] not in seen]
        if not fresh:
            return
        for x in fresh:
            seen.add(x['id'])
            yield x


def look_up(lead: Dict[str, Any]) -> Dict[str, Any]:
    d = td.details(lead['id'])
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    out: Dict[str, Any] = {'lead_id': lead['id'], 'name': lead['name'], 'checked_at': now, 'status': 'none', 'listings': []}
    if d.get('lat') is None or d.get('lng') is None:
        out['status'] = 'no_coords'
        return out
    town = (lead.get('search_town') or '').split(',')[0].strip()
    seen = 0
    for x in around(float(d['lat']), float(d['lng']), town):
        seen += 1
        verdict = judge(lead['name'], town, x['name'])
        if verdict and x.get('lat') is not None:
            km = round(td.km(float(d['lat']), float(d['lng']), x['lat'], x['lng']), 2)
            out['listings'].append(dict(x, verdict=settle(verdict, km), km=km))
    out['nearby'] = seen
    out['listings'].sort(key=lambda x: (x['verdict'] != 'match', x['km']))
    if out['listings']:
        out['status'] = out['listings'][0]['verdict']
    return out


SURE_KM = 0.6        # Airbnb blurs a listing's pin by a few hundred metres


def settle(verdict: str, km: float) -> str:
    return 'possible' if verdict == 'match' and km > SURE_KM else verdict


def rejudge(log=print) -> None:
    """Apply the current matching rules to what `check` already saved."""
    from . import db
    with db.connect() as con:
        leads = stays(con)
    for lead in leads:
        f = OUT / f'{td.place_key(lead["id"])}.json'
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        if r.get('status') not in ('match', 'possible', 'none'):
            continue
        town = (lead.get('search_town') or '').split(',')[0].strip()
        kept = []
        for x in r.get('listings', []):
            verdict = judge(lead['name'], town, x['name'])
            if verdict:
                kept.append(dict(x, verdict=settle(verdict, x['km'])))
        kept.sort(key=lambda x: (x['verdict'] != 'match', x['km']))
        r.update(listings=kept, status=kept[0]['verdict'] if kept else 'none')
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1))


def result(lead_id: str) -> Dict[str, Any]:
    f = OUT / f'{td.place_key(lead_id)}.json'
    return json.loads(f.read_text()) if f.exists() else {}


def stays(con) -> List[Dict[str, Any]]:
    from .sri_lanka import _tables
    marks = ', '.join('?' for _ in STAY_CATEGORIES)
    return [dict(r) for r in con.execute(
        f"SELECT * FROM {_tables()[0]} WHERE industry = 'Tourism' AND slug IS NOT NULL AND slug != '' "
        f"AND tourism_category IN ({marks}) ORDER BY score DESC, reviews DESC, id", STAY_CATEGORIES)]


def check(limit: Optional[int] = None, redo: bool = False, log=print) -> Dict[str, int]:
    from . import db
    OUT.mkdir(parents=True, exist_ok=True)
    with db.connect() as con:
        leads = stays(con)
    todo = [l for l in leads if redo or result(l['id']).get('status') in (None, 'error')]
    if limit:
        todo = todo[:limit]
    log(f'{len(leads)} stays with a preview, {len(todo)} to check')
    counts: Dict[str, int] = {}
    failures = 0

    def one(lead: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return look_up(lead)
        except Exception as e:  # blocked, timed out, layout changed
            return {'lead_id': lead['id'], 'name': lead['name'], 'status': 'error', 'error': str(e)[:200], 'listings': []}

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(WORKERS) as pool:
        for i, (lead, r) in enumerate(zip(todo, pool.map(one, todo)), 1):
            (OUT / f'{td.place_key(lead["id"])}.json').write_text(json.dumps(r, ensure_ascii=False, indent=1))
            counts[r['status']] = counts.get(r['status'], 0) + 1
            failures = failures + 1 if r['status'] == 'error' else 0
            best = r['listings'][0]['name'] if r['listings'] else ''
            log(f'{i}/{len(todo)} {r["status"]:9} {lead["name"][:40]:40} {best[:50]}')
            if failures >= 6:
                log('Six failures in a row: stopping. Run again later; finished ones are kept.')
                pool.shutdown(wait=False, cancel_futures=True)
                break
    return counts


def report(log=print) -> Dict[str, int]:
    from . import db
    with db.connect() as con:
        leads = stays(con)
    counts: Dict[str, int] = {}
    rows = []
    for lead in leads:
        r = result(lead['id'])
        status = r.get('status') or 'not checked'
        counts[status] = counts.get(status, 0) + 1
        if status in ('match', 'possible'):
            top = r['listings'][0]
            rows.append([status, lead['name'], (lead.get('search_town') or '').split(',')[0], lead['tourism_category'],
                         lead['website_status'], lead['score'], lead['reviews'], top['name'], top['km'], top['rating'],
                         top['price'], len([x for x in r['listings'] if x['verdict'] == status]), top['url'],
                         f'https://www.dunous.com/preview/{lead["slug"]}', lead['id']])
    out = config.ROOT / 'exports/airbnb_matches.csv'
    out.parent.mkdir(exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['verdict', 'business', 'town', 'type', 'web_presence', 'score', 'google_reviews', 'airbnb_title',
                    'km_apart', 'airbnb_rating', 'airbnb_price', 'listings', 'airbnb_url', 'preview', 'lead_id'])
        w.writerows(sorted(rows, key=lambda r: (r[0] != 'match', -(r[5] or 0), -(r[6] or 0))))
    log(f'{len(leads)} stays with a preview: ' + ', '.join(f'{v} {k}' for k, v in sorted(counts.items())))
    log(f'wrote {out}')
    return counts


# --------------------------------------------------------------------------
# The listing page of a sure match: host, what the place is, amenities, photos
# --------------------------------------------------------------------------
MAX_PHOTOS = 6
_NOT_A_NAME = re.compile(r'\b(villa|villas|hotel|resort|homes?|stays?|house|guest|lodge|inn|hostel|rentals?|holidays?|'
                         r'properties|property|management|group|team|tours?|travels?|lanka|ceylon|cabana|residenc\w+|pvt|ltd|'
                         r'green|turtle|nature|night|beach|surf|eco|garden|view|blue|sun|sea|ocean)\b', re.I)


def person_name(host: str, business: str = '') -> str:
    """The host's first name, when the host profile is a person and not a business."""
    host = re.sub(r'\s+', ' ', host or '').strip()
    if set(tokens(host)) & set(tokens(business)) or len(host) < 3:
        return ''  # the profile is named after the place
    first = re.split(r'\s+(?:and|&|And)\s+|\s*[,/]\s*', host)[0].strip()
    if not first or _NOT_A_NAME.search(host) or not re.fullmatch(r"[A-Za-z][A-Za-z.'-]{1,19}(?: [A-Za-z][A-Za-z.'-]{1,19})?", first):
        return ''
    return ' '.join(w.capitalize() if w.islower() or w.isupper() else w for w in first.split())


def parse_listing(html: str) -> Dict[str, Any]:
    import html as html_lib
    out: Dict[str, Any] = {}
    m = re.search(r'"text":"Hosted by ([^"]{1,80})"', html)
    out['host'] = json.loads(f'"{m.group(1)}"') if m else ''
    ld: Dict[str, Any] = {}
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get('@type') in ('VacationRental', 'Hotel', 'LodgingBusiness', 'Product'):
            ld = data
            break
    out['description'] = ld.get('description') or ''
    m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    out['overview'] = html_lib.unescape(m.group(1)) if m else ''
    m = re.search(r'"propertyType":"([^"]*)"', html)
    out['property_type'] = m.group(1) if m else ''
    m = re.search(r'"personCapacity":(\d+)', html)
    out['sleeps'] = int(m.group(1)) if m else 0
    amenities: List[str] = []
    m = re.search(r'"previewAmenitiesGroups":(\[.*?\]),"seeAllAmenitiesGroups"', html, re.S)
    if m:
        try:
            for group in json.loads(m.group(1)):
                amenities += [a['title'] for a in group.get('amenities', []) if a.get('available') and a.get('title')]
        except ValueError:
            pass
    out['amenities'] = amenities
    images = ld.get('image') or []
    images = [images] if isinstance(images, str) else list(images)
    for url in re.findall(r'https://a0\.muscache\.com/im/pictures/[^"?\\&]+\.(?:jpe?g|png|webp)', html):
        if '/user/' not in url and 'Hosting-' in url or '/miso/' in url:
            images.append(url)
    seen: List[str] = []
    for url in images:
        url = url.split('?')[0]
        if url not in seen and '/user/' not in url and '/pictures/airflow/' not in url:
            seen.append(url)
    out['photos'] = seen[:24]
    return out


def sure_matches() -> List[Dict[str, Any]]:
    from . import db
    with db.connect() as con:
        leads = stays(con)
    return [l for l in leads if result(l['id']).get('status') == 'match']


def details(redo: bool = False, log=print) -> int:
    done = 0
    for lead in sure_matches():
        f = OUT / f'{td.place_key(lead["id"])}.json'
        r = json.loads(f.read_text())
        if r.get('page') and not redo:
            continue
        try:
            r['page'] = parse_listing(_get(r['listings'][0]['url']))
        except Exception as e:  # noqa: BLE001
            log(f'  {lead["name"]}: {e}')
            continue
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1))
        done += 1
        page = r['page']
        log(f'{lead["name"][:36]:36} host={page["host"][:18]:18} photos={len(page["photos"]):2} amenities={len(page["amenities"])} {page["overview"][:50]}')
        time.sleep(PAUSE)
    return done


def photos(redo: bool = False, log=print) -> Dict[str, int]:
    """Download each sure match's first photos and write the sharp AVIFs the
    preview sites serve (same sizes as the Google photos)."""
    stats = {'leads': 0, 'photos': 0, 'failed': 0}

    def one(lead: Dict[str, Any]) -> None:
        key = td.place_key(lead['id'])
        f = OUT / f'{key}.json'
        r = json.loads(f.read_text())
        if not r.get('page') or (r.get('photo_files') and not redo):
            return
        saved: List[Dict[str, Any]] = []
        for url in r['page']['photos']:
            if len(saved) >= MAX_PHOTOS:
                break
            stem = f'{key}-a{len(saved)}'
            try:
                req = urllib.request.Request(url + '?im_w=1920', headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=40) as resp:
                    web = td._encode(resp.read(), stem)
            except Exception as e:  # noqa: BLE001
                stats['failed'] += 1
                log(f'  {lead["name"]}: {e}')
                continue
            big = web['files'][max(web['files'])]
            if web['src_w'] < 1000 or web['src_w'] < web['src_h'] * 0.9:  # too small, or a tall phone shot
                continue
            saved.append({'file': stem + '.webp', 'w': big[0], 'h': big[1], 'web': web, 'source': 'airbnb', 'from': url})
        r['photo_files'] = saved
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1))
        stats['leads'] += 1
        stats['photos'] += len(saved)
        log(f'{lead["name"][:40]:40} {len(saved)} photos')

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(one, sure_matches()))
    return stats


def names(apply: bool = False, log=print) -> int:
    """Put the Airbnb host's first name on leads that have no contact name yet."""
    from . import db
    from .sri_lanka import _tables
    tbl, ev_tbl = _tables()
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    changes = []
    for lead in sure_matches():
        host = (result(lead['id']).get('page') or {}).get('host') or ''
        name = person_name(host, lead['name'])
        if name and not (lead.get('contact_name') or '').strip():
            changes.append((name, lead['id'], lead['name'], host))
    for name, _, business, host in changes:
        log(f'  {business[:40]:40} {name}  (Airbnb host: {host})')
    if apply and changes:
        with db.connect() as con:
            con.executemany(f"UPDATE {tbl} SET contact_name = ? WHERE id = ? AND COALESCE(contact_name, '') = ''",
                            [(n, i) for n, i, _, _ in changes])
            con.executemany(f'INSERT INTO {ev_tbl} (lead_id, at, detail) VALUES (?, ?, ?)',
                            [(i, ts, f'Contact name {n} taken from the Airbnb host profile ("{h}"). Confirm on the call.')
                             for n, i, _, h in changes])
    log(f'{len(changes)} names {"saved" if apply else "found (add --apply)"}')
    return len(changes)


def publish(push: bool = True, log=print) -> Dict[str, Any]:
    """Re-render every live preview (the Airbnb ones pick up their new photos
    and details) and push the marketing site."""
    from . import db, publish as pub
    with db.connect() as con:
        leads = pub.active_leads(con) + pub.active_lk_leads(con)
    target = pub.prepare_worktree(log)
    pub.refresh_info_pack(log)
    log(f'Rendering {len(leads)} preview pages…')
    stats = pub.write_site_files(target, leads)
    n = len(sure_matches())
    pushed = pub.commit_and_push(target, f'Sri Lanka previews: Airbnb photos and details on {n} stays', push, log)
    return dict(stats, pushed=bool(pushed and push))


RANK_BONUS = 10
_WHY = ' · Listed on Airbnb: '


def rank(apply: bool = False, undo: bool = False, log=print) -> int:
    from . import db
    from .sri_lanka import _tables
    tbl = _tables()[0]
    changes = []
    with db.connect() as con:
        for lead in stays(con):
            why = lead.get('why') or ''
            if undo:
                if _WHY in why:
                    changes.append(((lead['score'] or 0) - RANK_BONUS, why.split(_WHY)[0], lead['id'], lead['name']))
                continue
            r = result(lead['id'])
            if r.get('status') == 'match' and _WHY not in why:
                changes.append(((lead['score'] or 0) + RANK_BONUS, why + _WHY + r['listings'][0]['url'], lead['id'], lead['name']))
        if apply and changes:
            con.executemany(f'UPDATE {tbl} SET score = ?, why = ? WHERE id = ?', [c[:3] for c in changes])
    for score, _, _, name in changes[:15]:
        log(f'  {name} -> score {score}')
    log(f'{len(changes)} leads {"updated" if apply else "would change (add --apply)"}')
    return len(changes)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check')
    c.add_argument('--limit', type=int)
    c.add_argument('--redo', action='store_true')
    sub.add_parser('report')
    sub.add_parser('rejudge')
    for cmd in ('details', 'photos'):
        sub.add_parser(cmd).add_argument('--redo', action='store_true')
    sub.add_parser('names').add_argument('--apply', action='store_true')
    sub.add_parser('publish').add_argument('--no-push', action='store_true')
    k = sub.add_parser('rank')
    k.add_argument('--apply', action='store_true')
    k.add_argument('--undo', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'check':
        print(check(a.limit, a.redo))
    elif a.cmd == 'details':
        print(details(a.redo))
    elif a.cmd == 'photos':
        print(photos(a.redo))
    elif a.cmd == 'names':
        names(a.apply)
    elif a.cmd == 'publish':
        print(json.dumps(publish(not a.no_push), indent=2))
    elif a.cmd == 'rejudge':
        rejudge()
        report()
    elif a.cmd == 'rank':
        rank(a.apply, a.undo)
    else:
        report()


if __name__ == '__main__':
    main()
