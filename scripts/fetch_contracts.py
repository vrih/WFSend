#!/usr/bin/env python3
"""Download the council's procurement notices from Contracts Finder and Find a Tender.

Writes:
  data/contracts/notices.csv     every notice published by the London Borough of
                                 Waltham Forest, from both services
  data/contracts/manifest.json   where the data came from and when

Contracts Finder can be searched by keyword, so each run downloads all of the
council's notices again. Find a Tender has no search API: its OCDS feed lists
every notice in the UK (about 500 a day), so the script reads the feed from
where the last run stopped and keeps the council's notices. The first run
reads from FTS_START, which takes about an hour.

All notices are kept, not only SEND ones, so the SEND filter in
scripts/metrics.py can be changed without reading the feed again.

Usage:
  python scripts/fetch_contracts.py
"""
import csv
import datetime as dt
import html
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "contracts"
BUYER = "london borough of waltham forest"
CF_SEARCH = "https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices/json"
CF_NOTICE = "https://www.contractsfinder.service.gov.uk/Notice/{id}"
FTS_FEED = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
FTS_NOTICE = "https://www.find-tender.service.gov.uk/Notice/{id}"
# The Procurement Act 2023 came into force on 24 February 2025. Earlier council
# notices are all on Contracts Finder too, so the Find a Tender feed is read from then.
FTS_START = "2025-02-24T00:00:00"
FIELDS = ["source", "notice_id", "url", "procurement_id", "stage", "status", "published",
          "title", "description", "value", "value_low", "value_high", "awarded_value",
          "suppliers", "start", "end"]


LONDON = ZoneInfo("Europe/London")
PAUSE = 1  # seconds between Find a Tender pages, to stay under its rate limit


def request(url, body=None, tries=6):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "wfsend-data-fetch"} | ({"Content-Type": "application/json"} if data else {})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if attempt == tries - 1 or (e.code != 429 and e.code < 500):
                raise
            wait = e.headers.get("Retry-After", "")
            wait = min(int(wait) if wait.isdigit() else 30 * (attempt + 1), 300)
            print(f"    HTTP {e.code}, waiting {wait}s", flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def text(s):
    return html.unescape(s or "").strip()


def contracts_finder():
    body = {"searchCriteria": {"keyword": '"Waltham Forest"',
                               "types": ["Contract", "Pipeline", "Opportunity", "EarlyEngagement", "FutureOpportunity"],
                               "statuses": ["Open", "Closed", "Awarded", "Withdrawn"]},
            "size": 1000}
    r = request(CF_SEARCH, body)
    if r["hitCount"] > len(r["noticeList"]):
        raise SystemExit(f"Contracts Finder returned {len(r['noticeList'])} of {r['hitCount']} notices; add paging")
    rows = []
    for n in r["noticeList"]:
        i = n["item"]
        if (i.get("organisationName") or "").strip().lower() != BUYER:
            continue
        rows.append({
            "source": "Contracts Finder",
            "notice_id": i["id"],
            "url": CF_NOTICE.format(id=i["id"]),
            "procurement_id": i.get("parentId") or i["id"],
            "stage": i.get("noticeType") or "",
            "status": i.get("noticeStatus") or "",
            "published": (i.get("publishedDate") or "")[:10],
            "title": text(i.get("title")),
            "description": text(i.get("description")),
            "value": "",
            "value_low": i.get("valueLow") or "",
            "value_high": i.get("valueHigh") or "",
            "awarded_value": i.get("awardedValue") or "",
            "suppliers": text(i.get("awardedSupplier")),
            "start": (i.get("start") or "")[:10],
            "end": (i.get("end") or "")[:10],
        })
    return rows


def amount(v):
    return v.get("amount", "") if isinstance(v, dict) else ""


def fts_row(rel):
    t = rel.get("tender", {})
    awards = rel.get("awards", [])
    contracts = rel.get("contracts", [])
    period = (contracts[0].get("period") if contracts else None) or t.get("contractPeriod") or {}
    awarded = [amount(a.get("value")) for a in awards if amount(a.get("value")) != ""]
    return {
        "source": "Find a Tender",
        "notice_id": rel["id"],
        "url": FTS_NOTICE.format(id=rel["id"]),
        "procurement_id": rel.get("ocid", ""),
        "stage": ", ".join(rel.get("tag", [])),
        "status": t.get("status", ""),
        "published": rel.get("date", "")[:10],
        "title": text(t.get("title")),
        "description": text(t.get("description")),
        "value": amount(t.get("value")),
        "value_low": amount(t.get("minValue")),
        "value_high": "",
        "awarded_value": sum(awarded) if awarded else "",
        "suppliers": "; ".join(s.get("name", "") for a in awards for s in a.get("suppliers", [])),
        "start": (period.get("startDate") or "")[:10],
        "end": (period.get("endDate") or "")[:10],
    }


def find_a_tender(since, until):
    """The council's notices updated between since and until, from the national feed.

    The feed's own "next" cursor can return the same page again and again, so
    pages are requested by date instead: each request asks for notices updated
    before the oldest one already seen. The feed reads its dates as UK local
    time, while notices carry UTC offsets, so dates are converted to London time.
    """
    rows, pages, seen = [], 0, set()
    to = until
    while True:
        d = request(f"{FTS_FEED}?updatedFrom={since}&updatedTo={to}&limit=100")
        pages += 1
        releases = d.get("releases", [])
        new = [rel for rel in releases if (rel["id"], rel.get("date")) not in seen]
        for rel in new:
            seen.add((rel["id"], rel.get("date")))
            if BUYER in (rel.get("buyer", {}).get("name") or "").lower():
                rows.append(fts_row(rel))
        if len(releases) < 100:
            break
        oldest = min(dt.datetime.fromisoformat(rel["date"].replace("Z", "+00:00")) for rel in releases)
        # One second of overlap, so notices sharing the oldest timestamp aren't missed;
        # if a whole page shares it, step back past it.
        step = dt.timedelta(seconds=1 if new else -1)
        to = (oldest.astimezone(LONDON) + step).strftime("%Y-%m-%dT%H:%M:%S")
        if pages % 25 == 0:
            print(f"      {pages} pages, back to {to[:16]}", flush=True)
        time.sleep(PAUSE)
    print(f"    {since[:10]} to {until[:10]}: {pages} pages, {len(rows)} council notices", flush=True)
    return rows


def windows(since, until):
    """Calendar-month slices, so a long first run can stop and carry on where it left off."""
    start = dt.datetime.fromisoformat(since)
    end = dt.datetime.fromisoformat(until)
    while start < end:
        nxt = min(dt.datetime(start.year + start.month // 12, start.month % 12 + 1, 1), end)
        yield start.isoformat(), nxt.isoformat()
        start = nxt


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path, manifest_path = OUT / "notices.csv", OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    old = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []

    print("Contracts Finder", flush=True)
    cf = contracts_finder()
    print(f"    {len(cf)} council notices")

    since = manifest.get("fts_read_to", FTS_START)
    until = dt.datetime.now().replace(microsecond=0).isoformat()
    print(f"Find a Tender, {since} to {until}", flush=True)
    fts = {r["notice_id"]: r for r in old if r["source"] == "Find a Tender"}

    for a, b in windows(since, until):
        fts.update({r["notice_id"]: r for r in find_a_tender(a, b)})  # a later release of the same notice replaces it
        save(path, manifest_path, cf + list(fts.values()), b)
    print(f"    {len(fts)} council notices in total")


def save(path, manifest_path, rows, read_to):
    rows = sorted(rows, key=lambda r: (r["published"], r["notice_id"]), reverse=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    manifest_path.write_text(json.dumps({
        "buyer": "London Borough of Waltham Forest",
        "contracts_finder": {"title": "Contracts Finder", "url": "https://www.contractsfinder.service.gov.uk/"},
        "find_a_tender": {"title": "Find a Tender", "url": "https://www.find-tender.service.gov.uk/", "read_from": FTS_START},
        "fts_read_to": read_to,
        "fetched": dt.date.today().isoformat(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
