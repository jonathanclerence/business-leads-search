"""Data for the Sri Lanka tourism preview sites.

    python -m pipeline.tourism_data pick --limit 1000      # who gets a site (read-only)
    python -m pipeline.tourism_data fetch --limit 1000     # their Google listing details + cover photo
    python -m pipeline.tourism_data scan                   # mark flyer-like photos (macOS Vision)

`fetch` runs one fast Maps search per business ("<name>, <town>, Sri Lanka"),
finds the listing by its place id and keeps what the listing itself says:
coordinates, Google's short description, amenities, the nightly price shown
for stays, check-in time, and the cover photo (downloaded and compressed, as
the marketing site only serves images from its own domain). Results live in
batches/sri-lanka/details/<place>.json and batches/sri-lanka/photos/.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

ROOT = config.ROOT
DETAILS = ROOT / 'batches/sri-lanka/details'
PHOTOS = ROOT / 'batches/sri-lanka/photos'
ATTRACTIONS_JSON = ROOT / 'data/attractions_sri_lanka.json'
ATTRACTION_IMG = Path(__file__).resolve().parent / 'tourism/attractions'

# Hotel groups and franchises: they have marketing teams and their own sites.
LK_CHAINS = re.compile(
    r'\b(cinnamon|jetwing|heritance|aitken spence|amaya|hilton|marriott|sheraton|shangri|taj |hyatt|radisson|'
    r'movenpick|mövenpick|anantara|avani|uga |citrus|centara|ramada|wyndham|best western|novotel|ibis|'
    r'club hotel dolphin|the kingsbury|galle face hotel|mount lavinia hotel|araliya|thilanka|earl\'?s regency|'
    r'thalappakatti|kfc|mcdonald|subway|baskin|cream house|perera and sons|green cabin|pizza hut|domino|burger king|starbucks|java lounge|barista|keells|cargills|'
    r'dialog|mobitel|hutch|singer|abans|odel|cotton collection|perera & sons|p&s |'
    r'thema collection|teardrop hotels|resplendent|lighthouse hotel|ceylon tea trails)\b', re.I)


def place_key(lead_id: str) -> str:
    """'lk:0x3ae1…:0x8cd…' → '3ae1…-8cd…' (a safe file name)."""
    return re.sub(r'[^0-9a-z]+', '-', lead_id.split(':', 1)[-1].lower().replace('0x', '')).strip('-')


def is_chain(name: str) -> bool:
    from .leads import is_chain as au_chain
    return bool(LK_CHAINS.search(name or '')) or au_chain(name or '')


# --------------------------------------------------------------------------
# Who gets a site
# --------------------------------------------------------------------------
MIN_PER_CATEGORY = 30


def pick(con, limit: int = 1000, include_previewed: bool = False) -> List[Dict[str, Any]]:
    """The next tourism businesses to build sites for: best score first, but
    every tourism category gets its share (at least MIN_PER_CATEGORY where
    that many exist), one site per business, no chains."""
    from . import leads as lead_tools
    from .sri_lanka import TOURISM, TOURISM_CATEGORIES, _tables
    tbl = _tables()[0]
    stage = "stage IN ('new', 'preview_created', 'preview_hosted')" if include_previewed else "stage = 'new' AND slug IS NULL"
    rows = [dict(r) for r in con.execute(
        f"SELECT * FROM {tbl} WHERE industry = ? AND {stage} AND COALESCE(owner, '') = '' "
        "ORDER BY score DESC, reviews DESC, id", (TOURISM,))]
    seen, by_cat = set(), {c: [] for c in TOURISM_CATEGORIES}
    for r in rows:
        key = lead_tools.business_key(r['name'], (r['search_town'] or '').split(',')[0])
        if key in seen or is_chain(r['name']) or r['tourism_category'] not in by_cat:
            continue
        seen.add(key)
        by_cat[r['tourism_category']].append(r)
    total = sum(len(v) for v in by_cat.values()) or 1
    quota = {c: min(len(v), max(MIN_PER_CATEGORY, round(limit * len(v) / total))) for c, v in by_cat.items()}
    while sum(quota.values()) > limit:  # trim the biggest categories first
        big = max(quota, key=lambda c: quota[c] - (MIN_PER_CATEGORY if len(by_cat[c]) >= MIN_PER_CATEGORY else 0))
        quota[big] -= 1
    chosen = [r for c, v in by_cat.items() for r in v[:quota[c]]]
    spare = [r for c, v in by_cat.items() for r in v[quota[c]:]]
    spare.sort(key=lambda r: (-(r['score'] or 0), -(r['reviews'] or 0)))
    chosen += spare[:max(0, limit - len(chosen))]
    chosen.sort(key=lambda r: (-(r['score'] or 0), -(r['reviews'] or 0), r['id']))
    return chosen[:limit]


# --------------------------------------------------------------------------
# Listing details from Google Maps
# --------------------------------------------------------------------------
def _g(x: Any, *path: int) -> Any:
    for i in path:
        if not isinstance(x, list) or i >= len(x):
            return None
        x = x[i]
    return x


def listing_details(p: list) -> Dict[str, Any]:
    """The bits of a Maps place array we put on a site."""
    desc = [d[1] for d in (_g(p, 32) or []) if isinstance(d, list) and isinstance(_g(d, 1), str)]
    long_desc = ''
    for d in _g(p, 32) or []:
        txt = _g(d, 7, 0, 0)
        if isinstance(txt, str):
            long_desc = txt
    amenities = [a[2] for a in (_g(p, 64, 2) or []) if isinstance(a, list) and isinstance(_g(a, 2), str) and _g(a, 3) == 1]
    price = _g(p, 88, 0)
    checkin = ''
    for item in _g(p, 196, 1) or []:
        txt = _g(item, 1, 0)
        if isinstance(txt, str) and 'check' in txt.lower():
            checkin = txt
    photos = []
    for ph in _g(p, 72, 0) or []:
        url, size = _g(ph, 6, 0), _g(ph, 6, 2)
        if isinstance(url, str) and 'googleusercontent' in url and isinstance(size, list) and len(size) == 2:
            photos.append({'url': url.split('=')[0], 'w': size[0], 'h': size[1]})
    hours = []
    for day in _g(p, 203, 0) or []:
        name, times = _g(day, 0), _g(day, 3)
        if isinstance(name, str) and isinstance(times, list):
            hours.append([name, ', '.join(t[0] for t in times if isinstance(_g(t, 0), str)) or 'Closed'])
    return {
        'lat': _g(p, 9, 2), 'lng': _g(p, 9, 3),
        'summary': desc[0] if desc else '', 'description': desc[1] if len(desc) > 1 else '', 'about': long_desc,
        'amenities': amenities[:12],
        'price': price if isinstance(price, str) and price.startswith('LKR') else '',
        'checkin': checkin, 'hours': hours, 'photos': photos,
        'rating': _g(p, 4, 7), 'reviews': _g(p, 4, 8),
    }


def usable(photo: Dict[str, Any]) -> bool:
    """Real photos only: big enough, not a square logo or a tiny scan."""
    w, h = photo.get('w') or 0, photo.get('h') or 0
    if min(w, h) < 640:
        return False
    return not (abs(w - h) < 0.06 * max(w, h) and max(w, h) < 1400)  # small squares are usually logos


def save_photo(data: bytes, out: Path, width: int, quality: int) -> Dict[str, int]:
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, 'WEBP', quality=quality, method=6)
    return {'w': img.width, 'h': img.height}


async def fetch(leads: List[Dict[str, Any]], rate: float = 2.0, log=print) -> Dict[str, int]:
    import httpx
    from leadfinder import fastmaps
    from leadfinder.config import settings
    DETAILS.mkdir(parents=True, exist_ok=True)
    todo = [l for l in leads if not (DETAILS / f"{place_key(l['id'])}.json").exists()]
    log(f'{len(leads) - len(todo)} already fetched, {len(todo)} to go')
    stats = {'found': 0, 'missing': 0, 'photos': 0}
    async with fastmaps.FastMapsClient(rate=rate) as client, httpx.AsyncClient(timeout=30) as http:
        for n, lead in enumerate(todo, 1):
            key, hex_id = place_key(lead['id']), lead['id'].split(':', 1)[-1]
            town = (lead['search_town'] or '').split(',')[0]
            q = f"{lead['name']}, {town}, Sri Lanka"
            params = {'tbm': 'map', 'authuser': '0', 'hl': 'en', 'gl': 'lk', 'q': q, 'pb': fastmaps.build_pb(q, 0)}
            await client.limiter.wait()
            try:
                r = await client._client.get(fastmaps.SEARCH_URL, params=params)
                places = fastmaps._place_arrays(fastmaps.decode(r.text)) if r.text.startswith(")]}'") else []
            except Exception as exc:  # noqa: BLE001
                log(f'  {lead["name"]}: {exc}')
                continue
            place = next((p for p in places if _g(p, 10) == hex_id), None)
            if place is None and len(places) == 1 and (_g(places[0], 11) or '').lower() == lead['name'].lower():
                place = places[0]
            info = listing_details(place) if place else {}
            info['found'] = bool(place)
            stats['found' if place else 'missing'] += 1
            saved = []
            for i, ph in enumerate([p for p in info.get('photos', []) if usable(p)][:2]):
                try:
                    resp = await http.get(ph['url'] + '=w1800-h1400-k-no')
                    if resp.status_code == 200 and resp.headers.get('content-type', '').startswith('image/'):
                        if i and resp.content in [s.get('_bytes') for s in saved]:
                            continue
                        name = f'{key}-{i}.webp'
                        dims = save_photo(resp.content, PHOTOS / name, 1600 if i == 0 else 960, 60)
                        saved.append({'file': name, **dims, '_bytes': resp.content})
                except Exception as exc:  # noqa: BLE001
                    log(f'  photo {lead["name"]}: {exc}')
            info['photo_files'] = [{k: v for k, v in s.items() if k != '_bytes'} for s in saved]
            stats['photos'] += len(saved)
            (DETAILS / f'{key}.json').write_text(json.dumps(info, ensure_ascii=False, indent=1))
            if n % 50 == 0:
                log(f'  {n}/{len(todo)} · {stats}')
    return stats


# --------------------------------------------------------------------------
# Flyers: owners often upload an advert (prices, phone numbers) as the cover.
# macOS Vision reads the text; photos with real text in them are not used.
# --------------------------------------------------------------------------
TEXTSCAN_SRC = Path(__file__).resolve().parent / 'tourism/textscan.swift'
TEXTSCAN_BIN = ROOT / 'batches/sri-lanka/textscan'
FLYER_CHARS, FLYER_AREA = 30, 0.04


def is_flyer(photo: Dict[str, Any]) -> bool:
    return (photo.get('text_chars') or 0) > FLYER_CHARS or (photo.get('text_area') or 0) > FLYER_AREA


def scan_text(log=print) -> Dict[str, int]:
    """Add text_chars / text_area to every fetched photo that has not been scanned."""
    import subprocess
    if not TEXTSCAN_BIN.exists() or TEXTSCAN_BIN.stat().st_mtime < TEXTSCAN_SRC.stat().st_mtime:
        subprocess.run(['swiftc', '-O', str(TEXTSCAN_SRC), '-o', str(TEXTSCAN_BIN)], check=True, capture_output=True)
    files = sorted(DETAILS.glob('*.json'))
    todo = []
    for f in files:
        info = json.loads(f.read_text())
        for ph in info.get('photo_files') or []:
            if 'text_chars' not in ph:
                todo.append(ph['file'])
    results = {}
    for i in range(0, len(todo), 40):
        out = subprocess.run([str(TEXTSCAN_BIN)] + [str(PHOTOS / n) for n in todo[i:i + 40]], capture_output=True, text=True).stdout
        for line in out.splitlines():
            path, chars, area = line.split('\t')
            results[Path(path).name] = (int(chars), float(area))
    flyers = 0
    for f in files:
        info = json.loads(f.read_text())
        changed = False
        for ph in info.get('photo_files') or []:
            if ph['file'] in results:
                ph['text_chars'], ph['text_area'] = results[ph['file']]
                changed = True
                flyers += is_flyer(ph)
        if changed:
            f.write_text(json.dumps(info, ensure_ascii=False, indent=1))
    log(f'scanned {len(results)} photos, {flyers} look like flyers')
    return {'scanned': len(results), 'flyers': flyers}


# --------------------------------------------------------------------------
# Sharp images for the published sites: every photo a site shows, from the
# original (up to 2560 px), as AVIF at 1920 and 960 px wide. Pages pick one
# with srcset. Business photos come from Google, attractions from Commons.
# --------------------------------------------------------------------------
WEB = ROOT / 'batches/sri-lanka/web'
WIDTHS = (1920, 960)
QUALITY = {1920: 60, 960: 56}
UA = {'User-Agent': 'DuNousPreviewBuilder/1.0 (https://www.dunous.com)'}


def web_name(stem: str, width: int) -> str:
    return f'{stem}-{width}.avif'


BUDGET = {1920: 430_000, 960: 165_000}  # bytes; quality steps down to fit


def _encode(data: bytes, stem: str) -> Dict[str, Any]:
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    WEB.mkdir(parents=True, exist_ok=True)
    out = {'src_w': img.width, 'src_h': img.height, 'files': {}}
    for w in WIDTHS:
        if w != min(WIDTHS) and img.width <= min(WIDTHS):
            continue  # no bigger file than the original has pixels for
        # Fit within w wide and 1.1 w tall (portrait photos are cropped anyway).
        scale = min(1.0, w / img.width, (w * 1.1) / img.height)
        im = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS) if scale < 1 else img
        q = QUALITY[w]
        while True:
            buf = io.BytesIO()
            im.save(buf, 'AVIF', quality=q, speed=6)
            if buf.tell() <= BUDGET[w] or q <= 42:
                break
            q -= 6
        (WEB / web_name(stem, w)).write_bytes(buf.getvalue())
        out['files'][w] = [im.width, im.height]
    return out


def shown_photos(lead: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The business photos a site shows: the first usable one, two for stays."""
    from .tourism_copy import FAMILY
    det = details(lead['id'])
    usable_ = [p for p in det.get('photo_files') or [] if not is_flyer(p)]
    return usable_[:2 if FAMILY.get(lead.get('tourism_category') or '') == 'stay' else 1]


async def build_web(leads: List[Dict[str, Any]], workers: int = 6, log=print) -> Dict[str, int]:
    """Download originals and write the sharp AVIFs for these leads' photos and
    every attraction photo. Already-built images are skipped."""
    import concurrent.futures
    import httpx
    pool = concurrent.futures.ThreadPoolExecutor(workers)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(workers)
    stats = {'photos': 0, 'places': 0, 'skipped': 0, 'failed': 0}

    async def one(client, url: str, stem: str, kind: str, record: Dict[str, Any]):
        if record.get('web') and all((WEB / web_name(stem, int(w))).exists() for w in record['web']['files']):
            stats['skipped'] += 1
            return
        async with sem:
            for attempt in range(5):
                try:
                    r = await client.get(url)
                    if r.status_code == 429:  # Google's CDN asks us to slow down
                        await asyncio.sleep(15 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    record['web'] = await loop.run_in_executor(pool, _encode, r.content, stem)
                    stats[kind] += 1
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 4:
                        stats['failed'] += 1
                        log(f'  {stem}: {exc}')
                    else:
                        await asyncio.sleep(5)
            else:
                stats['failed'] += 1
            await asyncio.sleep(0.4)

    async with httpx.AsyncClient(timeout=60, headers=UA, follow_redirects=True) as client:
        # Business photos: Google serves the original size up to the cap.
        jobs, touched = [], {}
        for lead in leads:
            f = DETAILS / f"{place_key(lead['id'])}.json"
            if not f.exists():
                continue
            info = touched.setdefault(f, json.loads(f.read_text()))
            wanted = {p['file'] for p in shown_photos(lead)}
            originals = {p['url'] for p in info.get('photos', [])}
            for ph in info.get('photo_files') or []:
                if ph['file'] not in wanted:
                    continue
                idx = int(ph['file'].rsplit('-', 1)[1].split('.')[0])
                src = [p for p in info.get('photos', []) if usable(p)][idx]['url'] if originals else None
                if src:
                    jobs.append(one(client, src + '=w2560-h2560-k-no', ph['file'].rsplit('.', 1)[0], 'photos', ph))
        # Attractions: Commons thumbnail at 1920 px (a standard width).
        places = attractions()
        titles = [a['image']['commons_file'] for a in places if a.get('image')]
        thumbs = {}
        for i in range(0, len(titles), 40):
            r = await client.get('https://commons.wikimedia.org/w/api.php', params={
                'action': 'query', 'format': 'json', 'prop': 'imageinfo', 'iiprop': 'url', 'iiurlwidth': 1920,
                'titles': '|'.join(titles[i:i + 40])})
            data = r.json().get('query', {})
            norm = {n['to']: n['from'] for n in data.get('normalized', [])}
            for page in data.get('pages', {}).values():
                info_ = (page.get('imageinfo') or [{}])[0]
                thumbs[norm.get(page['title'], page['title'])] = info_.get('thumburl') or info_.get('url')
        for a in places:
            if a.get('image') and thumbs.get(a['image']['commons_file']):
                jobs.append(one(client, thumbs[a['image']['commons_file']], 'place-' + a['id'], 'places', a['image']))
        await asyncio.gather(*jobs)
        for f, info in touched.items():
            f.write_text(json.dumps(info, ensure_ascii=False, indent=1))
        ATTRACTIONS_JSON.write_text(json.dumps(places, ensure_ascii=False, indent=1) + '\n')
    pool.shutdown()
    return stats


def details(lead_id: str) -> Dict[str, Any]:
    f = DETAILS / f'{place_key(lead_id)}.json'
    return json.loads(f.read_text()) if f.exists() else {}


# --------------------------------------------------------------------------
# Nearby attractions
# --------------------------------------------------------------------------
_ATTRACTIONS: Optional[List[Dict[str, Any]]] = None


def attractions() -> List[Dict[str, Any]]:
    global _ATTRACTIONS
    if _ATTRACTIONS is None:
        _ATTRACTIONS = json.loads(ATTRACTIONS_JSON.read_text()) if ATTRACTIONS_JSON.exists() else []
    return _ATTRACTIONS


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def travel(distance: float) -> str:
    """Road time is roughly 1.4 × the straight line at Sri Lankan speeds."""
    if distance < 1.2:
        return f'{max(2, round(distance * 1000 / 80))} min walk'
    minutes = round(distance * 1.4 / 32 * 60 / 5) * 5 or 5
    by = 'tuk-tuk' if distance < 15 else 'car'
    return f'{minutes} min by {by}' if minutes < 90 else f'{minutes / 60:.1f} h by car'.replace('.0 h', ' h')


def nearby(lat: Optional[float], lng: Optional[float], town: str = '', limit: int = 6, radius: float = 45.0) -> List[Dict[str, Any]]:
    """Closest attractions with a photo, nearest first, each with distance and travel time."""
    places = [a for a in attractions() if a.get('image')]
    if lat is None or lng is None:
        places = [a for a in places if town in (a.get('nearest_towns') or [])]
        return [dict(a, km=None, travel='') for a in places[:limit]]
    out = []
    for a in places:
        d = km(lat, lng, a['lat'], a['lng'])
        if d <= radius:
            out.append(dict(a, km=round(d, 1) if d < 10 else round(d), travel=travel(d)))
    out.sort(key=lambda a: a['km'])
    # Variety: at most two of a kind (six temples in a row tell a guest nothing).
    picked, kinds = [], {}
    for a in out:
        if kinds.get(a['kind'], 0) < 2:
            picked.append(a)
            kinds[a['kind']] = kinds.get(a['kind'], 0) + 1
    picked += [a for a in out if a not in picked]
    return picked[:limit]


def nearest(lat: Optional[float], lng: Optional[float], kinds, radius: float = 25.0) -> Optional[Dict[str, Any]]:
    """Closest attraction of these kinds, photo or not (for facts, not pictures)."""
    if lat is None or lng is None:
        return None
    best = None
    for a in attractions():
        if a['kind'] in kinds:
            dist = km(lat, lng, a['lat'], a['lng'])
            if dist <= radius and (best is None or dist < best[0]):
                best = (dist, a)
    if not best:
        return None
    return dict(best[1], km=round(best[0], 1), travel=travel(best[0]))


def main() -> None:
    from . import db
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['pick', 'fetch', 'scan', 'web'])
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--live', action='store_true', help='web: every tourism lead with a published site')
    ap.add_argument('--limit', type=int, default=1000)
    ap.add_argument('--rate', type=float, default=2.0)
    args = ap.parse_args()
    with db.connect() as con:
        if args.live:
            leads = [dict(r) for r in con.execute("SELECT * FROM lk_leads WHERE slug IS NOT NULL AND industry = 'Tourism'")]
        else:
            leads = pick(con, args.limit)
    if args.action == 'web':
        print(json.dumps(asyncio.run(build_web(leads, workers=args.workers)), indent=1))
        return
    if args.action == 'pick':
        from collections import Counter
        print(len(leads), 'businesses')
        for c, n in Counter(l['tourism_category'] for l in leads).most_common():
            print(f'  {n:4}  {c}')
        return
    if args.action == 'scan':
        scan_text()
        return
    print(json.dumps(asyncio.run(fetch(leads, rate=args.rate)), indent=1))
    scan_text()


if __name__ == '__main__':
    main()
