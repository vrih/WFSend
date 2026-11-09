#!/usr/bin/env python3
"""Download Ofsted's latest inspection outcomes for Waltham Forest's specialist settings.

Writes:
  data/ofsted/school_inspections.csv  the latest Ofsted inspections of every school in
                                      data/gias/specialist_settings.csv that Ofsted lists
  data/ofsted/manifest.json           where the data came from and when

Ofsted publishes monthly management information on GOV.UK: a CSV of the
latest inspections of every state-funded school in England (about 16 MB),
about six weeks after the month it covers. The script finds the newest file
through the GOV.UK content API, so it doesn't need updating each month.

Schools are matched to the GIAS list by URN, so run fetch_gias.py first.
Values are copied as published, including "NULL" for blanks. The file has
three sets of columns, one for each kind of inspection: report card
inspections (from November 2025), graded inspections under the previous
framework, and ungraded inspections.

Usage:
  python scripts/fetch_ofsted.py
"""
import csv
import datetime as dt
import io
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ofsted"
GIAS = ROOT / "data" / "gias" / "specialist_settings.csv"
GOVUK = "https://www.gov.uk"
PAGE = "/government/statistical-data-sets/monthly-management-information-ofsteds-school-inspections-outcomes"
TITLE = re.compile(r"state-funded schools - latest inspections (?:- )?as at (\d{1,2} \w+ \d{4})$")
COLUMNS = [
    "URN", "School name", "Ofsted phase", "Type of education", "Local authority", "Web Link",
    # report card inspections
    "Inspection number of latest full inspection", "Inspection type", "Inspection start date", "Publication date",
    "Does the latest full inspection relate to the URN of the current school?",
    "School name at time of latest full inspection", "Category of concern", "Safeguarding standards",
    "Inclusion", "Curriculum and teaching", "Achievement", "Attendance and behaviour",
    "Personal development and wellbeing", "Early years (where applicable)",
    "Post-16 provision (where applicable)", "Leadership and governance",
    # graded inspections under the previous framework (OEIF)
    "Inspection number of latest OEIF graded inspection", "Inspection type of latest OEIF graded inspection",
    "Inspection start date of latest OEIF graded inspection", "Publication date of latest OEIF graded inspection",
    "Does the latest OEIF graded inspection relate to the URN of the current school?",
    "School name at time of latest OEIF graded inspection", "Latest OEIF category of concern",
    "Latest OEIF overall effectiveness", "Latest OEIF quality of education", "Latest OEIF behaviour and attitudes",
    "Latest OEIF personal development", "Latest OEIF effectiveness of leadership and management",
    "Latest OEIF  safeguarding is effective?", "Latest OEIF early years provision (where applicable)",
    "Latest OEIF sixth form provision (where applicable)",
    # ungraded inspections
    "Latest ungraded inspection number", "Date of latest ungraded inspection", "Ungraded inspection publication date",
    "Does the ungraded inspection relate to the URN of the current school?",
    "School name at time of the ungraded inspection", "Ungraded inspection overall outcome",
    "Most recent category of concern",
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wfsend-data-fetch"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def latest_file():
    """The newest "latest inspections" CSV on the management information page."""
    page = json.loads(get(f"{GOVUK}/api/content{PAGE}"))
    files = []
    for a in page["details"].get("attachments", []):
        m = TITLE.search(a.get("title", "").strip())
        if m and a.get("content_type") == "text/csv":
            # titles mix "31 Aug 2026" and "31 August 2026"
            day, month, year = m.group(1).split()
            as_at = dt.datetime.strptime(f"{day} {month[:3]} {year}", "%d %b %Y").date()
            files.append((as_at, a))
    if not files:
        raise SystemExit(f"no 'latest inspections' CSV found on {PAGE}")
    return page, *max(files, key=lambda f: f[0])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with GIAS.open(encoding="utf-8") as f:
        urns = {r["URN"] for r in csv.DictReader(f)}
    page, as_at, att = latest_file()
    print(f"[ofsted] downloading {att['title']}")
    raw = get(att["url"])
    reader = csv.DictReader(io.StringIO(raw.decode("cp1252")))  # Ofsted's CSVs are Windows-1252
    missing = set(COLUMNS) - set(reader.fieldnames)
    if missing:
        raise SystemExit(f"Ofsted columns missing: {sorted(missing)}")
    rows = [{c: r[c] for c in COLUMNS} for r in reader if r["URN"] in urns]
    rows.sort(key=lambda r: int(r["URN"]))
    path = OUT / "school_inspections.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"  {len(rows)} rows -> {path.relative_to(ROOT)}")
    (OUT / "manifest.json").write_text(json.dumps({
        "publisher": "Ofsted",
        "title": page["title"],
        "url": GOVUK + PAGE,
        "dataset": att["title"].strip(),
        "file_url": att["url"],
        "as_at": as_at.isoformat(),
        "fetched": dt.date.today().isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
