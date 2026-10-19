"""Offline tests for the sales pipeline (cleaning, classifying, rendering).

    python tests/test_sales_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db, documents, offer  # noqa: E402
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
    check("one 'Make it mine' button, no separate 'Request changes'", "Request changes" in html, False)
    check("link back to dunous.com", 'href="https://www.dunous.com"' in html, True)
    check("hero scene for the theme", 'data-scene="beauty"' in html, True)
    check("3D hero knows the business", 'data-kind="nail-salon"' in html and 'data-hero3d="/previewsite-assets/hero3d.js' in html, True)
    check("glass rating lens when rated", 'data-lens-rating="4.7"' in html, True)
    check("no eyebrow labels or 01/02 numbering (tasteskill)", ('class="kicker"' in html, "service-num" in html), (False, False))
    check("barbers get barber navy", 'style="--accent:#1f3a5f' in render({**lead, "kind": "barber", "theme": "hair"}), True)
    check("booking widget", 'id="booker"' in html and 'data-mode="appointment"' in html, True)
    check("removalists get the boxes scene", 'data-scene="boxes"' in render({**lead, "kind": "removalist", "theme": "cleaning"}), True)
    check("trades book quotes", 'data-mode="quote"' in render({**lead, "kind": "plumber", "theme": "trades"}), True)
    check("cafes book tables", 'data-mode="table"' in render({**lead, "kind": "cafe", "theme": "food"}), True)
    check("turnstile placeholder for the edge route", "%%TURNSTILE_SITE_KEY%%" in html, True)
    check("name escaped", "Pearl Nails &amp; Co" in html, True)
    check("rating shown", "368 Google reviews" in html, True)
    check("tap to call", 'href="tel:+61484589929"' in html, True)
    final = render(lead, final=True, assets="assets")
    check("final has no preview bar", 'class="pv-bar"' in final or "pv-form" in final, False)
    check("final is indexable", "noindex" in final, False)
    check("final uses relative assets", 'href="assets/preview.css' in final, True)
    check("theme accent applied", 'style="--accent:#b0546f' in html, True)
    check("client colour overrides theme", 'style="--accent:#123456' in render({**lead, "accent": "#123456"}), True)
    check("bad colour ignored", 'style="--accent:#b0546f' in render({**lead, "accent": "red;}"}), True)
    hours = '[["Monday", "9 am–5 pm"]]'
    quotes = '[{"text": "Lovely </script> people", "author": "Sam", "stars": 5}]'
    personal = render({**lead, "hours_json": hours, "reviews_json": quotes})
    check("hours shown", "9 am–5 pm" in personal, True)
    check("review quote escaped", "Lovely &lt;/script&gt; people" in personal, True)
    check("final keeps motion but no colour panel", ("site.js" in final and "hero.js" in final, "pv-panel" in final), (True, False))
    check("final booking really sends (sms/mail)", 'data-final="1"' in final, True)
    unrated = render({**lead, "rating": None, "reviews": 0})
    check("no rating → no reviews section", "Google reviews" in unrated, False)


def test_documents():
    print("\nDocuments")
    lead = {"slug": "urban-trim", "name": "Urban Trim", "category": "Barber shop", "kind": "barber",
            "theme": "hair", "address": "25 Treloar Ln, Pakenham VIC 3810", "suburb": "Pakenham", "state": "VIC",
            "phone": "+61410771413", "phone_display": "0410 771 413", "rating": 4.9, "reviews": 434,
            "contact_name": "Hassan Ali", "email": "hassan@example.com", "notes": "INTERNAL: owner is grumpy",
            "hours_json": '[["Monday", "9\u202fam\u20137\u202fpm"]]'}
    pack = documents.html("pack", lead)
    check("pack is 5 pages: cover, website, packages, agreement, form", pack.count('<section class="page'), 5)
    check("every price from offer.py", all(offer.money(p["price"]) in pack for p in offer.PACKAGES), True)
    check("hosting is yearly only", (offer.money(offer.HOSTING["yearly"]) + " a year" in pack, "/month" in pack, "$39<" in pack), (True, False, False))
    check("personalised: rating, reviews, their suburb", ("434" in pack, "4.9" in pack, "in Pakenham" in pack), (True, True, True))
    check("agreement points to the Terms on the site", 'href="https://www.dunous.com/terms"' in pack, True)
    check("bank transfer, no card or PayPal", ("bank transfer" in pack, "PayPal" in pack, "by card" in pack), (True, False, False))
    check("internal notes never leak into client PDFs", "grumpy" in pack, False)
    check("hours pre-filled without narrow spaces", 'data-value="Monday: 9 am–7 pm"' in pack, True)
    names = [m for m in __import__("re").findall(r'data-field="([^"]+)"', pack)]
    check("form field names unique", len(names), len(set(names)))
    check("agreement and form are one page each",
          (documents.html("agreement", lead).count('<section class="page'), documents.html("onboarding", lead).count('<section class="page')), (1, 1))
    generic = documents.html("pack")
    check("generic pack skips the website page", generic.count('<section class="page'), 4)
    check("generic pack has no business details", ("Urban Trim" in generic, "Reference" in generic), (False, False))
    check("short name drops Google keyword stuffing",
          documents.short_name("Oxley Landscaping | Gardening | Weed Control | Fencing | Decking | Paving Morwell"),
          "Oxley Landscaping")
    check("short name keeps normal names", documents.short_name("Maryborough Veterinary Practice"),
          "Maryborough Veterinary Practice")
    check("file name", documents.filename("pack", lead), "DuNous-Website-pack-urban-trim.pdf")
    if documents.GENERIC_PACK.exists():
        from pypdf import PdfReader
        have = (PdfReader(documents.GENERIC_PACK).metadata or {}).get("/DunousSource")
        check("generic pack is current (python -m pipeline docs --generic)", have, documents.generic_fingerprint())
        check("previews link the info pack", 'href="/previewsite-assets/dunous-website-pack.pdf?v=' in render(lead), True)
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("  - skipped PDF build (Playwright not installed)")
        return
    from io import BytesIO
    from pypdf import PdfReader
    msgs = []
    pdf = PdfReader(BytesIO(documents.build("agreement", lead, log=msgs.append)))
    fields = pdf.get_fields()
    check("agreement PDF: 1 page, nothing overflows", (len(pdf.pages), [m for m in msgs if "overflow" in m]), (1, []))
    check("agreement PDF: fillable, pre-filled", (fields["agr_business"].get("/V"), fields["agr_abn"].get("/V")),
          ("Urban Trim", None))
    check("agreement PDF: package tick boxes", all(fields[f"agr_pkg_{p['id']}"]["/FT"] == "/Btn" for p in offer.PACKAGES), True)
    long = {**lead, "name": "Oxley Landscaping | Gardening | Weed Control | Fencing | Decking | Pergola | Paving | Lawn care Morwell",
            "rating": None, "reviews": None, "reviews_json": None, "hours_json": None, "contact_name": None}
    msgs = []
    documents.build("pack", long, log=msgs.append)
    check("pack for a long, unrated name: nothing overflows", [m for m in msgs if "overflow" in m], [])


def test_dncr():
    print("\nDo Not Call Register")
    import tempfile
    from pipeline import dncr
    check("wash format: mobile, landline, 1300, 13", [dncr.wash_number(n) for n in
          ("+61412345678", "+61352211234", "+611300123456", "+61131450", "+18175399484")],
          ["0412345678", "0352211234", "1300123456", "131450", ""])
    parsed = dncr.parse_results("Number,Status\r\n1,0412 345 678,Y\r\n2,(03) 5221 1234,N\r\n3,61400111222, I \r\n")
    check("results: Y/N/I per number, row numbers ignored", parsed,
          {"+61412345678": "Y", "+61352211234": "N", "+61400111222": "I"})
    check("registered-only list", dncr.parse_results("0412345678\n0352211234\n", registered_only=True),
          {"+61412345678": "Y", "+61352211234": "Y"})
    try:
        dncr.parse_results("0412345678\n0352211234\n")
        check("a list without indicators isn't read as all clear", "no error", "WashError")
    except dncr.WashError:
        check("a list without indicators isn't read as all clear", "WashError", "WashError")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.db"
        with db.connect(path) as con:
            for slug, phone, stage in (("a", "+61412345678", "preview_hosted"), ("b", "+61352211234", "preview_hosted")):
                con.execute("INSERT INTO leads (slug, key, name, phone, stage, created_at, updated_at, score) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 90)", (slug, slug, slug.upper(), phone, stage, db.now(), db.now()))
            check("both need a wash", len(dncr.due(con, "calling")), 2)
        res = dncr.load_results("0412345678,Y\n0352211234,N\n0499999999,N\n", path=path)
        check("import counts", (res["on_register"], res["clear"], res["unmatched"]), (1, 1, 1))
        with db.connect(path) as con:
            check("on the register → do not contact", db.get(con, "a")["stage"], "do_not_contact")
            check("clear stays callable", (db.get(con, "b")["stage"], db.get(con, "b")["dncr"]), ("preview_hosted", "N"))
            check("washed today → nothing due", len(dncr.due(con, "calling")), 0)


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
    test_documents()
    test_dncr()
    test_stages()
    print(f"\n{'─' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 62}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
