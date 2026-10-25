#!/usr/bin/env python3
"""Download DfE SEND statistics and keep England, London, the London boroughs
and Waltham Forest's statistical neighbours.

Reads data/dfe_sources.yaml, downloads each data set from Explore Education
Statistics, filters it and writes:

  data/dfe/<key>.csv        filtered rows, original DfE column names
  data/dfe/manifest.json    where every file came from and when it was fetched

Usage:
  python scripts/fetch_dfe.py            # fetch everything
  python scripts/fetch_dfe.py ehcp_requests ks4_sen
"""
import csv
import datetime as dt
import gzip
import io
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "dfe"
API = "https://api.education.gov.uk/statistics/v1"
CATALOGUE = "https://explore-education-statistics.service.gov.uk/data-catalogue/data-set"
# London region, plus Inner/Outer London, which some files use as the region for LAs.
LONDON = {"E12000007", "E13000001", "E13000002"}
UA = {"User-Agent": "wfsend-data-fetch", "Accept-Encoding": "gzip"}

csv.field_size_limit(10_000_000)


def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=600)


def get_json(url):
    with get(url) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return json.loads(body)


def open_csv_stream(url, encoding="utf-8-sig"):
    """Stream a (possibly gzipped) CSV download as text lines."""
    raw = io.BufferedReader(get(url), buffer_size=1 << 20)
    # EES sometimes gzips the body with or without a Content-Encoding header,
    # so sniff the magic bytes rather than trusting headers.
    if raw.peek(2)[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=raw)
    return io.TextIOWrapper(raw, encoding=encoding, newline="")


def in_scope(row, neighbours=frozenset(), school_rows=False):
    level = row.get("geographic_level")
    if level == "National" or (school_rows and level == "School"):
        return True
    if level in ("Regional", "Local authority"):
        return row.get("region_code") in LONDON or (level == "Local authority" and row.get("new_la_code") in neighbours)
    return False


def keep_row(row, keep):
    return all(row.get(col) in allowed for col, allowed in keep.items())


def resolve(ds):
    """Return (file_id, title, version, published) for a dataset config."""
    if "api_id" in ds:
        meta = get_json(f"{API}/data-sets/{ds['api_id']}")
        lv = meta["latestVersion"]
        return lv["file"]["id"], meta["title"], lv.get("version"), lv.get("published")
    return ds["file_id"], ds["title"], None, None


def fetch_dataset(key, ds, neighbours):
    file_id, title, version, published = resolve(ds)
    url = f"{CATALOGUE}/{file_id}/csv"
    print(f"[{key}] {title}\n    {url}", flush=True)
    # A few older DfE files are Windows-1252 rather than UTF-8; see `encoding` in the config.
    reader = csv.DictReader(open_csv_stream(url, ds.get("encoding", "utf-8-sig")))
    keep = ds.get("keep", {})
    rows, seen = [], 0
    unmatched = {col: set() for col in keep}
    for row in reader:
        seen += 1
        if not in_scope(row, neighbours, ds.get("school_rows", False)):
            continue
        if keep_row(row, keep):
            rows.append(row)
        else:
            for col in keep:
                if len(unmatched[col]) < 40:
                    unmatched[col].add(row.get(col))
    if not rows:
        raise SystemExit(f"[{key}] no rows matched keep={keep}; values seen: {unmatched}")
    dest = OUT / f"{key}.csv"
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=reader.fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"    kept {len(rows):,} of {seen:,} rows -> {dest.relative_to(ROOT)}")
    return {
        "title": title,
        "publication": ds["publication"],
        "dataset_url": f"{CATALOGUE}/{file_id}",
        "download_url": url,
        "api_id": ds.get("api_id"),
        "api_version": version,
        "published": published,
        "rows": len(rows),
    }


def parse_appeal_rate(text, extra=()):
    """Turn DfE's formatted appeal-rate table into tidy rows.

    Layout: a 'year' header row (2024 ... 2025 ...), a column header row, then
    one row per LA: name, old code, appeals, decisions, rate, appeals, decisions, rate.
    Keeps London boroughs, England, and any LA named in `extra`.
    """
    rows = list(csv.reader(io.StringIO(text)))
    years = None
    out = []
    london = False
    for r in rows:
        cells = [c.strip() for c in r]
        if years is None and len(cells) > 5 and cells[2].isdigit() and cells[5].isdigit():
            years = [cells[2], cells[5]]
            continue
        if not years or not cells or not cells[0]:
            continue
        name = cells[0]
        if name.isupper():  # region / sub-region headings
            london = name in ("LONDON", "INNER LONDON", "OUTER LONDON")
            continue
        if name.startswith(("England", "1.", "2.", "3.", "4.", "5.", "Footnotes", "SEND", "Sources")):
            if name.startswith("England"):
                area, level = "England", "National"
            else:
                continue
        elif london or name in extra:
            area, level = name, "Local authority"
        else:
            continue
        for i, year in enumerate(years):
            a, d, rate = cells[2 + 3 * i: 5 + 3 * i]
            out.append({"time_period": year, "geographic_level": level, "area": area,
                        "appeals": a.strip(" -"), "appealable_decisions": d.strip(),
                        "appeal_rate": rate.rstrip("%").strip()})
        if area == "England":
            break
    return out


def fetch_supporting(key, sf, extra):
    print(f"[{key}] {sf['title']}\n    {sf['download_url']}", flush=True)
    with get(sf["download_url"]) as r:
        body = r.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
    rows = parse_appeal_rate(body.decode("utf-8-sig"), extra)
    if not rows:
        raise SystemExit(f"[{key}] could not parse supporting file")
    dest = OUT / f"{key}.csv"
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"    {len(rows)} rows -> {dest.relative_to(ROOT)}")
    return {"title": sf["title"], "publication": sf["publication"],
            "dataset_url": sf["release_url"], "download_url": sf["download_url"], "rows": len(rows)}


def main(argv):
    cfg = yaml.safe_load((ROOT / "data" / "dfe_sources.yaml").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    wanted = set(argv) or None
    today = dt.date.today().isoformat()
    sn = cfg["statistical_neighbours"]["areas"]
    neighbours = frozenset(a["code"] for a in sn)
    outside_london = {a["name"] for a in sn if a["region"] != "London"}
    for key, ds in cfg["datasets"].items():
        if wanted and key not in wanted:
            continue
        manifest[key] = fetch_dataset(key, ds, neighbours) | {"fetched": today}
    for key, sf in cfg.get("supporting_files", {}).items():
        if wanted and key not in wanted:
            continue
        manifest[key] = fetch_supporting(key, sf, outside_london) | {"fetched": today}
    manifest_path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
