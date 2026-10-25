#!/usr/bin/env python3
"""Download Local Government and Social Care Ombudsman (LGSCO) data for Waltham Forest.

Writes:
  data/lgo/decisions.csv     every published decision about the council
  data/lgo/annual_stats.csv  the headline complaint statistics for each reporting year
  data/lgo/manifest.json     where the data came from and when

The Ombudsman keeps decision statements online for five years, and does not
publish every decision, so the decision counts are a minimum.

Usage:
  python scripts/fetch_lgo.py
"""
import csv
import datetime as dt
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "lgo"
SITE = "https://www.lgo.org.uk"
COUNCIL = "london-borough-of-waltham-forest"
NAME = "London Borough of Waltham Forest"
STATS = f"{SITE}/your-councils-performance/{COUNCIL}/statistics"
# An unrecognised outcome code ("all") returns every published decision for the year.
LISTING = (f"{SITE}/your-councils-performance/{COUNCIL}/decisions/{{y}}/all/Listing"
           "?t=both&fd={y}-04-01&td={y1}-03-31&dc=all&aname=London%20Borough%20of%20Waltham%20Forest"
           "&atype=London%20borough&sortOrder=descending&page={page}")
FIRST_YEAR = 2018


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wfsend-data-fetch"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def text(fragment, sep=" "):
    """Strip tags. Decision summaries sometimes split words across <span>s, so
    they are joined with sep=""; page text needs sep=" " to keep words apart."""
    fragment = re.sub(r"<(script|style).*?</\1>", "", fragment, flags=re.S)
    s = html.unescape(re.sub(r"<[^>]+>", sep, fragment))
    return re.sub(r"\s+", " ", s).strip()


def fetch_decisions(last_year):
    rows = []
    for y in range(FIRST_YEAR, last_year + 1):
        page, total = 1, None
        while True:
            t = get(LISTING.format(y=y, y1=y + 1, page=page))
            if total is None:
                m = re.search(r"There (?:are|is) (\d+) result", t)
                total = int(m.group(1)) if m else 0
            items = re.findall(r'<li>\s*<p class="mainItemLabel">(.*?)</li>', t, re.S)
            for it in items:
                link = re.search(r'href="([^"]+)"[^>]*>([^<]+)</a>', it)
                ref = re.search(r"\((\d\d \d\d\d \d\d\d)\)", link.group(2)).group(1)
                ids = [text(s) for s in re.findall(r"<span>(.*?)</span>", re.search(r'class="identifiers">(.*?)</p>', it, re.S).group(1), re.S)]
                summary = text(re.search(r'class="summary">(.*?)</p>', it, re.S).group(1), sep="")
                rows.append({
                    "reporting_year": f"{y}/{str(y + 1)[2:]}",
                    "reference": ref,
                    "url": SITE + link.group(1),
                    "type": ids[0],
                    "outcome": ids[1],
                    "category": ids[2],
                    "date": dt.datetime.strptime(ids[3], "%d-%b-%Y").date().isoformat(),
                    "summary": re.sub(r"^Summary:\s*", "", summary),
                })
            if page * 10 >= total or not items:
                break
            page += 1
            time.sleep(0.5)
        got = sum(1 for r in rows if r["reporting_year"].startswith(str(y)))
        print(f"  {y}/{str(y + 1)[2:]}: {got} of {total} decisions")
        if got != total:
            raise SystemExit(f"expected {total} decisions for {y}, parsed {got}")
    return rows


def num(pattern, s, cast=float):
    m = re.search(pattern, s)
    return cast(m.group(1).replace(",", "")) if m else None


def fetch_stats(last_year):
    """Headline statistics. The page layout changed in 2024/25, so each figure
    has a pattern for the newer and the older wording."""
    rows = []
    for y in range(FIRST_YEAR, last_year + 1):
        try:
            s = text(get(f"{STATS}?statsSort={y}"))
        except urllib.error.HTTPError as e:
            if e.code == 404:  # year not published yet
                continue
            raise
        if not re.search(rf"[Bb]etween 1 April {y}", s):
            continue
        rows.append({
            "reporting_year": f"{y}/{str(y + 1)[2:]}",
            "dealt_with": num(r"we dealt with ([\d,]+) complaints", s, int),
            "investigated": num(r"We investigated ([\d,]+) complaints", s, int)
                            or num(r"total of ([\d,]+) investigations", s, int),
            "upheld": num(r"complaints and upheld ([\d,]+)", s, int)
                      or num(r"([\d,]+) upheld decisions (?:Adjusted|View)", s, int),
            "upheld_pct": num(r"(\d+)% of complaints we investigated were upheld", s),
            "upheld_pct_similar": num(r"were upheld\. This compares to an average of (\d+)%", s),
            "upheld_per_100k": num(r"this is ([\d.]+) upheld decisions per 100,000", s),
            "upheld_per_100k_similar": num(r"average for authorities of this type is ([\d.]+) upheld", s),
        })
        time.sleep(0.5)
    return rows


def write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"  {len(rows)} rows -> {path.relative_to(ROOT)}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    # LGSCO reporting years run April to March.
    last_year = today.year if today.month >= 4 else today.year - 1
    print("[lgo] annual statistics")
    stats = fetch_stats(last_year)
    write(OUT / "annual_stats.csv", stats)
    print("[lgo] decisions")
    write(OUT / "decisions.csv", fetch_decisions(last_year))
    (OUT / "manifest.json").write_text(json.dumps({
        "publisher": "Local Government and Social Care Ombudsman",
        "statistics_url": STATS,
        "decisions_url": f"{SITE}/decisions",
        "fetched": today.isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
