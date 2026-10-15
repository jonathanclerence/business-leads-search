"""Turning scraped rows into clean, callable leads.

Everything here is pure (no I/O) so it's easy to test: country checks, phone
formatting, slugs, suburb parsing, and mapping Google's 600+ categories onto
the ~70 business kinds the preview templates know how to write for.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional, Tuple

from .content import KINDS

AU_STATES = ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "ACT", "NT")
_AU_ADDRESS = re.compile(r"(?:,\s*)?([^,]*?)\s+(VIC|NSW|QLD|SA|WA|TAS|ACT|NT)\s+(\d{4})\b")


# ---------------------------------------------------------------- location
def is_australian(address: str, phone: str) -> bool:
    """Google puts the country on every address. With no address (mobile and
    service-area businesses), a +61 number is the tell."""
    address = (address or "").strip()
    if address:
        return address.endswith("Australia") or bool(_AU_ADDRESS.search(address))
    return normalise_phone(phone).startswith("+61")


def parse_address(address: str) -> Tuple[str, str, str, str]:
    """→ (street, suburb, state, postcode). Blank parts when unknown."""
    a = re.sub(r",?\s*Australia\s*$", "", (address or "").strip())
    m = None
    for m in _AU_ADDRESS.finditer(a):
        pass  # last match wins: the suburb/state/postcode block is at the end
    if not m:
        return a, "", "", ""
    street = a[: m.start()].strip(" ,")
    return street, m.group(1).strip(" ,"), m.group(2), m.group(3)


def short_address(address: str) -> str:
    return re.sub(r",?\s*Australia\s*$", "", (address or "").strip())


# ------------------------------------------------------------------ phones
def normalise_phone(raw: str) -> str:
    """Any AU format → E.164 (+61…). Non-AU numbers come back unchanged."""
    s = re.sub(r"[^\d+]", "", raw or "")
    if not s:
        return ""
    if s.startswith("+"):
        return s
    if s.startswith("61") and len(s) == 11:
        return "+" + s
    if s.startswith("0") and len(s) == 10:
        return "+61" + s[1:]
    if s.startswith(("13", "18")) and len(s) in (6, 10):
        return "+61" + s
    return s


def display_phone(e164: str) -> str:
    """+61412345678 → 0412 345 678, +61352211234 → (03) 5221 1234."""
    if not e164.startswith("+61"):
        return e164
    n = e164[3:]
    if n.startswith(("1300", "1800")) and len(n) == 10:
        return f"{n[:4]} {n[4:7]} {n[7:]}"
    if n.startswith("13") and len(n) == 6:
        return f"{n[:2]} {n[2:4]} {n[4:]}"
    if n.startswith("4") and len(n) == 9:
        return f"0{n[:3]} {n[3:6]} {n[6:]}"
    if len(n) == 9:
        return f"(0{n[0]}) {n[1:5]} {n[5:]}"
    return e164


def is_mobile(e164: str) -> bool:
    return e164.startswith("+614") and len(e164) == 12


# ------------------------------------------------------------------- slugs
def slugify(text: str, maxlen: int = 48) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = t.lower().replace("&", " and ").replace("'", "").replace("’", "")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if len(t) > maxlen:
        t = t[:maxlen].rsplit("-", 1)[0]
    return t or "business"


def place_id(maps_url: str) -> str:
    """The ChIJ… place id buried in a Google Maps place URL, if present."""
    m = re.search(r"!19s(ChIJ[\w-]+)", maps_url or "")
    return m.group(1) if m else ""


# ------------------------------------------------------------------- kinds
# Checked in order against the lower-cased Google category. First match wins,
# so specific patterns ("dog day care", "auto electric") come before the
# general ones ("day care", "electric").
_KIND_RULES = [
    (r"barber", "barber"),
    (r"nail", "nail-salon"),
    (r"hair|stylist", "hair-salon"),
    (r"tattoo|piercing", "tattoo"),
    (r"day spa|^spa$", "day-spa"),
    (r"massage|remedial|myotherap", "massage"),
    (r"beaut|lash|brow|wax|skin care|cosmetic|tanning|make-?up", "beauty-salon"),
    (r"acupunct|chinese medicine", "acupuncture"),
    (r"naturopath|herbal|wellness|homeopath|kinesiolog|reiki", "naturopath"),
    (r"vet|animal hospital", "vet"),
    (r"groom", "pet-grooming"),
    (r"dog walk", "dog-walker"),
    (r"pet|kennel|boarding|dog day care|dog train|cattery", "pet-sitter"),
    (r"physio|physical therap|osteopath|occupational therap|exercise physiolog", "physio"),
    (r"chiropract", "chiropractor"),
    (r"podiatr|foot", "podiatrist"),
    (r"dent|orthodont", "dentist"),
    (r"optom|optician|eye", "optometrist"),
    (r"psycholog|counsel|psychotherap|mental health", "psychologist"),
    (r"speech", "speech-pathologist"),
    (r"medical|general practitioner|doctor", "medical"),
    (r"pilates", "pilates"),
    (r"yoga", "yoga"),
    (r"gym|fitness cent", "gym"),
    (r"personal trainer|fitness|boot ?camp", "personal-trainer"),
    (r"dance", "dance-school"),
    (r"music|guitar|piano|singing|vocal|drum", "music-teacher"),
    (r"swim", "swim-school"),
    (r"child ?care|day care|kindergarten|preschool|early learning", "childcare"),
    (r"tutor|educat|learning cent", "tutoring"),
    (r"driving|driver", "driving-school"),
    (r"windscreen|windshield|auto glass", "windscreen"),
    (r"tyre|tire|wheel alignment", "tyres"),
    (r"auto electric", "auto-electrician"),
    (r"panel|body shop|smash|auto restoration|spray paint", "panel-beater"),
    (r"detail", "car-detailing"),
    (r"car wash", "car-wash"),
    (r"mechanic|auto repair|car repair|truck repair|diesel|auto parts|towing|motorcycle", "mechanic"),
    (r"plumb|gas fitt|hot water|drain", "plumber"),
    (r"electric", "electrician"),
    (r"locksmith", "locksmith"),
    (r"appliance|refrigerator repair|washing machine", "appliance-repair"),
    (r"air condition|hvac|heating|refrigerat", "air-conditioning"),
    (r"pest|termite", "pest-control"),
    (r"carpet|tile clean|upholster", "carpet-cleaning"),
    (r"clean|maid|pressure wash|gutter|laundr", "cleaning"),
    (r"moving|removal|relocation", "removalist"),
    (r"skip|waste|rubbish|garbage|junk", "skip-bin"),
    (r"tree|arborist|stump", "tree-removal"),
    (r"landscap|garden cent|nursery", "landscaping"),
    (r"lawn|mow", "lawn-mowing"),
    (r"garden", "gardening"),
    (r"paint", "painter"),
    (r"handy|property maint|carpent|contractor|builder|construct|glazier|glass|excavat|concret|fenc|roof|tiler|renovat", "handyman"),
    (r"photo", "photographer"),
    (r"celebrant|wedding", "celebrant"),
    (r"florist|flower", "florist"),
    (r"cater", "caterer"),
    (r"bakery|cake|patisser|donut|bread", "bakery"),
    (r"butcher|meat", "butcher"),
    (r"fish|seafood|chips", "fish-and-chips"),
    (r"pizza", "pizza"),
    (r"winery|vineyard|wine", "winery"),
    (r"brew|beer|distill", "brewery"),
    (r"cafe|café|coffee|espresso|brunch|tea house", "cafe"),
    (r"restaurant|takeaway|takeout|kebab|noodle|bistro|diner|grill|sushi|burger|chicken|^bar$|pub", "restaurant"),
    (r"bookkeep", "bookkeeper"),
    (r"account|tax", "accountant"),
    (r"mortgage|loan|finance|broker", "mortgage-broker"),
    (r"phone|cell", "phone-repair"),
    (r"computer|laptop|it support|software", "computer-repair"),
]
_KIND_RULES_RE = [(re.compile(p), k) for p, k in _KIND_RULES]

# The business types the scraper searched for, used when Google's category is
# missing or unhelpful ("Store", "Add website").
_SEARCH_TYPE_KIND = {
    "hair salon": "hair-salon", "barber shop": "barber", "nail salon": "nail-salon",
    "beauty salon": "beauty-salon", "day spa": "day-spa", "massage therapist": "massage",
    "remedial massage": "massage", "pet grooming": "pet-grooming", "dog grooming": "pet-grooming",
    "mobile mechanic": "mobile-mechanic", "mechanic": "mechanic", "physiotherapist": "physio",
    "chiropractor": "chiropractor", "podiatrist": "podiatrist", "dentist": "dentist",
    "driving school": "driving-school", "tattoo studio": "tattoo", "personal trainer": "personal-trainer",
    "pilates studio": "pilates", "yoga studio": "yoga", "veterinary clinic": "vet",
    "optometrist": "optometrist", "acupuncture": "acupuncture", "naturopath": "naturopath",
    "psychologist": "psychologist", "speech pathologist": "speech-pathologist",
    "car detailing": "car-detailing", "car wash": "car-wash", "tyre shop": "tyres",
    "auto electrician": "auto-electrician", "panel beater": "panel-beater",
    "windscreen repair": "windscreen", "lawn mowing": "lawn-mowing", "gardening service": "gardening",
    "landscaping": "landscaping", "tree removal": "tree-removal", "pest control": "pest-control",
    "carpet cleaning": "carpet-cleaning", "cleaning service": "cleaning", "handyman": "handyman",
    "plumber": "plumber", "electrician": "electrician", "locksmith": "locksmith",
    "painter and decorator": "painter", "air conditioning service": "air-conditioning",
    "appliance repair": "appliance-repair", "computer repair": "computer-repair",
    "phone repair": "phone-repair", "photographer": "photographer",
    "wedding photographer": "photographer", "marriage celebrant": "celebrant", "caterer": "caterer",
    "swim school": "swim-school", "dance school": "dance-school", "music teacher": "music-teacher",
    "tutoring service": "tutoring", "childcare centre": "childcare", "dog walker": "dog-walker",
    "pet sitter": "pet-sitter", "removalist": "removalist", "skip bin hire": "skip-bin",
    "bookkeeper": "bookkeeper", "accountant": "accountant", "mortgage broker": "mortgage-broker",
    "cafe": "cafe", "restaurant": "restaurant", "bakery": "bakery", "butcher": "butcher",
    "florist": "florist", "pizza shop": "pizza", "fish and chips": "fish-and-chips",
    "brewery": "brewery", "winery": "winery",
}


def classify(category: str, search_type: str, name: str = "") -> str:
    """→ a key of content.KINDS ("local" when nothing fits)."""
    kind = ""
    cat = (category or "").strip().lower()
    for rx, k in _KIND_RULES_RE:
        if cat and rx.search(cat):
            kind = k
            break
    if not kind:
        kind = _SEARCH_TYPE_KIND.get((search_type or "").strip().lower(), "local")
    if kind == "mechanic" and "mobile" in (name or "").lower():
        kind = "mobile-mechanic"
    return kind if kind in KINDS else "local"


def theme_for(kind: str) -> str:
    return KINDS.get(kind, KINDS["local"])["theme"]


def clean_category(category: str, kind: str) -> str:
    """Google's label, unless it's one of its placeholder prompts."""
    c = (category or "").strip()
    if not c or c.lower() in {"add website", "add hours", "store", "park", "repair service"}:
        return KINDS.get(kind, KINDS["local"])["label"]
    return c


def to_int(v: object) -> Optional[int]:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def to_float(v: object) -> Optional[float]:
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def region_lookup(rows: Dict[str, str], town: str) -> str:
    return rows.get((town or "").strip().lower(), "")
