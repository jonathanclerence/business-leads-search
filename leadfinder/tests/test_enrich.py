"""Offline tests for the Google Maps enrichment helpers (hours + review snippets).

    python tests/test_enrich.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.enrich import (MAX_CHARS, fallback_url, first_name, name_words, norm_ws,  # noqa: E402
                             parse_hours, parse_stars, pick_reviews, same_place, snippet_problem,
                             trim_snippet)

PASS, FAIL = [], []


def check(name, got, want):
    if got == want:
        PASS.append(name)
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL.append(name)
        print(f"  \033[31m✗\033[0m {name}\n      got:  {got!r}\n      want: {want!r}")


NNBSP = " "  # what Google puts between "9" and "AM"


def _rows(start="Thursday", **override):
    """Table rows the way Google lists them: starting today, not Monday."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    i = days.index(start)
    order = days[i:] + days[:i]
    hours = {"Monday": f"9{NNBSP}AM–5:30{NNBSP}PM", "Tuesday": f"9{NNBSP}AM–5:30{NNBSP}PM",
             "Wednesday": f"9{NNBSP}AM–5:30{NNBSP}PM", "Thursday": f"9{NNBSP}AM–7{NNBSP}PM",
             "Friday": f"9{NNBSP}AM–7{NNBSP}PM", "Saturday": f"9{NNBSP}AM–1{NNBSP}PM", "Sunday": "Closed"}
    rows = []
    for d in order:
        rows.append(override.get(d) or {"day": [d], "items": [hours[d]]})
    return {"rows": rows}


def test_hours():
    print("\nHours")
    got = parse_hours(_rows())
    check("re-ordered Monday..Sunday", [d for d, _ in got],
          ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
    check("narrow no-break space → plain space", got[0], ["Monday", "9 AM–5:30 PM"])
    check("closed day kept as shown", got[6], ["Sunday", "Closed"])
    split = parse_hours(_rows(Tuesday={"day": ["Tuesday"], "items": [f"8{NNBSP}AM–12{NNBSP}PM", "1–5 PM"]}))
    check("split shift joined", split[1], ["Tuesday", "8 AM–12 PM, 1–5 PM"])
    differ = parse_hours(_rows(Monday={"day": ["Monday", "(King's Birthday)"],
                                       "items": [f"9{NNBSP}AM–5{NNBSP}PM", "Hours might differ"]}))
    check("'hours might differ' note dropped, regular hours kept", differ[0], ["Monday", "9 AM–5 PM"])
    special = _rows(Tuesday={"day": ["Tuesday", "Melbourne Cup"], "items": ["Closed", "Holiday hours"]})
    check("holiday-only schedule this week → None", parse_hours(special), None)
    missing = _rows()
    missing["rows"] = missing["rows"][:6]
    check("a day missing → None", parse_hours(missing), None)
    check("nothing found → None", parse_hours(None), None)
    check("24 hours", parse_hours(_rows(Friday={"day": ["Friday"], "items": ["Open 24 hours"]}))[4],
          ["Friday", "Open 24 hours"])
    label = ("Monday, 9 AM to 5 PM; Tuesday, 9 AM to 5 PM; Wednesday, 9 AM to 5 PM; "
             "Thursday, 9 AM to 12 PM, 1 to 7 PM; Friday, 9 AM to 5 PM; Saturday, Closed; Sunday, Closed. "
             "Hide open hours for the week")
    from_label = parse_hours({"label": label})
    check("aria-label fallback: 'to' → en dash", from_label[0], ["Monday", "9 AM–5 PM"])
    check("aria-label fallback: split shift", from_label[3], ["Thursday", "9 AM–12 PM, 1–7 PM"])
    check("aria-label fallback: closed", from_label[6], ["Sunday", "Closed"])
    values = [f"{d}, 9 AM–5 PM" for d in ("Thursday", "Friday", "Saturday", "Sunday",
                                                     "Monday", "Tuesday", "Wednesday")]
    check("copy-button fallback", parse_hours({"values": values})[0], ["Monday", "9 AM–5 PM"])


def test_text():
    print("\nText helpers")
    check("whitespace normalised", norm_ws(" 9 AM–5 PM ‎\n"), "9 AM–5 PM")
    check("line breaks collapse", norm_ws("Love it.\n\nWill be back"), "Love it. Will be back")
    check("icon glyphs dropped", norm_ws("Copy"), "Copy")
    check("first name", first_name("Michelle Gaeb"), "Michelle")
    check("first name from initials", first_name("Kayli AB"), "Kayli")
    check("lower-case name capitalised", first_name("sam harris"), "Sam")
    check("shouty name tidied", first_name("JOHN SMITH"), "John")
    check("honorific skipped", first_name("Dr. Priya Shah"), "Priya")
    check("empty author", first_name(""), "")
    check("stars aria-label", parse_stars("5 stars"), 5)
    check("one star", parse_stars("1 star"), 1)
    check("decimal rating", parse_stars("Rated 4.0 out of 5,"), 4)
    check("slash rating", parse_stars("5/5"), 5)
    check("no stars", parse_stars("Local Guide"), None)


def test_trim():
    print("\nSnippet trimming")
    short = "Great service, really friendly team and my nails look amazing!"
    check("short text untouched", trim_snippet(short), short)
    words = ("Lovely relaxing salon with lovely staff who take their time and really care about getting "
             "every detail right for you, and the whole place is spotless and calm and smells wonderful "
             "every single visit without fail which keeps me coming back again and again")
    t = trim_snippet(words)
    check("long text ≤ max", len(t) <= MAX_CHARS, True)
    check("ends with …", t.endswith("…"), True)
    check("cut on a word boundary", words.startswith(t[:-1]) and words[len(t) - 1] == " ", True)
    check("no dangling comma before …", t[-2] not in ",;: ", True)
    sentences = ("Absolutely loved my visit today and will be back. The team were quick and gentle and "
                 "explained everything they were doing as they went along which I appreciated. After that "
                 "we chatted about holidays and the time flew by so quickly I almost missed my bus home.")
    s = trim_snippet(sentences)
    check("prefers a sentence end", s, "Absolutely loved my visit today and will be back. The team were quick "
          "and gentle and explained everything they were doing as they went along which I appreciated…")
    check("custom max", trim_snippet("one two three four five six", 15), "one two three…")


def test_filter():
    print("\nReview filter")
    own = name_words("Got You Nails & Beauty", "Diamond Creek", "Shop 3/67 Main Hurstbridge Rd, Diamond Creek VIC")
    ok = "Love my nails. The girls were super quick, but very thorough. Highly Recommend!"
    check("clean review passes", snippet_problem(ok, own), None)
    check("own name + suburb are fine",
          snippet_problem("Best nail salon in Diamond Creek, Got You Nails never disappoints.", own), None)
    check("staff first name is fine", snippet_problem("Sophia did an amazing job on my gel nails today.", own), None)
    check("price ($)", snippet_problem("Only $45 for a full set, amazing work.", own), "price")
    check("price (words)", snippet_problem("Great work and very reasonable prices too.", own), "price")
    check("price (cheap)", snippet_problem("Friendly, quick and cheaper than anywhere else.", own), "price")
    check("phone", snippet_problem("Call them on 0412 345 678 to book in, great team.", own), "phone")
    check("landline", snippet_problem("Booked over the phone (03) 9438 1234 easily.", own), "phone")
    check("email", snippet_problem("Emailed sam@example.com and they replied quickly.", own), "email")
    check("url", snippet_problem("Booked through www.example.com.au, so easy.", own), "url")
    check("competitor (named)", snippet_problem("Way nicer than Pro Nails down the road, love it here.", own),
          "competitor")
    check("competitor (comparison)", snippet_problem("So much better than my previous salon, love it.", own),
          "competitor")
    check("competitor (other salons)", snippet_problem("I have tried other nail salons and none compare.", own),
          "competitor")
    check("competitor (another shop)",
          snippet_problem("Came in to get my old nails removed, which were done at another shop.", own),
          "competitor")
    check("surname", snippet_problem("Sophia Nguyen did my nails and they look perfect.", own), "surname")
    check("title + surname", snippet_problem("Dr Patel was so gentle with our puppy, thank you.", own), "surname")
    check("title-case praise is not a name", snippet_problem("Great Service and Amazing Staff, Thank You!", own),
          None)
    check("place names are not surnames",
          snippet_problem("When I moved to the Mornington Peninsula I found my new favourite salon.", own), None)
    check("sensitive story skipped",
          snippet_problem("Went in after my dad passed away and they were so kind to me.", own), "sensitive")
    check("star count isn't a phone number", snippet_problem("5 stars from me, 10/10 would come back again.", own),
          None)


def _raw(author, stars, text, **kw):
    return {"author": author, "stars": f"{stars} stars", "text": text, "lang": "en", "truncated": False, **kw}


def test_pick():
    print("\nPicking reviews")
    own = name_words("Urban Trim", "Pakenham")
    raw = [
        _raw("Liam Ng", 4, "Good cut, quick and friendly, will be back again next month for sure."),
        _raw("Ava R", 5, "Best fade I've had in years, the boys at Urban Trim really know their stuff."),
        _raw("Noah", 5, "Too short."),
        _raw("Mia Wong", 5, "Great haircut but charged me $40 which seemed a lot for a quick trim today."),
        _raw("Ethan", 1, "Waited forever and nobody even said hello to me when I walked in the door."),
        _raw("Zoe Li", 5, "Absolutely brilliant barbers, friendly chat and a sharp cut every single time."),
        _raw("Oli", 5, "Lovely team. " * 30),
        _raw("Ava Smith", 5, "Second review from someone with the same first name should be skipped."),
        _raw("Jack", 5, "Muy buen servicio, los recomiendo totalmente a todos mis amigos.", lang="es"),
        _raw("Ruby", 5, "Great service (Translated by Google) and a lovely team who were very welcoming."),
    ]
    got = pick_reviews(raw, own)
    check("three picked", len(got), 3)
    check("5-star untrimmed first, in Google's order", [g["author"] for g in got], ["Ava", "Zoe", "Oli"])
    check("long one trimmed with …", got[2]["text"].endswith("…") and len(got[2]["text"]) <= MAX_CHARS, True)
    check("shape", sorted(got[0]), ["author", "stars", "text"])
    check("stars are ints", got[0]["stars"], 5)
    check("4-star used when 5-star run out",
          [g["author"] for g in pick_reviews(raw[:5], own)], ["Ava", "Liam"])
    check("never below 4 stars", pick_reviews([raw[4]], own), None)
    check("nothing usable → None", pick_reviews([], own), None)
    trunc = [_raw("Kim", 5, "Such a lovely experience, the team were great with my nervous little dog and …",
                  truncated=True)]
    check("un-expanded review keeps a single …", pick_reviews(trunc, own)[0]["text"],
          "Such a lovely experience, the team were great with my nervous little dog and…")
    google_cut = [_raw("Amanda", 5, "Best barber in town! All the guys here are amazing. Can highly recommend 👌 …")]
    check("Google's ' …' cut tidied", pick_reviews(google_cut, own)[0]["text"],
          "Best barber in town! All the guys here are amazing. Can highly recommend 👌…")
    odd_names = [_raw("Nothing", 5, "This place met my expectations, the lady doing my nails was so sweet."),
                 _raw("NOOB BRO", 5, "Tried a new barber today and walked out with the best cut in years."),
                 _raw("user8812", 5, "Friendly team, always on time and my car runs like new again.")]
    check("display names that aren't names skipped", pick_reviews(odd_names, own), None)


def test_misc():
    print("\nMisc")
    check("fallback url", fallback_url({"name": "K&N Barber", "address": "1 Main St, Shepparton VIC 3630",
                                        "place_id": "ChIJV3JJ"}),
          "https://www.google.com/maps/search/?api=1&query=K%26N+Barber+1+Main+St%2C+Shepparton+VIC+3630"
          "&query_place_id=ChIJV3JJ")
    check("fallback url without place id", fallback_url({"name": "Pearl nails", "address": None}),
          "https://www.google.com/maps/search/?api=1&query=Pearl+nails")
    check("same place", same_place("Got You Nails & Beauty", "Got You Nails & Beauty"), True)
    check("different place", same_place("Diamond Creek Pharmacy", "Got You Nails & Beauty"), False)
    check("case-insensitive", same_place("PBX BARBERS", "PBX Barbers"), True)


def main() -> int:
    test_hours()
    test_text()
    test_trim()
    test_filter()
    test_pick()
    test_misc()
    print(f"\n{'─' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  failed: " + ", ".join(FAIL))
    print(f"{'─' * 62}\n")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
