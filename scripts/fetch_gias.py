#!/usr/bin/env python3
"""Download Waltham Forest's specialist settings from Get Information About Schools (GIAS).

Writes:
  data/gias/specialist_settings.csv  every Waltham Forest special school, and every
                                     school recorded with resourced provision or an
                                     SEN unit, whatever its status (open, proposed, closed)
  data/gias/manifest.json            where the data came from and when

GIAS publishes a CSV of every establishment in England each day (about 65 MB).
Only the rows and columns the site needs are kept. Values are copied as
published, including blanks.

Usage:
  python scripts/fetch_gias.py
"""
import csv
import datetime as dt
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gias"
DOWNLOADS = "https://get-information-schools.service.gov.uk/Downloads"
# The daily "all establishment data" file behind the Downloads page, on the DfE's own GIAS host.
FILE = "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{d}.csv"
LA_CODE = "320"  # Waltham Forest
SPECIALIST = {"Resourced provision", "SEN unit", "Resourced provision and SEN unit"}
COLUMNS = [
    "URN", "EstablishmentName", "TypeOfEstablishment (name)", "EstablishmentTypeGroup (name)",
    "EstablishmentStatus (name)", "OpenDate", "CloseDate", "PhaseOfEducation (name)",
    "StatutoryLowAge", "StatutoryHighAge", "SchoolCapacity", "NumberOfPupils", "CensusDate",
    "TypeOfResourcedProvision (name)", "ResourcedProvisionCapacity", "ResourcedProvisionOnRoll",
    "SenUnitCapacity", "SenUnitOnRoll",
] + [f"SEN{i} (name)" for i in range(1, 14)]


def is_special(r):
    """Special academies and free schools are grouped with other academies, so
    go by the establishment type: "Academy special converter", "Non-maintained
    special school", "Other independent special school" and so on."""
    return "special" in r["TypeOfEstablishment (name)"].lower()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wfsend-data-fetch"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def latest():
    """Today's file is published during the morning, so fall back a few days."""
    today = dt.date.today()
    for back in range(5):
        d = today - dt.timedelta(days=back)
        url = FILE.format(d=d.strftime("%Y%m%d"))
        try:
            return d, url, get(url)
        except urllib.error.HTTPError as e:
            if e.code not in (404, 500):
                raise
    raise SystemExit("no GIAS file found for the last 5 days")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("[gias] downloading all establishments")
    day, url, raw = latest()
    reader = csv.DictReader(io.StringIO(raw.decode("cp1252")))  # GIAS files are Windows-1252
    missing = set(COLUMNS) - set(reader.fieldnames)
    if missing:
        raise SystemExit(f"GIAS columns missing: {sorted(missing)}")
    rows = [{c: r[c] for c in COLUMNS} for r in reader
            if r["LA (code)"] == LA_CODE
            and (is_special(r) or r["TypeOfResourcedProvision (name)"] in SPECIALIST)]
    rows.sort(key=lambda r: int(r["URN"]))
    path = OUT / "specialist_settings.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"  {len(rows)} rows -> {path.relative_to(ROOT)}")
    (OUT / "manifest.json").write_text(json.dumps({
        "publisher": "Department for Education",
        "title": "Get Information About Schools",
        "downloads_url": DOWNLOADS,
        "file_url": url,
        "file_date": day.isoformat(),
        "fetched": dt.date.today().isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
