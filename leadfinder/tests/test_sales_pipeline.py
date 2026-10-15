"""Offline tests for the sales pipeline (cleaning, classifying, rendering).

    python tests/test_sales_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db  # noqa: E402
from pipeline.content import KINDS, THEME_ABOUT  # noqa: E402
from pipeline.importer import dedupe, normalise  # noqa: E402
from pipeline.leads import (classify, display_phone, is_australian, is_mobile,  # noqa: E402
                            normalise_phone, parse_address, place_id, slugify)
from pipeline.render import render  # noqa: E402

PASS, FAIL = [], []


def check(name, got, want):
    if got == want:
        PASS.append(name)
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL.append(name)
        print(f"  \033[31m✗\033[0m {name}\n      got:  {got!r}\n      want: {want!r}")


def test_phones():
    print("\nPhones")
    check("mobile → E.164", normalise_phone("0412 345 678"), "+61412345678")
    check("landline → E.164", normalise_phone("(03) 5221 1234"), "+61352211234")
    check("already E.164", normalise_phone("+61 3 5221 1234"), "+61352211234")
    check("display mobile", display_phone("+61412345678"), "0412 345 678")
    check("display landline", display_phone("+61352211234"), "(03) 5221 1234")
    check("display 1300", display_phone("+611300123456"), "1300 123 456")
    check("foreign untouched", display_phone("+18175399484"), "+18175399484")
    check("mobile detected", is_mobile("+61412345678"), True)
    check("landline not mobile", is_mobile("+61352211234"), False)


def test_location():
    print("\nLocation")
    check("AU address", is_australian("1 Main St, Geelong VIC 3220, Australia", ""), True)
    check("US address", is_australian("960 N Walnut Creek Dr, Mansfield, TX 76063, United States", "+18175399484"), False)
    check("no address, AU phone", is_australian("", "+61405014380"), True)
    check("no address, UK phone", is_australian("", "+441803123456"), False)
    check("parse address", parse_address("Shop 14a/67 Main Hurstbridge Rd, Diamond Creek VIC 3089, Australia"),
          ("Shop 14a/67 Main Hurstbridge Rd", "Diamond Creek", "VIC", "3089"))
    check("place id from maps url",
          place_id("https://www.google.com/maps/place/X/data=!4m7!3m6!1s0x1:0x2!8m2!3d-37!4d145!16s%2Fg%2F11!19sChIJ5y2v7pg31moRhg1e0_kdH94?authuser=0"),
          "ChIJ5y2v7pg31moRhg1e0_kdH94")


def test_classify():
    print("\nClassification")
    check("barber beats hair", classify("Barber shop", "hair salon"), "barber")
    check("nail salon", classify("Nail salon", "beauty salon"), "nail-salon")
    check("dog day care is pets, not childcare", classify("Dog day care center", "pet sitter"), "pet-sitter")
    check("auto electrician before electrician", classify("Auto electrical service", "electrician"), "auto-electrician")
    check("veterinary", classify("Animal hospital", "veterinary clinic"), "vet")
    check("placeholder category falls back to search type", classify("Add website", "plumber"), "plumber")
    check("mobile mechanic from name", classify("Mechanic", "mechanic", "Dave's Mobile Mechanic"), "mobile-mechanic")
    check("unknown → local", classify("Something odd", "nothing"), "local")
    check("real but unknown category → generic, not the search type", classify("Pharmacy", "nail salon"), "local")
    check("ballet school is a dance school", classify("Ballet school", "dance school"), "dance-school")
    check("every kind has a known theme", all(k["theme"] in THEME_ABOUT for k in KINDS.values()), True)
    check("every kind has 4 services", all(len(k["services"]) == 4 for k in KINDS.values()), True)
    check("slug", slugify("Mansfield Nails & Spa"), "mansfield-nails-and-spa")
    check("slug strips accents/quotes", slugify("Café O'Brien's"), "cafe-obriens")


def _row(**kw):
    base = {"Business Name": "Pearl Nails", "Phone Number": "+61484589929", "Website Available?": "No",
            "Full Address": "3 Bay Rd, St Leonards VIC 3223, Australia", "Category": "Nail salon",
            "Search Town": "St Leonards", "Search Business Type": "nail salon", "Score": "100", "Grade": "Hot",
            "Rating": "4.7", "Review Count": "368", "Google Maps URL": "", "Why This Lead": "", "First Found": ""}
    base.update(kw)
    return base


def test_import():
    print("\nImport filters")
    regions = {"st leonards": "Bellarine"}
    lead = normalise("b1", _row(), regions)
    check("kept: AU, no site, phone", bool(lead), True)
    check("suburb parsed", lead["suburb"], "St Leonards")
    check("region from search town", lead["region"], "Bellarine")
    check("theme", lead["theme"], "beauty")
    check("has website → dropped", normalise("b1", _row(**{"Website Available?": "Yes"}), regions), None)
    check("no phone → dropped", normalise("b1", _row(**{"Phone Number": ""}), regions), None)
    check("US → dropped", normalise("b1", _row(**{"Full Address": "1 Main St, Rochester, NY 14620, United States",
                                                  "Phone Number": "+15855551234"}), regions), None)
    a = normalise("b1", _row(), regions)
    b = normalise("b2", _row(Score="80", **{"Full Address": "3 Bay Rd, St Leonards VIC 3223"}), regions)
    out = dedupe([b, a])
    check("same phone merged, best score kept", (len(out), out[0]["score"]), (1, 100))


def test_render():
    print("\nRendering")
    lead = {"slug": "pearl-nails", "name": "Pearl Nails & Co", "category": "Nail salon", "kind": "nail-salon",
            "theme": "beauty", "address": "3 Bay Rd, St Leonards VIC 3223", "suburb": "St Leonards", "state": "VIC",
            "phone": "+61484589929", "phone_display": "0484 589 929", "rating": 4.7, "reviews": 368,
            "place_id": "ChIJx", "email": None}
    html = render(lead)
    check("preview is noindex", 'name="robots" content="noindex' in html, True)
    check("preview has claim form", 'id="pv-form"' in html, True)
    check("turnstile placeholder for the edge route", "%%TURNSTILE_SITE_KEY%%" in html, True)
    check("name escaped", "Pearl Nails &amp; Co" in html, True)
    check("rating shown", "368 Google reviews" in html, True)
    check("tap to call", 'href="tel:+61484589929"' in html, True)
    final = render(lead, final=True, assets="assets")
    check("final has no preview bar", "pv-bar" in final or "pv-form" in final, False)
    check("final is indexable", "noindex" in final, False)
    check("final uses relative assets", 'href="assets/preview.css' in final, True)
    unrated = render({**lead, "rating": None, "reviews": 0})
    check("no rating → no reviews section", "Google reviews" in unrated, False)


def test_stages():
    print("\nStages")
    check("preview stages are real stages", db.PREVIEW_STAGES <= set(db.STAGE_KEYS), True)
    check("closed stages never get a preview",
          {"new", "not_interested", "do_not_contact", "live"} & db.PREVIEW_STAGES, set())


def main() -> int:
    test_phones()
    test_location()
    test_classify()
    test_import()
    test_render()
    test_stages()
    print(f"\n{'─' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 62}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
