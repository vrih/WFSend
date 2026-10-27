#!/usr/bin/env python3
"""Download the Ministry of Justice's SEND Tribunal tables for England.

Writes:
  data/moj/send_tribunal.csv  appeals registered and their outcomes, by academic year
  data/moj/manifest.json      where the data came from and when

MoJ publishes the SEND tables once a year, with the July to September release
of Tribunals statistics quarterly (usually in December). The tables cover
England only: outcomes are not published for each council. The script finds
the latest SEND file through the GOV.UK content API, so it doesn't need
updating when a new release comes out.

The file is OpenDocument (.ods), read with the standard library. Values are
copied as published, without thousands separators. "-" means zero and ".."
means not available.

Usage:
  python scripts/fetch_moj.py
"""
import csv
import datetime as dt
import io
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "moj"
GOVUK = "https://www.gov.uk"
COLLECTION = "/government/collections/tribunals-statistics"
ATTACHMENT = "SEND Tribunal Tables"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wfsend-data-fetch"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def content(path):
    return json.loads(get(f"{GOVUK}/api/content{path}"))


def latest_release():
    """The newest July to September release that has the SEND tables."""
    docs = content(COLLECTION)["links"]["documents"]
    releases = []
    for doc in docs:
        m = re.search(r"July to September (\d{4})", doc["title"])
        if m:
            releases.append((int(m.group(1)), doc["base_path"]))
    for _, path in sorted(releases, reverse=True):
        page = content(path)
        for a in page["details"].get("attachments", []):
            if a.get("title", "").startswith(ATTACHMENT):
                return page, a
    raise SystemExit(f"no '{ATTACHMENT}' attachment found in {COLLECTION}")


def sheets(ods):
    """{sheet name: [[cell text, ...], ...]} from an .ods file."""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(ods)).read("content.xml"))
    out = {}
    for sheet in root.iter(TABLE + "table"):
        rows = []
        for row in sheet.iter(TABLE + "table-row"):
            cells = []
            for c in row.findall(TABLE + "table-cell"):
                # trailing empty cells are stored once with a large repeat count
                rep = min(int(c.get(TABLE + "number-columns-repeated", 1)), 300)
                cells += [" ".join("".join(p.itertext()) for p in c.findall(TEXT + "p")).strip()] * rep
            while cells and not cells[-1]:
                cells.pop()
            rows.append(cells)
        out[sheet.get(TABLE + "name")] = rows
    return out


def year_rows(rows):
    """Rows that start with an academic year ("1 September 2024 to 31 August
    2025"), keyed by "2024/25"."""
    out = {}
    for r in rows:
        m = re.fullmatch(r"1 September (\d{4}) to 31 August (\d{4})", r[0] if r else "")
        if m:
            out[f"{m.group(1)}/{m.group(2)[2:]}"] = [v.replace(",", "") for v in r[1:]]
    return out


def check(rows, expected):
    """Stop if MoJ has changed a table's column headings."""
    text = " | ".join(" | ".join(r) for r in rows[:8])
    for heading in expected:
        if heading not in text:
            raise SystemExit(f"column heading {heading!r} not found; check the table layout")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    page, att = latest_release()
    print(f"[moj] {att['title']}: {att['url']}")
    s = sheets(get(att["url"]))

    # SEND_1: registered, all outcomes, decided, then decided split three ways
    check(s["SEND_1"], ["Registered appeals", "All outcomes", "Outcomes decided", "Decision Upheld",
                        "Decision in favour of appellant", "Decision Revised against appellant"])
    # SEND_5: the first five columns are the totals for every appeal type
    check(s["SEND_5"], ["Total outcome of appeals", "Total", "Decided", "Withdrawn / Conceded", "Withdrawn", "Conceded"])
    send1, send5 = year_rows(s["SEND_1"]), year_rows(s["SEND_5"])
    rows = []
    for year, r in send1.items():
        t = send5.get(year, [""] * 5)
        if t[0] != r[1] or t[1] != r[2]:  # both tables give all outcomes and decided
            raise SystemExit(f"SEND_1 and SEND_5 disagree for {year}: {r[1:3]} vs {t[:2]}")
        rows.append({
            "academic_year": year,
            "registered": r[0],
            "all_outcomes": r[1],
            "decided": r[2],
            "decided_upheld": r[3],
            "decided_in_favour": r[4],
            "decided_revised_against": r[5],
            "withdrawn_or_conceded": t[2],
            "withdrawn": t[3],
            "conceded": t[4],
        })
    with (OUT / "send_tribunal.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"  {len(rows)} rows -> {(OUT / 'send_tribunal.csv').relative_to(ROOT)}")

    (OUT / "manifest.json").write_text(json.dumps({
        "publisher": "Ministry of Justice",
        "title": page["title"],
        "url": GOVUK + page["base_path"],
        "published": page["first_published_at"][:10],
        "dataset": att["title"],
        "dataset_url": att["url"],
        "fetched": dt.date.today().isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
