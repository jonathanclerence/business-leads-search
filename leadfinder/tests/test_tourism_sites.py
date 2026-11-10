"""Sri Lanka tourism preview sites: every category renders, the copy rules
hold on every page, names and hours are tidied, flyers are never the hero.

    .venv/bin/python tests/test_tourism_sites.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["PIPELINE_DB"] = str(Path(tempfile.mkdtemp()) / "pipeline.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import tourism_copy as copy, tourism_data as data, tourism_site as site  # noqa: E402
from pipeline.sri_lanka import TOURISM_CATEGORIES, tourism_segment  # noqa: E402

PASS, FAIL = [], []
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅]")


def check(label, got, want):
    (PASS if got == want else FAIL).append(label)
    print(("  ok   " if got == want else "  FAIL ") + label + ("" if got == want else f"\n         got  {got!r}\n         want {want!r}"))


def visible(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def fake_details(lead_id):
    return {"lat": 5.9485, "lng": 80.4718, "amenities": ["Free Wi-Fi", "Air-conditioned", "Pool"], "price": "LKR 9,500",
            "checkin": "Check-in time: 2:00 pm", "hours": [["Tuesday", "7AM–7PM"], ["Monday", "Closed"]],
            "photo_files": [{"file": "x-0.webp", "w": 1600, "h": 1067, "text_chars": 0, "text_area": 0},
                            {"file": "x-1.webp", "w": 960, "h": 640, "text_chars": 400, "text_area": 0.2}]}


def lead_for(cat, i=0):
    return {"id": f"lk:0x{i:x}:0x1", "slug": f"test-{i}", "name": "SUNSET SURF HOUSE (PVT) LTD", "category": "Hotel",
            "tourism_category": cat, "industry": "Tourism", "country": "LK", "search_town": "Mirissa, Matara District",
            "search_district": "Matara", "address": "12 Beach Rd, Mirissa 81740, Sri Lanka", "phone": "+94771234567",
            "rating": 4.7, "reviews": 128, "code": "TEST"}


def main():
    print("Tourism preview sites")
    check("every tourism category has a family and words", sorted(c for c in TOURISM_CATEGORIES if c not in copy.FAMILY or c not in copy.CATEGORY), [])
    real = data.details
    data.details = fake_details
    try:
        problems = []
        for i, cat in enumerate(TOURISM_CATEGORIES):
            html = site.render(lead_for(cat, i))
            text = visible(html)
            for bad in copy.BANNED:
                if bad in (html if bad in ("—", "–") else text.lower() if bad.isalpha() or " " in bad else text):
                    problems.append(f"{cat}: {bad!r}")
            if EMOJI.search(html):
                problems.append(f"{cat}: emoji")
            if "Sunset Surf House" not in html or "PVT" in text:
                problems.append(f"{cat}: name not tidied")
            if "x-1.webp" in html:
                problems.append(f"{cat}: flyer photo used")
            if 'class="glass nav-pill"' not in html or 'id="pv-sheet"' not in html or "noindex" not in html:
                problems.append(f"{cat}: chrome missing")
        check("all categories render within the copy rules", problems, [])
        surf = site.render(lead_for("Surf camps & surf schools", 99))
        check("surf sites have the chameleon", "data-chameleon" in surf, True)
        check("non-surf sites do not", "data-chameleon" in site.render(lead_for("Cafés", 98)), False)
        stay = site.render(lead_for("Resorts & boutique hotels", 97))
        check("stays show the Google nightly price", "From LKR 9,500 a night" in stay, True)
        check("stays show the airport drive", "Bandaranaike Airport" in stay, True)
    finally:
        data.details = real
    check("names tidied", [site.clean_name(n, t) for n, t in [
        ("YARL BIKE RENTS (PVT) LTD", "Jaffna"), ("Yala Tiger Safari ( Yala, Lunugamvehera National Park, Udawalawe)", "Yala"),
        ("Pasijou - restaurant, coworking, cinema, yoga", "Weligama"), ("Happy Tours All Taxi Servise & Bikes Rent @ Ahangama", "Ahangama")]],
        ["Yarl Bike Rents", "Yala Tiger Safari", "Pasijou", "Happy Tours All Taxi Servise"])
    check("hours: Monday first, no dashes", site.nice_hours([["Tuesday", "7AM–7PM"], ["Monday", "Closed"]]),
          [["Monday", "Closed"], ["Tuesday", "7 am to 7 pm"]])
    check("flyers detected", [data.is_flyer({"text_chars": 118, "text_area": .14}), data.is_flyer({"text_chars": 8, "text_area": .001})], [True, False])
    check("chains skipped", [bool(data.LK_CHAINS.search(n)) for n in ("Cinnamon Red", "Jetwing Lagoon", "Coco Hostels Weligama", "Dindigul Thalappakatti")],
          [True, True, False, True])
    check("travel times read naturally", [data.travel(0.6), data.travel(8), data.travel(40)], ["8 min walk", "20 min by tuk-tuk", "1.8 h by car"])
    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
