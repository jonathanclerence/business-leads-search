"""Sri Lanka tourism preview sites: lead + listing details → HTML.

One template (templates/tourism.html.j2), nine looks ("families", see
tourism_copy.FAMILY), personalised per business: its own Google cover photo,
the real attractions nearest to it with travel times, amenities and price
from its listing, the drive from the airport, its rating, and the season for
its part of the island. Shared css/js/fonts/photos are published under
/previewsite-assets/lk/ (the marketing site only serves its own files).
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, tourism_copy as copy, tourism_data as data

HERE = Path(__file__).resolve().parent
STATIC = HERE / 'tourism'
LK_ASSETS = 'lk'  # under config.ASSETS_DIR

_env = Environment(loader=FileSystemLoader(HERE / 'templates'), autoescape=select_autoescape(['html', 'j2']),
                   trim_blocks=True, lstrip_blocks=True)


def _seed(text: str) -> int:
    return int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)


def pick(options: List[Any], key: str) -> Any:
    return options[_seed(key) % len(options)] if options else None


@__import__('functools').lru_cache(maxsize=1)
def static_version() -> str:
    h = hashlib.sha1()
    for f in sorted(p for p in STATIC.rglob('*') if p.is_file() and p.suffix in ('.css', '.js', '.svg', '.woff2')):
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:10]


def ink_on(hex_colour: str) -> str:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return '#141414' if 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > 0.4 else '#ffffff'


def town_info(search_town: str) -> Dict[str, str]:
    from .sri_lanka import towns
    row = towns().get(search_town, {})
    return {'town': (search_town or '').split(',')[0].strip() or 'Sri Lanka',
            'region': row.get('region') or row.get('province') or '', 'tags': row.get('tags', ''),
            'district': row.get('district', '')}


def airport_drive(lat: float, lng: float) -> str:
    d = data.km(lat, lng, *copy.AIRPORT)
    if d < 12:
        return 'about 20 minutes from Bandaranaike Airport'
    # Expressways run south along the coast; the hills and the east are slow.
    if lat < 7.3 and (lng < 80.6 or lat < 6.25):
        speed = 58   # expressways down the west and south coasts
    elif 6.4 < lat < 7.4 and 80.5 < lng < 81.2:
        speed = 30   # hill country bends
    else:
        speed = 45
    hours = d * 1.3 / speed
    if hours < 1:
        return f'about {round(hours * 60 / 5) * 5} minutes from Bandaranaike Airport'
    whole, half = int(hours), (hours - int(hours)) >= 0.25
    if (hours - whole) >= 0.75:
        whole, half = whole + 1, False
    return f"about {whole}{' and a half' if half else ''} hour{'s' if whole > 1 or half else ''} from Bandaranaike Airport"


def season_for(info: Dict[str, str], category: str, name: str = '') -> Dict[str, str]:
    region = info['region']
    if 'safari' in info['tags'] and region == 'Safari':
        key = 'Safari'
    else:
        key = region if region in copy.SEASONS else 'South Coast'
    when, text = copy.SEASONS[key]
    extra = ''
    tags = info['tags']
    if category == 'Whale watching, boat & lagoon tours':
        if 'whale' in tags or 'whale' in (name or '').lower() or 'dolphin' in (name or '').lower():
            extra = copy.SPECIAL_SEASONS['whale_east' if region == 'East Coast' else
                                         'whale_kalpitiya' if 'Kalpitiya' in info['town'] else 'whale_south']
        else:
            extra = copy.SPECIAL_SEASONS['lagoon']
    elif 'surf' in tags and category.startswith('Surf'):
        extra = copy.SPECIAL_SEASONS['surf_east' if region == 'East Coast' else 'surf_south']
    return {'when': when, 'text': text, 'extra': extra}


def fill(text: str, ctx: Dict[str, str]) -> str:
    return text.format(**ctx)


def photo_url(name: str) -> str:
    return f"/previewsite-assets/{LK_ASSETS}/photos/{name}"


def place_url(name: str) -> str:
    return f"/previewsite-assets/{LK_ASSETS}/places/{name.rsplit('.', 1)[0]}.webp"


FULL_BLEED_MIN = 1600  # px of original width a photo needs to fill the screen sharply


def picture(stem: str, web: Dict[str, Any], folder: str, fallback: str, w: int = 1600, h: int = 1067) -> Dict[str, Any]:
    """An image for the template: sharp AVIFs with a srcset when built
    (tourism_data.build_web), else the older single file."""
    base = f"/previewsite-assets/{LK_ASSETS}/{folder}"
    files = {int(k): v for k, v in ((web or {}).get('files') or {}).items()}
    if files:
        big = max(files)
        return {'url': f"{base}/{data.web_name(stem, big)}", 'w': files[big][0], 'h': files[big][1],
                'srcset': ', '.join(f"{base}/{data.web_name(stem, k)} {files[k][0]}w" for k in sorted(files)),
                'src_w': web.get('src_w') or files[big][0]}
    return {'url': fallback, 'w': w, 'h': h, 'srcset': '', 'src_w': w}


def place_picture(a: Dict[str, Any]) -> Dict[str, Any]:
    img = a['image']
    return picture('place-' + a['id'], img.get('web'), 'places', place_url(img['file']), img.get('width') or 1600, img.get('height') or 1067)


def maps_link(lead: Dict[str, Any]) -> str:
    q = f"{lead['name']} {lead.get('address') or lead.get('search_town') or ''}".strip()
    return 'https://www.google.com/maps/search/?' + urllib.parse.urlencode({'api': '1', 'query': q})


def display_phone(raw: str) -> str:
    m = re.fullmatch(r'\+94(\d{2})(\d{3})(\d{4})', raw or '')
    return f'0{m.group(1)} {m.group(2)} {m.group(3)}' if m else (raw or '')


DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def nice_hours(rows: List[List[str]]) -> List[List[str]]:
    """Google's ["Tuesday", "7AM–7PM"] → Monday first, "7 am to 7 pm"."""
    def fmt(h: str) -> str:
        h = h.replace('\u2013', ' to ').replace('\u2014', ' to ').replace('\u202f', ' ').replace('\u2009', ' ')
        h = re.sub(r'(\d)\s*(AM|PM)', lambda m: f'{m.group(1)} {m.group(2).lower()}', h)
        return re.sub(r'\s+', ' ', h).strip()
    by_day = {d: fmt(h) for d, h in rows if d in DAYS}
    return [[d, by_day[d]] for d in DAYS if d in by_day]


LEGAL = re.compile(r'\s*[\(\[]?\b(pvt\.?|private)\s*\)?\s*(ltd\.?|limited)\b[\)\]]?|\s*\b(pvt|ltd)\b\.?', re.I)


def clean_name(name: str, town: str = '') -> str:
    """Tidy a Google listing name for a headline: no "(Pvt) Ltd", no
    shouting, no "- Kandy" tail repeating the town."""
    from .documents import short_name
    n = re.sub(r'[_\s]+', ' ', name or '').strip()
    n = LEGAL.sub('', n).strip(' -,')
    n = re.sub(r'\(\s*\)?\s*$', '', n).strip(' -,')
    n = re.split(r'\s+@\s*', n)[0]
    n = re.sub(r'\s*\([^)]*(\)|$)', ' ', n).strip() or n   # "Name(Keywords…)": drop the bracketed part
    n = short_name(n, 34).strip(' -,.|')
    n = re.sub(r'\s+(&|and|with|by|-)$', '', n, flags=re.I).strip(' -,.|&')
    n = re.sub(r'\s+[-|]\s+' + re.escape(town) + r'$', '', n, flags=re.I) if town else n
    if n.isupper() or n.islower():
        small = {'and', 'of', 'the', 'by', 'at', 'in', 'on', 'for', 'de', 'la'}
        words = n.lower().split()
        n = ' '.join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))
    else:  # leave the owner's capitals alone, but start words in place names with one
        n = re.sub(r'\b(sigiriya|kandy|galle|ella|mirissa|weligama|unawatuna|hikkaduwa|bentota|matara|tangalle|'
                   r'trincomalee|negombo|colombo|jaffna|arugam|kalpitiya|ahangama|haputale|nuwara|eliya|dambulla|'
                   r'habarana|koggala|hiriketiya|polhena|yala|udawalawe|kataragama|tissamaharama)\b',
                   lambda m: m.group(1).capitalize(), n)
    return n.strip() or name


SIZES = ['xl', 'l', 'm', 's']
# How wide each family's display face sets a character, relative to the serif.
FACE_WIDTH = {'surf': 1.3, 'hostel': .82, 'trip': .85, 'ride': .8}


def name_size(name: str, family: str = '') -> str:
    """Heading size: by length, and small enough that the longest word fits a
    320 px phone (a word can't wrap)."""
    n = len(name)
    size = 0 if n <= 16 else 1 if n <= 26 else 2 if n <= 38 else 3
    longest = max((len(w) for w in name.split()), default=0) * FACE_WIDTH.get(family, 1.0)
    size = max(size, 3 if longest >= 13 else 2 if longest >= 9.5 else 1 if longest >= 7.5 else 0)
    return SIZES[size]


def ucfirst(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


_env.filters['ucfirst'] = ucfirst


def nice_amenity(a: str) -> str:
    return {'Free Wi-Fi': 'Free Wi-Fi', 'Air-conditioned': 'Air conditioning', 'Accessible': 'Step-free access',
            'Free breakfast': 'Breakfast included', 'Paid breakfast': 'Breakfast available'}.get(a, a)


# With no usable photo of their own, the hero is the nearest real place of these kinds.
HERO_KINDS = {
    'Safari jeep operators': ('wildlife', 'lake'),
    'Whale watching, boat & lagoon tours': ('beach', 'lake', 'wildlife', 'island'),
    'Diving & snorkelling': ('island', 'beach', 'surf'),
    'Surf camps & surf schools': ('surf', 'beach'), 'Surf shops & board rental': ('surf', 'beach'),
    'Hostels & surf hostels': ('surf', 'beach', 'viewpoint'),
    'Tea estate tours & trekking': ('tea', 'hike', 'viewpoint', 'waterfall'),
    'Resorts & boutique hotels': ('beach', 'viewpoint', 'lake', 'tea'),
    'Villas & holiday rentals': ('beach', 'viewpoint', 'lake', 'tea'),
    'Guest houses & homestays': ('beach', 'viewpoint', 'lake', 'garden'),
    'Restaurants & beach clubs': ('beach', 'lake', 'viewpoint'),
    'Cafés': ('viewpoint', 'beach', 'garden'),
    'Yoga, Ayurveda & spas': ('garden', 'beach', 'lake'),
}


def context(lead: Dict[str, Any], assets: str = '/previewsite-assets') -> Dict[str, Any]:
    from .render import INFO_PACK_LK, ASSET_SRC
    from .leads import slugify
    cat = lead.get('tourism_category') or 'Tour operators & travel agents'
    family = copy.FAMILY.get(cat, 'local')
    words = copy.CATEGORY[cat]
    slug = lead['slug']
    info = town_info(lead.get('search_town') or '')
    det = data.details(lead['id'])
    lat, lng = det.get('lat'), det.get('lng')
    near = data.nearby(lat, lng, lead.get('search_town') or '', limit=6)
    beach = data.nearest(lat, lng, ('beach', 'surf'), 20) or next((a for a in near if a['kind'] in ('beach', 'surf')), None)
    surf = data.nearest(lat, lng, ('surf',), 25)
    town = info['town']
    name = clean_name(lead['name'], town)
    fills = {'name': name, 'town': town, 'region': info['region'] or 'Sri Lanka',
             'beach': (beach['name'] if beach else f'the beach at {town}') if 'coast' in info['tags'] or beach
             else (near[0]['name'] if near else town),
             'category': (lead.get('category') or cat).lower().capitalize()}

    inland = 'coast' not in info['tags'] and not (beach and beach.get('km') is not None and beach['km'] < 8)
    if family == 'trip':
        paper, ink, accent, deep, soft = copy.TRIP_PALETTE[cat]
    else:
        paper, ink, accent, deep, soft = pick(copy.PALETTES[family], slug)
    display, body, weight = copy.FONTS[family]

    photos = [dict(picture(ph['file'].rsplit('.', 1)[0], ph.get('web'), 'photos', photo_url(ph['file']), ph.get('w') or 1600, ph.get('h') or 1067),
                   own=True) for ph in data.shown_photos(lead)]
    near = [dict(a, pic=place_picture(a)) for a in near]
    variant = _seed(slug + 'layout') % 2
    own_inline = None
    hero = photos[0] if photos else None
    sharp = bool(hero) and hero['src_w'] >= FULL_BLEED_MIN
    if hero and not sharp and family == 'stay':
        variant = 1                      # framed beside the words, never stretched
    elif hero and not sharp and family in ('trip', 'dine') and near:
        own_inline, hero = hero, None    # a landmark fills the screen, their photo sits by the intro
    if hero is None and near:
        likes = HERO_KINDS.get(cat, ())
        spot = next((a for k in likes for a in near if a['kind'] == k), near[0])
        near = [spot] + [a for a in near if a is not spot]
        hero = dict(near[0]['pic'], place=near[0])
    rating, reviews = lead.get('rating') or det.get('rating'), lead.get('reviews') or det.get('reviews') or 0
    rated = bool(rating and rating >= 4.0 and reviews >= 5)
    booking = copy.BOOKING_BY_CATEGORY.get(cat, copy.BOOKING[family])
    ride_to = town
    credits = [a for a in near if a.get('image')]
    if hero and hero.get('place') and hero['place'] not in credits:
        credits.append(hero['place'])

    ctx = {
        'lead': lead, 'slug': slug, 'family': family, 'category': cat, 'cat_slug': slugify(cat, 40),
        'variant': variant, 'own_inline': own_inline,
        'paper': paper, 'ink': ink, 'accent': accent, 'accent_ink': ink_on(accent), 'deep': deep, 'soft': soft,
        'display_font': display, 'body_font': body, 'display_weight': weight,
        'name': name, 'town': town, 'region': info['region'], 'district': info['district'],
        'headline': fill(pick(words['headlines'], slug + 'h'), fills),
        'intro': fill(pick(words['intro_inland'] if inland and words.get('intro_inland') else words['intro'], slug + 'i'), fills),
        'offer': [(fill(t, fills), fill(d, fills)) for t, d in (words.get('offer_inland') if inland and words.get('offer_inland') else words.get('offer', []))],
        'itinerary': [(fill(t, fills), fill(d, fills)) for t, d in words.get('itinerary', [])],
        'included': words.get('included', []),
        'nav': words['nav'], 'special': words['special'], 'booking': booking,
        'surf_video': 'surf-chameleon' if (STATIC / 'video/ride-lg.mp4').exists() else '',
        'hero_sizes': ('100vw' if family in ('trip', 'dine') or (family == 'stay' and variant == 0)
                       else '(min-width: 900px) 55vw, 100vw' if family == 'stay'
                       else '(min-width: 980px) 1200px, 92vw' if family == 'ride'
                       else '(min-width: 980px) 45vw, 92vw' if family == 'local'
                       else '(min-width: 980px) 560px, 92vw'),
        'hero': hero, 'photos': photos, 'near': near, 'surf_break': surf, 'beach': beach,
        'amenities': [nice_amenity(a) for a in det.get('amenities', [])][:10],
        'price': det.get('price', ''), 'checkin': det.get('checkin', ''), 'hours': nice_hours(det.get('hours') or []),
        'season': season_for(info, cat, lead['name']),
        'airport': airport_drive(lat, lng) if lat is not None else '',
        'ride_to': ride_to,
        'rated': rated, 'rating': f'{rating:g}' if rating else '', 'reviews_fmt': f'{reviews:,}',
        'address': re.sub(r'\s*https?://\S+,?\s*', ' ', lead.get('address') or '').strip(' ,'), 'maps_link': maps_link(lead),
        'phone': lead.get('phone') or '', 'phone_display': display_phone(lead.get('phone') or ''),
        'wa': 'https://wa.me/' + (lead.get('phone') or '').lstrip('+'),
        'credits': credits,
        'assets': assets, 'lk': f'{assets}/{LK_ASSETS}', 'version': static_version(),
        'icons': f"{assets}/preview-icons.svg",
        'brand': config.BRAND, 'brand_url': config.SITE_URL,
        'phone_href': config.PHONE_HREF, 'brand_phone': config.PHONE_DISPLAY,
        'whatsapp_href': config.WHATSAPP_HREF, 'whatsapp_display': config.WHATSAPP_DISPLAY,
        'domain_hint': f"{slugify(name, 30).replace('-', '')}.lk",
        'info_pack': INFO_PACK_LK if (ASSET_SRC / INFO_PACK_LK).exists() else '',
        'checkout_url': (f"{config.CHECKOUT_PATH}?" + urllib.parse.urlencode({'site': slug, 'b': lead['name']})
                         if config.CHECKOUT_PATH else ''),
        'year': date.today().year,
        'name_size': name_size(name, family),
        'monogram': ''.join(w[0] for w in re.findall(r'[A-Za-z]+', name)[:2]).upper() or name[:1],
    }
    return ctx


def render(lead: Dict[str, Any], assets: str = '/previewsite-assets') -> str:
    return _env.get_template('tourism.html.j2').render(**context(lead, assets=assets))


def is_tourism(lead: Dict[str, Any]) -> bool:
    return lead.get('country') == 'LK' and lead.get('industry') == 'Tourism' and bool(lead.get('tourism_category'))


def sync_assets(site_dir: Path, leads: List[Dict[str, Any]]) -> Dict[str, int]:
    """Copy css/js/fonts, the businesses' photos and the attraction photos
    these pages use into <site>/public/previewsite-assets/lk/. Photos no page
    uses any more are removed."""
    import shutil
    from PIL import Image
    root = site_dir / config.ASSETS_DIR / LK_ASSETS
    for f in STATIC.iterdir():
        if f.is_file() and f.suffix in ('.css', '.js'):
            (root).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, root / f.name)
    if (STATIC / 'video').is_dir():
        (root / 'video').mkdir(parents=True, exist_ok=True)
        keep = {f.name for f in (STATIC / 'video').iterdir() if f.is_file()}
        for f in (STATIC / 'video').iterdir():
            dst = root / 'video' / f.name
            if f.is_file() and (not dst.exists() or dst.stat().st_size != f.stat().st_size):
                shutil.copyfile(f, dst)
        for f in (root / 'video').iterdir():   # clips from earlier builds
            if f.is_dir():
                shutil.rmtree(f)
            elif f.name not in keep:
                f.unlink()
    (root / 'fonts').mkdir(parents=True, exist_ok=True)
    for f in (STATIC / 'fonts').glob('*.woff2'):
        shutil.copyfile(f, root / 'fonts' / f.name)
    want = {'photos': {}, 'places': {}}  # published name -> source file
    for lead in leads:
        det = data.details(lead['id'])
        for ph in data.shown_photos(lead):
            files = ((ph.get('web') or {}).get('files') or {})
            stem = ph['file'].rsplit('.', 1)[0]
            if files:
                for w in files:
                    want['photos'][data.web_name(stem, int(w))] = data.WEB / data.web_name(stem, int(w))
            else:
                want['photos'][ph['file']] = data.PHOTOS / ph['file']
        for a in data.nearby(det.get('lat'), det.get('lng'), lead.get('search_town') or '', limit=6):
            files = ((a['image'].get('web') or {}).get('files') or {})
            if files:
                for w in files:
                    n = data.web_name('place-' + a['id'], int(w))
                    want['places'][n] = data.WEB / n
            else:
                n = a['image']['file'].rsplit('.', 1)[0] + '.webp'
                want['places'][n] = data.ATTRACTION_IMG / a['image']['file']
    copied = removed = 0
    for folder, files in want.items():
        (root / folder).mkdir(parents=True, exist_ok=True)
        for name, src in files.items():
            dst = root / folder / name
            if dst.exists() or not src.exists():
                continue
            if name.endswith('.avif') or src.suffix == '.webp':
                shutil.copyfile(src, dst)
            else:  # an attraction photo with no sharp build yet
                img = Image.open(src).convert('RGB')
                img.save(dst, 'WEBP', quality=72, method=4)
            copied += 1
        for f in (root / folder).iterdir():
            if f.name not in files:
                f.unlink()
                removed += 1
    want_photos, want_places = want['photos'], want['places']
    return {'photos': len(want_photos), 'places': len(want_places), 'copied': copied, 'removed': removed}
