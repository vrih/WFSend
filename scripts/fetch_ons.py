#!/usr/bin/env python3
"""Download ONS mid-year population estimates for children aged 2 to 18.

The estimates come from Nomis, the ONS's official labour market and population
statistics service, which has an API. Keeps England, London, the London
boroughs and Waltham Forest's statistical neighbours, and writes:

  data/ons/population.csv    population at 30 June by single year of age, as published
  data/ons/manifest.json     where the data came from and when

The site uses these to turn counts (EHC plans, requests) into rates per 1,000
children, so areas of different sizes can be compared.

Usage:
  python scripts/fetch_ons.py
"""
import csv
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ons"
API = "https://www.nomisweb.co.uk/api/v01/dataset/NM_2002_1"
FIRST_YEAR = 2018
AGES = range(2, 19)  # single years 2 to 18
ENGLAND, LONDON = "E92000001", "E12000007"
LONDON_BOROUGHS = [f"E090000{n:02d}" for n in range(1, 34)]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wfsend-data-fetch"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    neighbours = yaml.safe_load((ROOT / "data" / "dfe_sources.yaml").read_text())["statistical_neighbours"]["areas"]
    codes = [ENGLAND, LONDON] + LONDON_BOROUGHS + [a["code"] for a in neighbours if a["code"] not in LONDON_BOROUGHS]
    overview = json.loads(get(f"{API}.overview.json"))["overview"]
    years = [c["value"] for d in overview["dimensions"]["dimension"] if d["concept"] == "time"
             for c in d["codes"]["code"] if int(c["value"]) >= FIRST_YEAR]
    query = urllib.parse.urlencode({
        "geography": ",".join(codes),
        "date": ",".join(str(y) for y in years),
        "gender": 0,  # all people
        "c_age": ",".join(str(100 + a + 1) for a in AGES),  # Nomis codes "Age 0" as 101
        "measures": 20100,  # count, not percent
        "select": "date_name,geography_code,geography_name,c_age_name,obs_value",
    })
    url = f"{API}.data.csv?{query}"
    print("[ons] population estimates")
    rows = []
    for r in csv.DictReader(get(url).splitlines()):
        rows.append({
            "year": r["DATE_NAME"],
            "area_code": r["GEOGRAPHY_CODE"],
            "area_name": r["GEOGRAPHY_NAME"],
            "age": int(r["C_AGE_NAME"].removeprefix("Age ")),
            "population": r["OBS_VALUE"],
        })
    expected = len(codes) * len(years) * len(AGES)
    if len(rows) != expected:
        raise SystemExit(f"expected {expected} rows, got {len(rows)}")
    rows.sort(key=lambda r: (r["year"], r["area_code"], r["age"]))
    path = OUT / "population.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"  {len(rows)} rows -> {path.relative_to(ROOT)}")
    (OUT / "manifest.json").write_text(json.dumps({
        "publisher": "Office for National Statistics",
        "title": "Population estimates for England and Wales",
        "url": "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates/datasets/estimatesofthepopulationforenglandandwales",
        "dataset": overview["name"],
        "dataset_url": "https://www.nomisweb.co.uk/datasets/pestsyoala",
        "download_url": url,
        "published": overview["lastupdated"][:10],
        "latest_year": years[-1],
        "fetched": dt.date.today().isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
