#!/usr/bin/env python3
"""Cut hand-downloaded NHS England files down to the rows this site needs.

NHS England Digital blocks automated downloads and its files are hundreds of
megabytes uncompressed, so they are not committed. Download them in a browser,
then run this script on your own computer. It reads the zip (or CSV/XLSX)
without unzipping it, keeps rows for North East London, NELFT, London and
England, and writes small extracts to data/nhs/<dataset>/ for committing.

Usage:
  python scripts/extract_nhs.py autism ~/Downloads/autism_waiting_times_apr26_jun26.zip
  python scripts/extract_nhs.py community_waits ~/Downloads/chs_waiting_list_2026_08.csv

Only the Python standard library is needed for CSV and zip files. XLSX files
also need openpyxl (pip install openpyxl).
"""
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nhs"

# A row is kept if any cell exactly matches one of these codes, or contains one
# of these names. Codes: NELFT trust (RAT), NHS North East London ICB (QMF),
# London region (Y56), England (E92000001).
CODES = {"RAT", "QMF", "Y56", "E92000001", "ENG", "ENGLAND"}
NAMES = re.compile(r"north east london|nelft|waltham forest|^england$|^london$|^national$", re.I)

csv.field_size_limit(10_000_000)


def wanted(cells):
    for c in cells:
        c = (c or "").strip()
        if c.upper() in CODES or NAMES.search(c):
            return True
    return False


def filter_rows(rows):
    """rows: iterator of lists. Yields the header then the matching rows.

    NHS spreadsheets often put a title and notes above the real header, so
    every row up to and including the first row with three or more filled
    cells is kept as-is. For plain CSVs that is just the header row.
    """
    for r in rows:
        yield r
        if sum(1 for c in r if str(c or "").strip()) >= 3:
            break
    for r in rows:
        if wanted(r):
            yield r


def csv_rows(binary):
    text = io.TextIOWrapper(binary, encoding="utf-8-sig", errors="replace", newline="")
    return csv.reader(text)


def xlsx_sheets(binary):
    import openpyxl  # only needed for spreadsheets
    wb = openpyxl.load_workbook(binary, read_only=True, data_only=True)
    for ws in wb.worksheets:
        ws.reset_dimensions()  # some NHS files record a wrong sheet size
        yield ws.title, ([("" if v is None else str(v)) for v in row] for row in ws.iter_rows(values_only=True))


def any_match(path):
    with path.open(encoding="utf-8", newline="") as f:
        return any(wanted(r) for r in csv.reader(f))


def write(dest, rows):
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = -1
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        for n, r in enumerate(filter_rows(rows)):
            r = list(r)
            while r and str(r[-1] or "").strip() == "":  # drop trailing empty cells
                r.pop()
            w.writerow(r)
    if n < 1 or not any_match(dest):  # header only, or empty
        dest.unlink()
        return 0
    return n


def extract_member(name, opener, outdir, report):
    lower = name.lower()
    stem = Path(name).stem
    if lower.endswith(".csv"):
        with opener() as b:
            n = write(outdir / f"{stem}.csv", csv_rows(b))
        report.append({"file": name, "rows_kept": n})
    elif lower.endswith((".xlsx", ".xlsm")):
        with opener() as b:
            data = io.BytesIO(b.read())
        for sheet, rows in xlsx_sheets(data):
            safe = re.sub(r"[^\w-]+", "_", sheet).strip("_")
            n = write(outdir / f"{stem}__{safe}.csv", rows)
            report.append({"file": name, "sheet": sheet, "rows_kept": n})
    else:
        report.append({"file": name, "skipped": "not a CSV or XLSX file"})


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    dataset, paths = argv[0], [Path(p).expanduser() for p in argv[1:]]
    for src in paths:
        outdir = OUT / dataset / re.sub(r"[^\w-]+", "_", src.stem).strip("_")
        report = []
        print(f"[{dataset}] {src.name}")
        # .xlsx files are zip archives too, so check the extension first
        if src.suffix.lower() not in (".xlsx", ".xlsm") and zipfile.is_zipfile(src):
            with zipfile.ZipFile(src) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        extract_member(info.filename, lambda i=info: z.open(i), outdir, report)
        else:
            extract_member(src.name, lambda: open(src, "rb"), outdir, report)
        for r in report:
            print("   ", r)
        kept = sum(r.get("rows_kept", 0) for r in report)
        if not kept:
            print("    no matching rows found: check the file is the provider or ICB breakdown")
            continue
        (outdir / "source.json").write_text(json.dumps({
            "dataset": dataset,
            "original_file": src.name,
            "original_sha256": sha256(src),
            "original_bytes": src.stat().st_size,
            "extracted": dt.date.today().isoformat(),
            "files": report,
        }, indent=2) + "\n")
        print(f"    kept {kept:,} rows -> {outdir.relative_to(ROOT)}/")


if __name__ == "__main__":
    main(sys.argv[1:])
