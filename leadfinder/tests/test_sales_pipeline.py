"""Offline tests for the sales pipeline (cleaning, classifying, rendering).

    python tests/test_sales_pipeline.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Never the real pipeline or the shared database in .env (DATABASE_URL): a throwaway SQLite file.
os.environ["PIPELINE_DB"] = str(Path(tempfile.mkdtemp()) / "pipeline.db")

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

    from pipeline.importer import upsert
    # A second Google listing with the same phone (a Facebook-only twin).
    twin = dict(b, key="pid:twin", score=99, address="9 Other St, Ocean Grove VIC 3226", kind="cleaning")
    def forget(con):
        con.execute("DELETE FROM events WHERE slug IN (SELECT slug FROM leads WHERE phone = ?)", (a["phone"],))
        con.execute("DELETE FROM leads WHERE phone = ?", (a["phone"],))

    with db.connect() as con:
        forget(con)
        upsert(con, [a])
        slug = con.execute("SELECT slug FROM leads WHERE phone = ?", (a["phone"],)).fetchone()[0]
        check("add-only skips a tracked business", upsert(con, [twin], add_only=True), (0, 0))
        check("add-only leaves its details alone",
              con.execute("SELECT address, kind FROM leads WHERE slug = ?", (slug,)).fetchone()[:],
              (a["address"], a["kind"]))
        check("a normal import refreshes them", upsert(con, [twin]), (0, 1))
        forget(con)


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
    from pipeline.render import media
    from pipeline.content import KIND_COPY, KINDS as ALL_KINDS
    check("a kind without its own photo uses the theme's", media("nail-salon", "beauty")["about"], "beauty")
    check("removalists never get the cleaning video", media("removalist", "cleaning")["video"], "")
    check("kind copy only for real kinds", set(KIND_COPY) <= set(ALL_KINDS), True)
    wash = render({**lead, "kind": "car-wash", "theme": "auto", "category": "Car wash"})
    check("car washes get car-wash words, not the mechanic's", ("A clean car" in wash, "Honest work." in wash), (True, False))


def test_selection():
    print("\nPicking the next previews")
    import tempfile
    from pipeline import publish
    from pipeline.content import KIND_GROUPS, expand_kinds
    from pipeline.leads import business_key, is_chain
    check("every blue-collar kind is a real kind", set(KIND_GROUPS["blue-collar"]) <= set(KINDS), True)
    check("groups and kinds mix", expand_kinds(["blue-collar", "vet"])[-1], "vet")
    try:
        expand_kinds(["plumbers"])
        check("unknown kind is an error", "no error", "ValueError")
    except ValueError:
        check("unknown kind is an error", "ValueError", "ValueError")
    check("franchises", [is_chain(n) for n in ("Jim's Mowing", "Colac Toyota Service Workshop", "APCO EasyWash")],
          [True, True, True])
    check("not franchises", [is_chain(n) for n in ("Geelong Tyre Services (Formerly Beaurepaires Geelong)",
                                                   "Toyota Specialist Repairs", "Fordham Plumbing", "Thrifty Auto Electrics")],
          [False, False, False, False])
    check("one business, several towns", business_key("Mr Magic Carwash Shepparton", "Shepparton"),
          business_key("Mr Magic Car Wash", "Warrnambool"))
    check("different businesses stay apart", business_key("On Time Pest Control", "Echuca") == business_key("On Time Plumbing", "Echuca"), False)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.db"
        rows = (("bob", "Bob's Plumbing", "plumber", "Geelong", 90, "new"),
                ("bob-2", "Bob's Plumbing", "plumber", "Ballarat", 88, "new"),
                ("jims", "Jim's Mowing Geelong", "lawn-mowing", "Geelong", 95, "new"),
                ("sparky", "Sparky Sam", "electrician", "Geelong", 80, "new"),
                ("sparky-2", "Sparky Sam", "electrician", "Torquay", 85, "new"),
                ("nails", "Pearl Nails", "nail-salon", "Geelong", 99, "new"))
        with db.connect(path) as con:
            for slug, name, kind, suburb, score, stage in rows:
                con.execute("INSERT INTO leads (slug, key, name, kind, suburb, grade, stage, created_at, updated_at, score) "
                            "VALUES (?, ?, ?, ?, ?, 'Hot', ?, ?, ?, ?)", (slug, slug, name, kind, suburb, stage, db.now(), db.now(), score))
            con.execute("UPDATE leads SET stage = 'preview_hosted' WHERE slug = 'sparky'")
            check("blue-collar only, no franchise, one per business, none already live",
                  publish.select_new(con, ["Hot"], None, kinds=expand_kinds(["blue-collar"])), ["bob"])
            check("limit counts what's picked", publish.select_new(con, ["Hot"], 1), ["nails"])
    _campaign_check()


def _campaign_check():
    """campaign.run with the network parts faked: publish moves the picked leads on, verify finds them live."""
    from pipeline import campaign, publish
    from pipeline.content import expand_kinds
    with db.connect() as con:
        for slug, name, kind, score in (("pipes", "Pipes Plumbing", "plumber", 90), ("wires", "Wires Electrical", "electrician", 85),
                                        ("mow", "Mow Co", "lawn-mowing", 80), ("salon", "Hair Salon X", "hair-salon", 99)):
            con.execute("INSERT INTO leads (slug, key, name, kind, suburb, grade, stage, created_at, updated_at, score) "
                        "VALUES (?, ?, ?, ?, 'Geelong', 'Hot', 'new', ?, ?, ?)", (slug, slug, name, kind, db.now(), db.now(), score))
    calls = {"published": [], "packs": []}

    def fake_publish(grades, limit, kinds, log):
        with db.connect() as c:
            picked = publish.select_new(c, grades, limit, kinds=kinds)
            for slug in picked:
                db.set_stage(c, slug, "preview_created")
        calls["published"].append(picked)
        return {"pushed": True}

    def fake_verify(slugs, log):
        with db.connect() as c:
            for slug in slugs:
                db.advance(c, slug, "preview_hosted")

    saved = (publish.publish, publish.verify, documents.save_many, campaign.time.sleep)
    publish.publish, publish.verify = fake_publish, fake_verify
    documents.save_many = lambda jobs, log=None: calls["packs"].append([l["slug"] for _, l in jobs]) or {"made": jobs, "failed": []}
    campaign.time.sleep = lambda s: None
    try:
        report = campaign.run(expand_kinds(["blue-collar"]), ["Hot"], batches=3, size=2, enrich_first=False, log=lambda m: None)
    finally:
        publish.publish, publish.verify, documents.save_many, campaign.time.sleep = saved
    check("campaign: batches of the next blue-collar leads, then stops when none are left",
          calls["published"], [["pipes", "wires"], ["mow"]])
    check("campaign: a website pack for every new preview", calls["packs"], [["pipes", "wires"], ["mow"]])
    check("campaign: report per batch, all live", [(r["published"], r["not_live"]) for r in report], [(2, []), (1, [])])


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


def test_codes():
    print("\nPreview codes")
    from pipeline.leads import preview_code
    check("first word", preview_code("Reddis"), "reddis")
    check("first word of a long name", preview_code("Muscletek Handyman Services"), "muscletek")
    check("short first word grows", preview_code("Got You Nails & Beauty"), "gotyou")
    check("a trade word alone isn't a code", preview_code("Barber One Shop"), "barberone")
    check("taken → add the next word", preview_code("Urban Barber Co.", {"urban"}), "urbanbarber")
    check("every word taken → numbered", preview_code("Urban", {"urban"}), "urban2")
    check("lowercase letters and digits only", preview_code("Café O'Brien's & Co"), "cafeobriens")


def test_team():
    print("\nTeam: sign-in, one lead at a time")
    import tempfile
    saved = db.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        db.DB_PATH = Path(tmp) / "t.db"
        try:
            _team_checks()
        finally:
            db.DB_PATH = saved
    # The same again on Postgres (the shared database), when there's one to test on:
    #   docker run -d -e POSTGRES_PASSWORD=pg -p 127.0.0.1:54329:5432 postgres:17
    #   TEST_DATABASE_URL=postgresql://postgres:pg@127.0.0.1:54329/postgres python tests/test_sales_pipeline.py
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        print("\nTeam, on Postgres")
        _use_postgres(url)
        try:
            _team_checks()
        finally:
            _use_postgres("")


def _use_postgres(url):
    """Point the pipeline at an empty Postgres database ("" = back to SQLite)."""
    from pipeline import auth
    if db._POOL is not None:
        db._POOL.close()
    db._POOL, db._PG_READY, db.DATABASE_URL, auth._enabled = None, False, url, False
    if url:
        import psycopg
        with psycopg.connect(url, autocommit=True) as c:
            c.execute("DROP TABLE IF EXISTS texts, events, leads, users CASCADE")


def _team_checks():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pipeline import auth, web
    app = FastAPI()
    app.include_router(web.router)
    auth.install(app)

    with db.connect() as con:
        for slug, stage in (("a", "preview_hosted"), ("b", "preview_hosted"), ("c", "contacted"), ("d", "new")):
            con.execute("INSERT INTO leads (slug, key, name, phone, phone_display, stage, created_at, updated_at, score) "
                        "VALUES (?, ?, ?, '+61412345678', '0412 345 678', ?, ?, ?, 90)",
                        (slug, slug, slug.upper(), stage, db.now(), db.now()))
    check("no users, own machine: open as before",
          TestClient(app, base_url="http://localhost").get("/pipeline/api/leads").json()["total"], 4)
    check("no users, through a tunnel: refused", TestClient(app).get("/pipeline/api/leads").status_code, 403)

    with db.connect() as con:
        for username, name, role in (("boss", "Boss", "admin"), ("sam", "Sam", "rep"), ("ana", "Ana", "rep")):
            con.execute("INSERT INTO users (username, name, role, pw_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                        (username, name, role, auth.hash_password("pw-" + username), db.now()))
    anon = TestClient(app)
    check("signed out: API says 401", anon.get("/pipeline/api/leads").status_code, 401)
    r = anon.get("/pipeline", follow_redirects=False)
    check("signed out: page goes to sign-in", (r.status_code, r.headers["location"]), (303, "/login?next=/pipeline"))
    r = anon.post("/login", data={"username": "sam", "password": "nope"}, follow_redirects=False)
    check("wrong password: no session", (r.status_code, auth.COOKIE in r.cookies), (200, False))

    def signin(username):
        c = TestClient(app)
        c.post("/login", data={"username": username, "password": "pw-" + username}, follow_redirects=False)
        return c
    sam, ana, boss = signin("sam"), signin("ana"), signin("boss")
    free = sam.get("/pipeline/api/leads").json()["leads"]
    check("rep sees the free, callable leads", sorted(l["slug"] for l in free), ["a", "b", "c"])
    check("…without phone numbers", {l["phone"] for l in free}, {""})
    check("rep can't open a lead they haven't taken", sam.get("/pipeline/api/leads/a").status_code, 403)
    check("rep can't publish", sam.post("/pipeline/api/publish", json={}).status_code, 403)
    check("rep can't use the lead finder", sam.get("/api/health").status_code, 403)

    check("take a lead", sam.post("/pipeline/api/leads/a/claim").json()["owner"], "sam")
    mine = sam.get("/pipeline/api/leads").json()["leads"]
    check("while working: that lead and nothing else, with its number",
          [(l["slug"], l["phone"]) for l in mine], [("a", "+61412345678")])
    check("can't take a second", sam.post("/pipeline/api/leads/b/claim").status_code, 409)
    check("other reps don't see it", sorted(l["slug"] for l in ana.get("/pipeline/api/leads").json()["leads"]), ["b", "c"])
    check("…or take it", ana.post("/pipeline/api/leads/a/claim").status_code, 409)
    check("done needs a logged call first", sam.post("/pipeline/api/leads/a/done").status_code, 409)
    check("rep can't mark it paid", sam.post("/pipeline/api/leads/a/stage", json={"stage": "paid"}).status_code, 403)
    lead = sam.post("/pipeline/api/leads/a/call", json={"outcome": "no_answer"}).json()
    check("call logged under the rep's name", (lead["stage"], lead["history"][0]["who"]), ("contacted", "Sam"))
    check("done", sam.post("/pipeline/api/leads/a/done").status_code, 200)
    check("next: free leads again", sorted(l["slug"] for l in sam.get("/pipeline/api/leads").json()["leads"]), ["b", "c"])
    check("…and it stays theirs", [l["slug"] for l in sam.get("/pipeline/api/leads?mine=true").json()["leads"]], ["a"])
    check("not open once done", sam.get("/pipeline/api/leads/a").status_code, 403)

    check("admin sees everything", boss.get("/pipeline/api/leads").json()["total"], 4)
    check("admin filters by owner", [l["slug"] for l in boss.get("/pipeline/api/leads?owner=sam").json()["leads"]], ["a"])
    check("admin reassigns", boss.post("/pipeline/api/leads/a/owner", json={"owner": "ana"}).json()["owner_name"], "Ana")
    check("rep can't reassign", sam.post("/pipeline/api/leads/b/owner", json={"owner": "sam"}).status_code, 403)
    check("admin calling a free lead makes it theirs",
          boss.post("/pipeline/api/leads/b/call", json={"outcome": "voicemail"}).json()["owner"], "boss")

    with db.connect() as con:
        db.claim(con, "c", "ana", "Ana", web.QUEUE_SQL)
    try:
        with db.connect() as con:
            con.execute("UPDATE leads SET owner = 'ana', working_since = ? WHERE slug = 'a'", (db.now(),))
        check("database refuses two at once", "allowed", "refused")
    except db.IntegrityError:
        check("database refuses two at once", "refused", "refused")
    # Sending the preview, and handing an interested business to sales@.
    check("rep can't email a customer", ana.post("/pipeline/api/leads/c/sent", json={"via": "email", "to": "x@y.au"}).status_code, 403)
    lead = ana.post("/pipeline/api/leads/c/sent", json={"via": "request", "to": "owner@c.com.au"}).json()
    check("preview email asked of sales@", lead["history"][0]["detail"],
          "Asked sales@dunous.com to email the preview to owner@c.com.au")
    check("rep can't download the website pack", ana.get("/pipeline/api/leads/c/docs/pack.pdf").status_code, 403)
    check("hand-over needs the customer's email", ana.post("/pipeline/api/leads/c/handover", json={"email": ""}).status_code, 400)
    lead = ana.post("/pipeline/api/leads/c/handover", json={"email": "owner@c.com.au", "package": "Starter"}).json()
    check("hand-over: email saved, now interested",
          (lead["email"], lead["stage"]), ("owner@c.com.au", "interested"))
    check("hand-over logged for sales@",
          any(h["kind"] == "handover" and "sales@dunous.com" in h["detail"] and h["who"] == "Ana" for h in lead["history"]), True)
    check("rep can't mark an invoice sent", ana.post("/pipeline/api/leads/c/stage", json={"stage": "invoice_sent"}).status_code, 403)

    # Texts: the rep asks, someone with the DuNous phone sends.
    with db.connect() as con:
        con.execute("UPDATE leads SET mobile = 1 WHERE slug = 'c'")
        con.execute("INSERT INTO users (username, name, role, pw_hash, created_at) VALUES ('oz', 'Oz', 'texter', ?, ?)",
                    (auth.hash_password("pw-oz"), db.now()))
    oz = signin("oz")
    text = {"body": "Hi, it's Ana from DuNous (we just spoke). Here's your website."}
    check("text needs their yes", ana.post("/pipeline/api/leads/c/text", json=text).status_code, 400)
    check("text queued", ana.post("/pipeline/api/leads/c/text", json={**text, "consent": True}).status_code, 200)
    check("not twice", ana.post("/pipeline/api/leads/c/text", json={**text, "consent": True}).status_code, 409)
    check("reps can't see the texts", ana.get("/pipeline/api/texts").status_code, 403)
    queue = oz.get("/pipeline/api/texts").json()["texts"]
    check("texter sees it, with the rep's name", [(t["business"], t["rep"], t["status"]) for t in queue], [("C", "Ana", "pending")])
    check("texter can't see leads", oz.get("/pipeline/api/leads").status_code, 403)
    r = oz.get("/pipeline", follow_redirects=False)
    check("texter's home is the texts page", (r.status_code, r.headers.get("location")), (303, "/pipeline/texts"))
    check("sent", oz.post(f"/pipeline/api/texts/{queue[0]['id']}/sent").status_code, 200)
    check("only once", oz.post(f"/pipeline/api/texts/{queue[0]['id']}/sent").status_code, 409)
    oz.post(f"/pipeline/api/texts/{queue[0]['id']}/stop")
    with db.connect() as con:
        check("STOP → do not contact", db.get(con, "c")["stage"], "do_not_contact")

    with db.connect() as con:
        con.execute("UPDATE users SET pw_hash = ? WHERE username = 'sam'", (auth.hash_password("new"),))
    check("new password signs them out", sam.get("/pipeline/api/leads").status_code, 401)


def test_sri_lanka():
    print("\nSri Lanka pipeline (separate from Australia)")
    import tempfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pipeline import auth, sri_lanka, web
    check("LK phone normaliser", [sri_lanka.phone_lk(p) for p in ("077 123 4567", "+94 11 234 5678", "0094712345678", "+61412345678")],
          ["+94771234567", "+94112345678", "+94712345678", ""])
    check("Instagram/Facebook is social (no own site)", [sri_lanka.site_status("https://instagram.com/salon"),
                                                         sri_lanka.site_status("https://facebook.com/cafe"),
                                                         sri_lanka.site_status("https://booking.com/hotel/lk/x"),
                                                         sri_lanka.site_status("https://ownsite.lk")],
          ["social", "social", "directory", "real"])
    areas = {"Colombo, Colombo District": {"district": "Colombo", "province": "Western"}}
    raw_salon = {"name": "Colombo Glow Salon", "phone": "077 123 4567", "address": "12 Galle Rd, Colombo, Sri Lanka",
                 "lat": 6.9, "lng": 79.85, "website": "https://instagram.com/colomboglow", "category": "Beauty salon",
                 "search_town": "Colombo, Colombo District", "reviews": 45, "rating": 4.8, "claimed": True, "place_id": "lk1"}
    cand = sri_lanka.candidate(raw_salon, "b-lk", areas)
    check("Instagram-only salon is a Sri Lanka candidate", (cand["sector"], cand["website_status"], cand["country"]),
          ("Beauty & bridal", "social", "LK"))
    raw_mechanic = dict(raw_salon, name="Raja Motor Mechanic", category="Auto repair shop", place_id="lk2")
    check("non-target older trade (motor mechanic) excluded", sri_lanka.candidate(raw_mechanic, "b-lk", areas), None)
    raw_own_site = dict(raw_salon, website="https://colomboglow.lk", place_id="lk3")
    check("business with proper website excluded", sri_lanka.candidate(raw_own_site, "b-lk", areas), None)

    tourist = sri_lanka.tourist_towns()
    seg = lambda cats, name="", town="Mirissa, Matara District": sri_lanka.tourism_segment(cats, name, town, tourist)
    check("tourist towns exclude Colombo, the airport and regional hubs",
          ["Mirissa, Matara District" in tourist, "Ella, Badulla District" in tourist,
           "Colombo, Colombo District" in tourist, "Katunayake, Gampaha District" in tourist,
           "Matara, Matara District" in tourist], [True, True, False, False, False])
    check("tourism segments follow the inspiration brief", [
        seg(["Surf school"]), seg(["Whale watching tour agency"]), seg(["Guest house", "Restaurant"]),
        seg(["Travel agency", "Wildlife and safari park"], town="Kurunegala, Kurunegala District"),
        seg(["Travel agency"], "Mirissa Whale Watching Tours"), seg(["Cafe"]),
        seg(["Cafe"], town="Kurunegala, Kurunegala District"), seg(["Beauty salon", "Facial spa"]),
        seg(["Cake shop", "Culinary school"], town="Wattala, Gampaha District"),
        seg(["Service establishment"], "Ella Hiking Guides", "Ella, Badulla District"),
        seg(["Coworking space"], town="Colombo, Colombo District"), seg(["Gem shop"]),
    ], [
        ("Tourism", "Surf camps & surf schools"), ("Tourism", "Whale watching, boat & lagoon tours"),
        ("Tourism", "Guest houses & homestays"), ("Tourism", "Safari jeep operators"),
        ("Tourism", "Whale watching, boat & lagoon tours"), ("Tourism", "Cafés"),
        ("Other", ""), ("Other", ""), ("Other", ""),
        ("Tourism", "Tea estate tours & trekking"), ("Other", ""), ("Tourism", "Gem, jewellery & souvenir shops"),
    ])
    check("every tourism category has a rule", set(sri_lanka.TOURISM_CATEGORIES) >= {
        "Resorts & boutique hotels", "Villas & holiday rentals", "Surf camps & surf schools", "Cafés",
        "Restaurants & beach clubs", "Yoga, Ayurveda & spas", "Whale watching, boat & lagoon tours",
        "Safari jeep operators", "Diving & snorkelling", "Scooter, tuk-tuk & airport transfers",
        "Cooking classes & local experiences", "Hostels & surf hostels", "Surf shops & board rental",
        "Coworking & coliving", "Tea estate tours & trekking"}, True)
    gem = sri_lanka.candidate(dict(raw_salon, name="Mirissa Moonstones", category="Gem shop", categories=["Gem shop"],
                                   search_town="Mirissa, Matara District", place_id="lk5"), "b-lk", sri_lanka.towns())
    check("tourism-only category in a tourist town imports as Tourism",
          (gem["industry"], gem["tourism_category"], gem["sector"], gem["search_district"]),
          ("Tourism", "Gem, jewellery & souvenir shops", "Retail & lifestyle", "Matara"))
    check("salon in Colombo is a non-tourism lead", (cand["industry"], cand["tourism_category"]), ("Other", ""))
    pairs = sri_lanka.tourism_pairs()
    check("tourism sweep: whale searches only in whale towns, no restaurants in Colombo",
          ({p["town"] for p in pairs if p["business_type"] == "whale watching"} <= {
              t for t, r in sri_lanka.towns().items() if "whale" in (r.get("tags") or "")},
           any(p["town"].startswith("Colombo") and p["business_type"] == "restaurant" for p in pairs),
           any(p["town"].startswith("Colombo") and p["business_type"] == "tour operator" for p in pairs)),
          (True, False, True))

    lk_doc = documents.html("pack", sri_lanka.doc_lead(cand))
    check("Sri Lanka website pack has 5 pages", lk_doc.count('<section class="page'), 5)
    check("Sri Lanka website pack uses LKR pricing & discounts",
          all(s in lk_doc for s in (
              "LKR 25,000", "15% off first year domain and hosting",
              "LKR 39,000", "50% off first year domain and hosting",
              "LKR 69,000", "First year domain and hosting free",
              "from LKR 120,000", "LKR 12,000 a year", "BRN / NIC", "colomboglowsalon.lk",
          )),
          True)
    check("Sri Lanka website pack excludes AUD/ABN",
          any(s in lk_doc for s in ("Australian dollars", "Australian Consumer Law")),
          False)

    saved_lk = sri_lanka.DB_PATH
    saved_env = os.environ.get("SRI_LANKA_DB")
    with tempfile.TemporaryDirectory() as tmp:
        sri_lanka.DB_PATH = Path(tmp) / "lk.db"
        os.environ["SRI_LANKA_DB"] = str(sri_lanka.DB_PATH)
        try:
            app = FastAPI()
            app.include_router(web.router)
            auth.install(app)
            with db.connect() as con:
                con.execute("DELETE FROM users")
                for username, role in (("boss", "admin"), ("sam", "rep"), ("kasun", "lk_rep")):
                    con.execute("INSERT INTO users (username, name, role, pw_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                                (username, username.title(), role, auth.hash_password("pw-" + username), db.now()))
            cand2 = sri_lanka.candidate(
                dict(raw_salon, name="Kandy Villa", phone="071 987 6543", category="Villa", place_id="lk4"),
                "b-lk", areas,
            )
            with sri_lanka.connect() as lk_con:
                for item in (cand, cand2):
                    item_row = dict(item, imported_at=db.now(), updated_at=db.now())
                    lk_con.execute(
                        f"INSERT INTO leads ({','.join(item_row)}) VALUES ({','.join('?' for _ in item_row)})",
                        list(item_row.values()),
                    )
            anon = TestClient(app)
            check("anon redirected from Sri Lanka page", anon.get("/pipeline/sri-lanka", follow_redirects=False).status_code, 303)
            sam = TestClient(app)
            sam.post("/login", data={"username": "sam", "password": "pw-sam"}, follow_redirects=False)
            check("Australian rep blocked from Sri Lanka page", sam.get("/pipeline/sri-lanka").status_code, 403)
            check("Australian rep blocked from Sri Lanka API", sam.get("/pipeline/sri-lanka/api/leads").status_code, 403)
            kasun = TestClient(app)
            r_login = kasun.post("/login", data={"username": "kasun", "password": "pw-kasun"}, follow_redirects=False)
            check("Sri Lanka rep login redirects to /pipeline/sri-lanka",
                  (r_login.status_code, r_login.headers.get("location")), (303, "/pipeline/sri-lanka"))
            check("Sri Lanka rep can open Sri Lanka page", kasun.get("/pipeline/sri-lanka").status_code, 200)
            check("Sri Lanka rep can read Sri Lanka API", kasun.get("/pipeline/sri-lanka/api/meta").status_code, 200)
            check("Sri Lanka rep blocked from Australia page", kasun.get("/pipeline").status_code, 403)
            check("Sri Lanka rep blocked from Australia API", kasun.get("/pipeline/api/leads").status_code, 403)

            pool_leads = kasun.get("/pipeline/sri-lanka/api/leads").json()["leads"]
            check("Sri Lanka rep sees free leads without phone numbers",
                  (len(pool_leads), pool_leads[0]["phone"]), (2, ""))
            check("Sri Lanka rep can't open lead before claiming",
                  kasun.get("/pipeline/sri-lanka/api/leads/lk:lk1").status_code, 403)
            claimed = kasun.post("/pipeline/sri-lanka/api/leads/lk:lk1/claim")
            check("Sri Lanka rep claims a lead and unlocks phone",
                  (claimed.status_code, claimed.json()["phone"]), (200, "+94771234567"))
            while_working = kasun.get("/pipeline/sri-lanka/api/leads").json()["leads"]
            check("Sri Lanka rep only sees their active lead while working",
                  [r["id"] for r in while_working], ["lk:lk1"])
            check("Sri Lanka rep can't claim a second lead while working",
                  kasun.post("/pipeline/sri-lanka/api/leads/lk:lk4/claim").status_code, 409)
            check("Sri Lanka rep can't mark done before logging call",
                  kasun.post("/pipeline/sri-lanka/api/leads/lk:lk1/done").status_code, 409)
            logged = kasun.post(
                "/pipeline/sri-lanka/api/leads/lk:lk1/call",
                json={"outcome": "gatekeeper", "note": "Spoke to receptionist, gave owner mobile", "contact_name": "Dilshan", "owner_phone": "077 555 4444"},
            )
            check("Sri Lanka rep logs call + owner's phone number",
                  (logged.status_code, logged.json()["contact_name"], logged.json()["owner_phone"], logged.json()["stage"]),
                  (200, "Dilshan", "077 555 4444", "contacted"))
            check("Sri Lanka rep marks lead done after logging",
                  kasun.post("/pipeline/sri-lanka/api/leads/lk:lk1/done").status_code, 200)

            boss = TestClient(app)
            boss.post("/login", data={"username": "boss", "password": "pw-boss"}, follow_redirects=False)
            check("admin can open Sri Lanka page", boss.get("/pipeline/sri-lanka").status_code, 200)
            check("admin can read Sri Lanka API", boss.get("/pipeline/sri-lanka/api/meta").status_code, 200)
            admin_leads = boss.get("/pipeline/sri-lanka/api/leads").json()["leads"]
            check("admin sees all leads and phone numbers",
                  (len(admin_leads), bool(admin_leads[0]["phone"])), (2, True))
            check("tourism leads listed first", [r["id"] for r in admin_leads], ["lk:lk4", "lk:lk1"])
            check("industry filter: tourism only",
                  [r["id"] for r in boss.get("/pipeline/sri-lanka/api/leads?industry=Tourism").json()["leads"]], ["lk:lk4"])
            check("industry filter: non-tourism only",
                  [r["id"] for r in boss.get("/pipeline/sri-lanka/api/leads?industry=Other").json()["leads"]], ["lk:lk1"])
            check("tourism type filter",
                  boss.get("/pipeline/sri-lanka/api/leads?tourism_category=Villas+%26+holiday+rentals").json()["total"], 1)
            lk_meta = boss.get("/pipeline/sri-lanka/api/meta").json()
            check("meta counts tourism leads by type",
                  (lk_meta["tourism"], dict(lk_meta["tourism_categories"])["Villas & holiday rentals"]), (1, 1))
            export_csv = boss.get("/pipeline/sri-lanka/api/export.csv?industry=Tourism").text
            check("export carries the tourism segment",
                  ("industry,tourism_category" in export_csv, "Kandy Villa" in export_csv, "Colombo Glow" in export_csv),
                  (True, True, False))
        finally:
            sri_lanka.DB_PATH = saved_lk
            if saved_env is None:
                os.environ.pop("SRI_LANKA_DB", None)
            else:
                os.environ["SRI_LANKA_DB"] = saved_env


def main() -> int:
    test_phones()
    test_location()
    test_classify()
    test_import()
    test_render()
    test_selection()
    test_documents()
    test_dncr()
    test_stages()
    test_codes()
    test_team()
    test_sri_lanka()
    print(f"\n{'─' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 62}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
