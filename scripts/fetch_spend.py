#!/usr/bin/env python3
"""Download Waltham Forest's monthly spending over £500 reports and keep SEND payments.

Writes:
  data/spend/send_payments.csv  every payment coded to a SEND service, from the
                                September 2023 report onwards
  data/spend/reports.csv        every monthly report: how many payments it lists
                                and their total, across all services
  data/spend/manifest.json      where the data came from and when

The council publishes one Excel file a month on its transparency page. From
September 2023 the files use the service codes in SEND_SERVICES. Earlier files
use a different set of codes that can't be matched to these, so their payments
aren't kept, but they are still counted in reports.csv. Values are copied as
published, including the council's "REDACTED PERSONAL DATA" for payments to
individuals.

Usage:
  python scripts/fetch_spend.py
"""
import csv
import datetime as dt
import html
import io
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "spend"
SITE = "https://www.walthamforest.gov.uk"
PAGE = f"{SITE}/council-and-elections/about-us/council-budgets-and-spending/council-transparency"
FIRST = (2023, 9)  # first report using the current service codes
# Children's Services cost centres for SEND, by the code at the start of the
# "Service" column. Some were renamed over time, so match on the code.
SEND_SERVICES = {
    "B6503E": "Central Expenditure High Needs",
    "B6113E": "Provisions Team Short Breaks and Home School Transport",
    "B6111E": "Assistant Director SEND Services",
    "B6114E": "SEND Staffing",
    "B6116E": "Education Psychology Service",
    "B6207E": "SEND Commissioning and Delivery",
    "B6208E": "SEND Statutory Assessments",
}
COLUMNS = ["Supplier Name", "Unique Reference", "Invoice Amount", "Invoice Date",
           "Payment Date", "Division", "Service", "Subjective"]
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wfsend-data-fetch"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def reports():
    """[(year, month, url)] for each monthly report linked from the transparency page.
    Purchase card and other files on the same page are left out."""
    page = get(PAGE).decode("utf-8", "replace")
    out = {}
    for href, label in re.findall(r'<a[^>]+href="([^"]+\.xlsx)"[^>]*>(.*?)</a>', page, re.S):
        label = re.sub(r"<[^>]+>|\s+", " ", html.unescape(label)).strip()
        m = re.fullmatch(r"Transparency Report (\w+) (\d{4}) \(Excel file\)", label)
        if m and m.group(1) in MONTHS:
            url = href if href.startswith("http") else SITE + href
            out[(int(m.group(2)), MONTHS[m.group(1)])] = url
    return sorted((y, mo, u) for (y, mo), u in out.items())


def col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def num_text(s):
    """Excel stores 521.3 as 521.29999999999995. Write the shortest text for the
    same number, so the value is unchanged but reads as it does in Excel."""
    s = repr(float(s))
    return s[:-2] if s.endswith(".0") else s


def xlsx_rows(data):
    """Rows of the first worksheet as lists of strings, using only the standard library."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rid = wb.find("m:sheets/m:sheet", NS).get(f"{{{NS['r']}}}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels.findall("rel:Relationship", NS) if r.get("Id") == rid)
    sheet = ET.fromstring(z.read("xl/" + target.lstrip("/").removeprefix("xl/")))
    for row in sheet.iter(f"{{{NS['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", NS):
            t, v = c.get("t"), c.find("m:v", NS)
            if t == "s":
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
            elif v is not None and t in (None, "n"):
                val = num_text(v.text)
            else:
                val = v.text if v is not None else ""
            cells[col(c.get("r"))] = val
        yield [cells.get(i, "") for i in range(max(cells) + 1)] if cells else []


def payments(data):
    rows = xlsx_rows(data)
    header = next(r for r in rows if r and r[0].strip())
    idx = {h.strip(): i for i, h in enumerate(header) if h.strip()}
    for r in rows:
        if r and r[0].strip():
            yield {c: r[idx[c]].strip() if c in idx and idx[c] < len(r) else "" for c in COLUMNS}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    kept, summary = [], []
    for y, mo, url in reports():
        ps = list(payments(get(url)))
        total = sum(float(p["Invoice Amount"]) for p in ps if re.fullmatch(r"-?[\d.]+", p["Invoice Amount"]))
        month = f"{y}-{mo:02d}"
        summary.append({"report_month": month, "url": url, "payments": len(ps), "total": round(total, 2)})
        if (y, mo) >= FIRST:
            kept += [{"report_month": month, **p} for p in ps if p["Service"][:6] in SEND_SERVICES]
        print(month, len(ps), "payments")
        time.sleep(0.3)
    with (OUT / "send_payments.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["report_month"] + COLUMNS)
        w.writeheader()
        w.writerows(kept)
    with (OUT / "reports.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["report_month", "payments", "total", "url"])
        w.writeheader()
        w.writerows(summary)
    (OUT / "manifest.json").write_text(json.dumps({
        "publisher": "London Borough of Waltham Forest",
        "title": "Council transparency: spending over £500",
        "url": PAGE,
        "first_report": summary[0]["report_month"],
        "latest_report": summary[-1]["report_month"],
        "send_services": SEND_SERVICES,
        "fetched": dt.date.today().isoformat(),
    }, indent=2, ensure_ascii=False) + "\n")
    print(len(kept), "SEND payments kept from", len(summary), "reports")


if __name__ == "__main__":
    main()
