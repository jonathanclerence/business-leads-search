"""Batch engine tests — the parts that would silently ruin an overnight run.

Covers the failure modes that actually cost you a night's work:

* a hard crash mid-batch, then resuming without re-scraping or losing leads
* a JSONL file whose last line was cut off by the crash
* the same business appearing in both "Geelong" and "Highton" (a Geelong
  suburb) and being counted once, not twice
* task ordering, so an aborted run leaves complete verticals
* scoring, filtering and the shape of the sales CSV

Runs entirely offline against a fake Google Maps.

    python tests/test_batch.py
"""

from __future__ import annotations

import asyncio
import csv
import io
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote_plus, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import leadfinder.scraper as scraper_mod  # noqa: E402
from leadfinder.batch import (  # noqa: E402
    BatchConfig,
    BatchRunner,
    build_query,
    in_country,
    load_input_list,
    load_pairs,
)
from leadfinder.scoring import category_tier, score_lead  # noqa: E402
from leadfinder.store import (  # noqa: E402
    SALES_HEADERS,
    BatchStore,
    lead_key,
    list_batches,
)

PASS, FAIL = [], []


def check(label, got, want):
    if got == want:
        PASS.append(label)
        print(f"  \033[32m✓\033[0m {label}")
    else:
        FAIL.append(label)
        print(f"  \033[31m✗\033[0m {label}\n      got:  {got!r}\n      want: {want!r}")


# ---------------------------------------------------------------------------
# Fake Google Maps with deliberate cross-town overlap.
#   Highton and Belmont are Geelong suburbs, so Google legitimately returns
#   some of the same businesses for all three. Business 3 and 4 appear in two
#   towns each — they must land in the output exactly once.
# ---------------------------------------------------------------------------
RESULTS = {
    "hair salon in Geelong":    [1, 2, 3, 4],
    "hair salon in Highton":    [3, 4, 5],
    "hair salon in Belmont":    [4, 6],
    "pet grooming in Geelong":  [7, 8],
    "pet grooming in Highton":  [8, 9],
    "pet grooming in Belmont":  [10],
    "cafe in Geelong":          [11, 12],
    "cafe in Highton":          [],          # genuinely nothing here
    "cafe in Belmont":          [13],
}

# id -> (name, category, has_website, phone, reviews, rating)
BUSINESSES = {
    1:  ("Snip & Style",      "Hair salon",       False, "03 5222 0001", 210, 4.8),
    2:  ("The Cut Above",     "Hair salon",       True,  "03 5222 0002", 95,  4.4),
    3:  ("Curl Up & Dye",     "Hair salon",       False, "03 5222 0003", 48,  4.6),
    4:  ("Shear Madness",     "Barber shop",      False, "",             12,  4.1),
    5:  ("Highton Hair Co",   "Hair salon",       False, "03 5222 0005", 30,  4.9),
    6:  ("Belmont Blow Dry",  "Beauty salon",     True,  "03 5222 0006", 8,   3.9),
    7:  ("Waggy Tails",       "Pet groomer",      False, "03 5222 0007", 150, 4.9),
    8:  ("Pawfect Grooming",  "Pet groomer",      False, "03 5222 0008", 60,  4.7),
    9:  ("The Dog House",     "Dog day care",     True,  "03 5222 0009", 20,  4.2),
    10: ("Clip & Clean",      "Pet groomer",      False, "",             0,   None),
    11: ("Bean There",        "Cafe",             False, "03 5222 0011", 400, 4.5),
    12: ("Corner Store Cafe", "Supermarket",      False, "03 5222 0012", 300, 4.0),
    13: ("Belmont Brew",      "Coffee shop",      True,  "03 5222 0013", 75,  4.3),
}


def feed_html(ids):
    cards = "".join(
        f'<div jsaction="c"><a class="hfpxzc" aria-label="{BUSINESSES[i][0]}" '
        f'href="/maps/place/B{i}/data=!4m5!3m4!1s0x{1000 + i:x}:0x{2000 + i:x}!8m2"></a></div>'
        for i in ids
    )
    return (f'<!DOCTYPE html><html><body><div role="feed">{cards}'
            f"<p>You've reached the end of the list.</p></div></body></html>")


def place_html(i):
    name, cat, has_site, phone, reviews, rating = BUSINESSES[i]
    site = f'<a data-item-id="authority" href="https://biz{i}.example.com/"></a>' if has_site else ""
    tel = (f'<button data-item-id="phone:tel:{phone}" aria-label="Phone: {phone}"></button>'
           if phone else "")
    rat = (f'<div class="F7nice"><span aria-hidden="true">{rating}</span>'
           f'<span aria-label="{reviews} reviews"></span></div>' if rating is not None else "")
    return (f'<!DOCTYPE html><html><body><div role="main">'
            f'<h1 class="DUwDvf">{name}</h1>{rat}'
            f'<button class="DkEaL">{cat}</button>'
            f'<button data-item-id="address" aria-label="Address: {i} Main St, Geelong VIC"></button>'
            f"{site}{tel}</div></body></html>")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = unquote_plus(urlparse(self.path).path)
        if path.startswith("/maps/search/"):
            query = path[len("/maps/search/"):]
            body = feed_html(RESULTS.get(query, []))
        elif path.startswith("/maps/place/B"):
            body = place_html(int(path.split("/maps/place/B")[1].split("/")[0]))
        else:
            self.send_response(404); self.end_headers(); return
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


FAST = dict(pace_seconds=0.01, pace_jitter=0.0, long_break_every=0,
            long_break_seconds=0.0, recycle_every=0, max_results=20)


# ---------------------------------------------------------------------------
def test_inputs(tmp: Path):
    print("\nInput CSV parsing")
    (tmp / "headered.csv").write_text(
        "town,region,priority\n# a comment\nGeelong,G,2\nHighton,G,1\nGeelong,G,3\n",
        encoding="utf-8")
    check("header detected + priority sorts + dupes dropped",
          load_input_list(tmp / "headered.csv", "town"), ["Highton", "Geelong"])

    (tmp / "bare.csv").write_text("Geelong\nHighton\n\nBelmont\n", encoding="utf-8")
    check("headerless single column",
          load_input_list(tmp / "bare.csv", "town"), ["Geelong", "Highton", "Belmont"])

    (tmp / "types.csv").write_text("keyword,notes\nhair salon,x\npet grooming,y\n", encoding="utf-8")
    check("alternate column name 'keyword'",
          load_input_list(tmp / "types.csv", "type"), ["hair salon", "pet grooming"])

    (tmp / "bom.csv").write_text("﻿town\nGeelong\n", encoding="utf-8")
    check("excel BOM tolerated", load_input_list(tmp / "bom.csv", "town"), ["Geelong"])

    (tmp / "pairs.csv").write_text(
        "town,business_type\nGeelong,hair salon\nGeelong,hair salon\nHighton,cafe\n",
        encoding="utf-8")
    check("explicit pairs deduped", load_pairs(tmp / "pairs.csv"),
          [{"town": "Geelong", "business_type": "hair salon"},
           {"town": "Highton", "business_type": "cafe"}])

    check("query format", build_query("pet grooming", "Geelong"), "pet grooming in Geelong")
    check("query pins state + country", build_query("plumber", "Portland", "VIC", "Australia"),
          "plumber in Portland, VIC, Australia")
    check("town with its own region keeps it", build_query("plumber", "Albury, NSW", "VIC", "Australia"),
          "plumber in Albury, NSW, Australia")

    au = "Australia"
    check("AU address kept", in_country({"address": "429 King St, Newtown NSW 2042, Australia"}, au), True)
    check("AU address without country kept", in_country({"address": "25 Treloar Ln, Pakenham VIC 3810"}, au), True)
    check("AU address without postcode kept", in_country({"address": "1 Main St, Geelong VIC"}, au), True)
    check("US address dropped", in_country({"address": "960 N Walnut Creek Dr, Mansfield, TX 76063, United States"}, au), False)
    check("UK address dropped", in_country({"address": "12 Strand, Torquay TQ1 2AA, United Kingdom"}, au), False)
    check("no address, AU phone kept", in_country({"address": "", "phone": "+61405014380"}, au), True)
    check("no address, UK phone dropped", in_country({"address": "", "phone": "+44 1803 123456"}, au), False)
    check("no country filter keeps all", in_country({"address": "x, United States"}, ""), True)

    cfg = BatchConfig(towns=["A", "B"], business_types=["x", "y"])
    check("type-major ordering keeps verticals whole",
          [(t["business_type"], t["town"]) for t in cfg.tasks()],
          [("x", "A"), ("x", "B"), ("y", "A"), ("y", "B")])


def test_scoring():
    print("\nScoring")
    check("hair salon is tier A", category_tier("Hair salon"), "A")
    check("auto repair is tier B", category_tier("Auto repair shop"), "B")
    check("cafe is tier C", category_tier("Cafe"), "C")
    check("supermarket is weak fit", category_tier("Supermarket"), "none")
    check("blank category is unknown", category_tier(""), "?")
    check("longest match wins (pet groom beats spa)",
          category_tier("Pet grooming service"), "A")

    salon = score_lead(dict(category="Hair salon", phone="03 1", website="",
                            reviews=180, rating=4.8))
    market = score_lead(dict(category="Supermarket", phone="03 1", website="",
                             reviews=400, rating=4.5))
    check("bookable no-website business is Hot", salon["grade"], "Hot")
    check("retail no-website business is not Hot", market["grade"] in ("Cool", "Cold"), True)
    check("bookable outranks retail despite fewer reviews",
          salon["score"] > market["score"], True)

    with_site = score_lead(dict(category="Hair salon", phone="03 1",
                                website="https://x.com", has_website=True,
                                reviews=180, rating=4.8))
    check("having a website drops the score hard",
          salon["score"] - with_site["score"] > 25, True)

    no_phone = score_lead(dict(category="Hair salon", phone="", website="",
                               reviews=180, rating=4.8))
    check("unreachable lead is penalised", no_phone["score"] < salon["score"], True)
    check("reason string explains itself", "no phone listed" in no_phone["why"], True)
    check("score stays within bounds",
          all(0 <= score_lead(b)["score"] <= 100 for b in [
              dict(category="Hair salon", phone="1", website="", reviews=99999, rating=5.0),
              dict(category="", phone="", website="", reviews=None, rating=None),
          ]), True)


def test_store_resilience(tmp: Path):
    print("\nStore resilience")
    store = BatchStore.create(tmp / "batches", "crashtest", {"a": 1})
    with store:
        store.add_leads([{"name": "A", "place_id": "p1", "has_website": False,
                          "phone": "1", "category": "Hair salon"}], "Geelong", "hair salon")
        store.record_task("Geelong", "hair salon", "q", "done", found=1, new_leads=1)

    # Simulate a hard kill mid-write: a truncated final line.
    with store.leads_path.open("a", encoding="utf-8") as fh:
        fh.write('{"name": "Truncated", "place_i')

    reopened = BatchStore.open(store.dir)
    check("truncated final line skipped, not fatal", len(reopened.leads), 1)
    check("completed task survived", reopened.is_done("Geelong", "hair salon"), True)
    check("case-insensitive task key", reopened.is_done("geelong", "HAIR SALON"), True)
    check("unrun task is not done", reopened.is_done("Highton", "hair salon"), False)

    check("dedupe key prefers place id",
          lead_key({"place_id": "p1", "name": "X"}), "pid:p1")
    check("dedupe key falls back to name+address",
          lead_key({"name": "Bob's Cafe", "address": "1 A St"}),
          lead_key({"name": "BOBS CAFE", "address": "1 a st."}))


async def _run_batch(store, cfg, resume=True, stop_after=None):
    runner = BatchRunner(store, cfg)
    if stop_after is not None:
        original = runner._search_one
        state = {"n": 0}

        async def flaky(query):
            if state["n"] >= stop_after:
                raise KeyboardInterrupt("simulated crash")
            state["n"] += 1
            return await original(query)

        runner._search_one = flaky
    with store:
        try:
            return await runner.run(resume=resume)
        except KeyboardInterrupt:
            return None


async def test_batch(tmp: Path):
    srv, base = serve()
    scraper_mod.build_search_url = lambda q: f"{base}/maps/search/{q}"
    root = tmp / "batches"

    # The fake Maps server keys results on the bare "x in Town" query.
    cfg = BatchConfig(name="geelong", towns=["Geelong", "Highton", "Belmont"],
                      business_types=["hair salon", "pet grooming", "cafe"],
                      state="", country="", **FAST)

    # ---------------- crash halfway ----------------
    print("\nBatch run — crash and resume")
    store = BatchStore.create(root, "geelong", cfg.to_dict())
    await _run_batch(store, cfg, resume=False, stop_after=4)

    partial = BatchStore.open(store.dir)
    done_after_crash = sum(1 for t in partial.done_tasks.values() if t["status"] == "done")
    leads_after_crash = len(partial.leads)
    check("crash left completed searches on disk", done_after_crash, 4)
    check("crash left leads on disk", leads_after_crash > 0, True)

    # ---------------- resume ----------------
    resumed = BatchStore.open(store.dir)
    summary = await _run_batch(resumed, cfg, resume=True)
    c = summary["counts"]

    check("resume completed every search", c["tasks_done"], 9)
    check("resume did not re-scrape finished work",
          sum(1 for t in resumed.done_tasks.values() if t["status"] == "done"), 9)
    check("no leads lost across the crash", len(resumed.leads) >= leads_after_crash, True)

    # ---------------- dedupe ----------------
    print("\nCross-town deduplication")
    expected_unique = len({i for ids in RESULTS.values() for i in ids})
    check("every unique business captured exactly once",
          c["leads_total"], expected_unique)
    names = [l["name"] for l in resumed.leads]
    check("no duplicate names in output", len(names), len(set(names)))
    check("business found in 2 towns is stored once",
          sum(1 for l in resumed.leads if l["name"] == "Curl Up & Dye"), 1)
    seen = {l["name"]: l.get("times_seen", 1) for l in resumed.leads}
    check("re-sightings are counted, not duplicated", seen["Shear Madness"], 3)
    check("duplicates tallied for reporting", c["duplicates"] > 0, True)

    # ---------------- website flag + scoring ----------------
    print("\nScored output")
    no_site = [l for l in resumed.leads if not l.get("has_website")]
    check("no-website count", c["leads_no_website"], len(no_site))
    check("every lead is scored", all("score" in l and "grade" in l for l in resumed.leads), True)
    ranked = sorted(resumed.leads, key=lambda l: -l["score"])
    top = ranked[0]
    check("top lead has no website", top["has_website"], False)
    check("top lead is an appointment-based vertical",
          category_tier(top["category"]), "A")
    check("top lead is the best-reviewed bookable no-site business",
          top["name"], "Snip & Style")  # 210 reviews beats Waggy Tails' 150
    check("other strong bookable leads rank near the top",
          "Waggy Tails" in [l["name"] for l in ranked[:3]], True)
    check("businesses with websites sink below the best leads",
          all(not l["has_website"] for l in ranked[:3]), True)
    market = next(l for l in resumed.leads if l["name"] == "Corner Store Cafe")
    salon = next(l for l in resumed.leads if l["name"] == "Snip & Style")
    check("supermarket ranks below salon despite more reviews",
          market["score"] < salon["score"], True)

    check("search provenance recorded", salon["search_town"], "Geelong")
    check("search type recorded", salon["search_business_type"], "hair salon")

    # ---------------- filtering + export ----------------
    print("\nSales CSV")
    hot = resumed.filtered(no_website_only=True, min_score=78)
    check("filter: hot no-website leads only",
          all(not l["has_website"] and l["score"] >= 78 for l in hot), True)
    check("filter: results sorted by score descending",
          [l["score"] for l in hot] == sorted([l["score"] for l in hot], reverse=True), True)
    check("filter by town", {l["search_town"] for l in
                             resumed.filtered(towns=["Highton"])}, {"Highton"})
    check("filter by grade", {l["grade"] for l in
                              resumed.filtered(grades=["Hot"])} <= {"Hot"}, True)
    check("filter requiring a phone drops unreachable leads",
          all(l["phone"] for l in resumed.filtered(require_phone=True)), True)

    text = resumed.export_csv_string(no_website_only=True)
    rows = list(csv.reader(io.StringIO(text)))
    check("csv header matches the sales schema", rows[0], SALES_HEADERS)
    check("csv row count matches filter", len(rows) - 1, len(no_site))
    check("csv leads with Score column", rows[0][0], "Score")
    check("csv top row is the highest-scoring lead", rows[1][2], ranked[0]["name"])
    check("csv records cross-search sightings",
          "in " in rows[[r[2] for r in rows].index("Shear Madness")][
              SALES_HEADERS.index("Also Found In")], True)
    check("csv marks websites as No", rows[1][8], "No")
    check("csv seeds a Status column for reps",
          rows[1][SALES_HEADERS.index("Status")], "New")
    check("csv carries the why-string", "no website" in rows[1][SALES_HEADERS.index("Why This Lead")], True)

    path = resumed.export_csv(no_website_only=True)
    check("csv written to disk", path.exists(), True)
    check("csv is excel-safe utf-8 BOM", path.read_bytes()[:3], b"\xef\xbb\xbf")

    # ---------------- reporting ----------------
    print("\nReporting")
    s = resumed.summary()
    check("summary reports top towns", len(s["top_towns"]) > 0, True)
    check("summary reports top business types", len(s["top_types"]) > 0, True)
    check("grades histogram present", set(c["grades"]) >= {"Hot", "Warm", "Cool", "Cold"}, True)
    check("batch discoverable in the index",
          list_batches(root)[0]["batch_id"], resumed.manifest["batch_id"])
    check("empty search recorded, not treated as failure",
          resumed.done_tasks["cafe|highton"]["status"], "done")
    check("empty search found nothing", resumed.done_tasks["cafe|highton"]["found"], 0)

    srv.shutdown()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="leadfinder-batch-"))
    try:
        test_inputs(tmp)
        test_scoring()
        test_store_resilience(tmp)
        asyncio.run(test_batch(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'─' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 62}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
