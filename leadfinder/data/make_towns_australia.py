"""Build data/au_localities.csv and data/towns_australia.csv.

    python data/make_towns_australia.py SUBURBS_CSV POSTCODES_CSV

Sources (both public, downloaded October 2026):
  SUBURBS_CSV    github.com/michalsn/australian-suburbs  data/suburbs.csv
                 every gazetted suburb/town with population, postcode, centre point
  POSTCODES_CSV  github.com/matthewproctor/australianpostcodes  australian_postcodes.csv
                 for the ABS SA4 region names ("Far West and Orana", "Mid North Coast")

au_localities.csv   all ~15,000 localities; geo.nearest() labels pin-only businesses with it
towns_australia.csv the search centres for a nationwide sweep, one row per town

Picking search centres: a Maps search for "plumber in X" returns the
businesses around X, so the centres need to be spread like the population.
Localities are taken biggest first, and one is skipped when a bigger one
already sits within 3.5 km (capital-city metro areas) or 12 km (everywhere
else). Towns the 2026 Victoria sweep already searched (data/towns_victoria.csv)
count as taken but are left out of the file.
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_POPULATION = 1000
METRO_SPACING_KM = 3.5
REGIONAL_SPACING_KM = 12.0


def km(lat1, lng1, lat2, lng2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def load_regions(path: Path) -> dict:
    """(LOCALITY, STATE, postcode) and (LOCALITY, STATE) → SA4 name."""
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            sa4 = (r.get("sa4name") or "").strip()
            if not sa4 or r.get("type") not in ("Delivery Area", ""):
                continue
            loc, st = r["locality"].strip().upper(), r["state"].strip().upper()
            out.setdefault((loc, st, r["postcode"].strip().zfill(4)), sa4)
            out.setdefault((loc, st), sa4)
    return out


def main(suburbs_csv: str, postcodes_csv: str) -> None:
    regions = load_regions(Path(postcodes_csv))
    rows = []
    with open(suburbs_csv, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            st = (r["state"] or "").strip()
            if st not in ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"):
                continue
            try:
                lat, lng = float(r["lat"]), float(r["lng"])
            except ValueError:
                continue
            name = r["suburb"].strip()
            pc = (r["postcode"] or "").strip().zfill(4)
            region = (regions.get((name.upper(), st, pc)) or regions.get((name.upper(), st))
                      or r["statistic_area"].replace("Rest of ", "Regional "))
            rows.append({
                "locality": name, "state": st, "postcode": pc, "lat": round(lat, 5), "lng": round(lng, 5),
                "population": int(float(r["population"] or 0)), "region": region,
                "metro": r["statistic_area"].startswith("Greater") or st == "ACT",
                "lga": r["local_goverment_area"].strip(),
            })

    loc_path = HERE / "au_localities.csv"
    with loc_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["locality", "state", "postcode", "lat", "lng", "population", "region"])
        for r in sorted(rows, key=lambda r: (r["state"], r["locality"])):
            w.writerow([r["locality"], r["state"], r["postcode"], r["lat"], r["lng"], r["population"], r["region"]])

    # Towns the Victoria sweep already covered.
    done = set()
    vic_file = HERE / "towns_victoria.csv"
    if vic_file.exists():
        for row in csv.reader(vic_file.read_text(encoding="utf-8-sig").splitlines()):
            if row and row[0] and not row[0].startswith("#") and row[0].lower() != "town":
                done.add(row[0].strip().lower())

    by_name = {}
    for r in rows:
        by_name.setdefault((r["locality"].lower(), r["state"]), []).append(r)

    taken = []   # (lat, lng, metro)
    centres = []
    for r in rows:
        if r["state"] == "VIC" and r["locality"].lower() in done:
            taken.append(r)
    for r in sorted(rows, key=lambda r: -r["population"]):
        if r["population"] < MIN_POPULATION:
            break
        spacing = METRO_SPACING_KM if r["metro"] else REGIONAL_SPACING_KM
        if any(abs(t["lat"] - r["lat"]) < 0.2 and km(t["lat"], t["lng"], r["lat"], r["lng"]) < spacing
               for t in taken):
            continue
        taken.append(r)
        centres.append(r)

    # Name each centre so Google can't mistake it: "Dubbo, NSW", or with the
    # postcode when the state has two places of that name.
    out = []
    for r in centres:
        town = f"{r['locality']}, {r['state']}"
        if len(by_name[(r["locality"].lower(), r["state"])]) > 1:
            town += f" {r['postcode']}"
        out.append((town, r))

    # Priority: biggest first across the whole country, so a stopped run has
    # covered every state's main towns rather than all of NSW and nothing else.
    for i, (_, r) in enumerate(sorted(out, key=lambda t: -t[1]["population"])):
        r["rank"] = i
    towns_path = HERE / "towns_australia.csv"
    with towns_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["town", "region", "state", "priority", "population", "lat", "lng", "metro"])
        for town, r in sorted(out, key=lambda t: t[1]["rank"]):
            w.writerow([town, r["region"], r["state"], r["rank"] + 1, r["population"], r["lat"], r["lng"],
                        "metro" if r["metro"] else "regional"])

    by_state = {}
    for _, r in out:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    print(f"{len(rows)} localities → {loc_path.name}")
    print(f"{len(out)} search centres → {towns_path.name}  {by_state}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
