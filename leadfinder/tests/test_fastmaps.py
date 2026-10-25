"""Offline tests for the fast HTTP engine, website classification, the
nearest-locality lookup and the Australia-wide lead database.

    python tests/test_fastmaps.py

The fixture is a real "plumber in Dubbo, NSW" search response (October 2026)
cut to six businesses; the sixth was edited to be unclaimed and Facebook-only.
If Google changes the response layout, the parser tests here fail first.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Never the real pipeline or the shared database in .env (DATABASE_URL): a throwaway SQLite file.
import os  # noqa: E402
os.environ["PIPELINE_DB"] = os.path.join(tempfile.mkdtemp(), "pipeline.db")

from leadfinder import database, fastmaps, geo, websites  # noqa: E402
from leadfinder.batch import BatchConfig, BatchRunner  # noqa: E402
from leadfinder.scoring import score_lead  # noqa: E402
from leadfinder.scraper import BlockedError  # noqa: E402
from leadfinder.store import BatchStore  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "maps_search_dubbo_plumber.txt"
PASS, FAIL = [], []


def check(name, got, want):
    if got == want:
        PASS.append(name)
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL.append(name)
        print(f"  \033[31m✗\033[0m {name}\n      got:  {got!r}\n      want: {want!r}")


def test_websites():
    print("\nWebsite classification")
    check("blank is none", websites.classify(""), "none")
    check("facebook page is social", websites.classify("https://m.facebook.com/Some-Biz-123/"), "social")
    check("instagram is social", websites.classify("instagram.com/biz"), "social")
    check("linktree is social", websites.classify("https://linktr.ee/biz"), "social")
    check("yellow pages is a directory", websites.classify("https://www.yellowpages.com.au/x"), "directory")
    check("fresha is a booking page", websites.classify("https://www.fresha.com/a/x"), "booking")
    check("business.site is dead", websites.classify("https://acme.business.site/"), "dead")
    check("wixsite is a free builder", websites.classify("https://bob.wixsite.com/plumbing"), "builder")
    check("google sites is a free builder", websites.classify("https://sites.google.com/view/x"), "builder")
    check("own domain is real", websites.classify("https://www.mattdiamondplumbing.com.au/"), "real")
    check("facebook-only is not an own site", websites.has_own_site("https://facebook.com/x"), False)
    check("lookalike domain isn't facebook", websites.classify("https://notfacebook.com.au"), "real")


def test_parse():
    print("\nParsing a Maps search response")
    items = fastmaps.parse(FIXTURE.read_text())
    check("six businesses", len(items), 6)
    first = items[0]
    check("name", first.name, "Mainline Plumbing & Civil")
    check("primary category", first.category, "Plumber")
    check("all categories kept", len(first.categories) > 3, True)
    check("phone as displayed", first.phone, "0423 627 149")
    check("website", first.website, "https://www.mainlineplumbingandcivil.com.au/")
    check("rating", first.rating, 5)
    check("reviews", first.reviews, 25)
    check("address ends in Australia", first.address, "Unit 1/5 Fletcher Cres, Dubbo NSW 2830, Australia")
    check("suburb/state/postcode", (first.suburb, first.state, first.postcode), ("Dubbo", "NSW", "2830"))
    check("hex place id", first.place_id, "0x222e95a86b4136c5:0xf9e38b51c41b1694")
    check("ChIJ id", first.google_id.startswith("ChIJ"), True)
    check("maps url carries the ChIJ id for the pipeline", f"!19s{first.google_id}" in first.maps_url, True)
    check("claimed listing", first.claimed, True)
    check("has hours", first.has_hours, True)
    check("not a service-area business", first.service_area, False)

    sab = items[2]  # Sapuppo & Sons: no street address on Google
    check("pin-only business flagged service-area", sab.service_area, True)
    check("pin-only business gets nearest locality and state", sab.state, "NSW")
    check("pin-only address is locality + state + postcode",
          sab.address.endswith("NSW 2830, Australia"), True)

    edited = items[5]
    check("unclaimed listing detected", edited.claimed, False)
    check("facebook website is social", edited.website_status, "social")
    check("social-only counts as no website", edited.has_website, False)
    check("to_dict carries website_status", edited.to_dict()["website_status"], "social")


def test_pb():
    print("\nRequest building")
    pb = fastmaps.build_pb("plumber in Dubbo, NSW, Australia", 40)
    check("query first", pb.startswith("!1splumber in Dubbo, NSW, Australia!7i20!8i40"), True)
    check("first page has no offset", "!8i" in fastmaps.build_pb("x", 0), False)
    check("delimiters stripped from the query", fastmaps.build_pb("a!b*c").startswith("!1sa b c!"), True)


def test_geo():
    print("\nNearest locality")
    n = geo.nearest(-32.2471, 148.6269)
    check("Dubbo pin → Dubbo", (n["locality"], n["state"]), ("Dubbo", "NSW"))
    check("region attached", n["region"], "Far West and Orana")
    check("Hobart pin → TAS", geo.nearest(-42.8821, 147.3272)["state"], "TAS")
    check("ocean pin → nothing", geo.nearest(-40.0, 160.0), None)
    check("London is not in Australia", geo.in_australia(51.5, -0.12), False)


def test_scoring():
    print("\nNeeds-a-site scoring")
    base = dict(category="Plumber", phone="0412 345 678", reviews=30, rating=4.8, claimed=True, has_hours=True)
    none = score_lead(dict(base, website=""))
    social = score_lead(dict(base, website="https://facebook.com/x"))
    builder = score_lead(dict(base, website="https://x.wixsite.com/y"))
    real = score_lead(dict(base, website="https://plumbing.com.au"))
    check("social-only outranks no link at all", social["score"] > none["score"], True)
    check("free-builder site sits between", real["score"] < builder["score"] < none["score"], True)
    check("why names the social page", social["why"].startswith("social page only"), True)
    landline = score_lead(dict(base, website="", phone="(02) 6884 1531"))
    check("mobile (owner-operator) scores higher", none["score"] > landline["score"], True)
    unclaimed = score_lead(dict(base, website="", claimed=False))
    check("unclaimed listing noted", "listing unclaimed" in unclaimed["why"], True)


class FakeClient:
    """Stands in for FastMapsClient: two pages for Dubbo, a block once."""

    def __init__(self, items, block_first=False):
        self.items = items
        self.block_first = block_first
        self.calls = []
        self.limiter = fastmaps.RateLimiter(100)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def search(self, query, max_results=20, keep_going=None):
        self.calls.append(query)
        if self.block_first:
            self.block_first = False
            raise BlockedError("simulated")
        return list(self.items) if "Dubbo" in query else []


async def _run(tmp: Path, client):
    cfg = BatchConfig(name="au", towns=["Dubbo, NSW", "Orange, NSW", "Bathurst, NSW"],
                      business_types=["plumber", "handyman"], provider="fast", concurrency=3,
                      rate=100, pace_seconds=0, long_break_every=0, state="", country="Australia",
                      block_backoff=(0.01, 0.01))
    store = BatchStore.create(tmp / "batches", "au", cfg.to_dict())
    runner = BatchRunner(store, cfg)
    runner._scraper = client
    runner._recycle_browser = _noop_recycle(runner, client)
    with store:
        summary = await runner.run(resume=False)
    return store, summary


def _noop_recycle(runner, client):
    async def recycle(reason="scheduled"):
        runner._scraper = client
    return recycle


def test_runner_and_database(tmp: Path):
    print("\nFast runner (3 workers) + database")
    items = fastmaps.parse(FIXTURE.read_text())
    client = FakeClient(items, block_first=True)
    store, summary = asyncio.run(_run(tmp, client))
    c = summary["counts"]
    check("every search done, the blocked one retried", c["tasks_done"], 6)
    check("6 searches + 1 retry hit the client", len(client.calls), 7)
    check("each business stored once", c["leads_total"], 6)
    check("no-website count uses website status", c["leads_no_website"],
          sum(1 for b in items if not b.has_website))

    out = tmp / "db"
    s = database.build([store.dir], out, pipeline_db=tmp / "none.db", log=lambda m: None)
    con = sqlite3.connect(out / "au_leads.db")
    statuses = {r[0] for r in con.execute("SELECT website_status FROM leads")}
    check("database holds only no-site and free-builder leads", statuses <= {"none", "social", "builder",
                                                                            "directory", "booking", "dead"}, True)
    check("call list = no own site, phone, not chains", s["call_list"],
          con.execute("SELECT COUNT(*) FROM call_list").fetchone()[0])
    check("facebook-only business is on the call list",
          con.execute("SELECT website_status FROM call_list WHERE name LIKE 'Sam Knight%'").fetchone(), ("social",))
    check("csv written", (out / "au-no-website-leads.csv").exists(), True)
    check("per-state csv written", (out / "by-state" / "NSW.csv").exists(), True)
    check("summary written", json.loads((out / "summary.json").read_text())["call_list"], s["call_list"])
    con.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="leadfinder-fast-"))
    try:
        test_websites()
        test_parse()
        test_pb()
        test_geo()
        test_scoring()
        test_runner_and_database(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'─' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 62}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
