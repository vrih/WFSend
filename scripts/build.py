#!/usr/bin/env python3
"""Build the static site into _site/ from data/ and site/.

  python scripts/build.py

No network access is needed: it reads the committed DfE extracts
(data/dfe/) and the curated local figures (data/local/).
"""
import csv
import datetime as dt
import io
import json
import shutil
import sys
from html import escape
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts  # noqa: E402
import metrics as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
SITE = ROOT / "site"
DOMAIN = "wfsenddata.org.uk"
CONTACT_EMAIL = f"info@{DOMAIN}"

AREAS = (M.WF, "London", "England")


def read_yaml(name):
    return yaml.safe_load((ROOT / "data" / "local" / name).read_text())


SOURCES = read_yaml("sources.yaml")
MANIFEST = json.loads((ROOT / "data" / "dfe" / "manifest.json").read_text())
LGO_MANIFEST = json.loads((ROOT / "data" / "lgo" / "manifest.json").read_text())
DFE_CFG = yaml.safe_load((ROOT / "data" / "dfe_sources.yaml").read_text())
PUBS = DFE_CFG["publications"]

# Every citation used on the site, so sources.html can list exactly those.
USED = {"local": set(), "dfe": set()}


def fmt(v, unit="percent"):
    return charts._fmt(v, unit)


def cite(source, page=None):
    """Inline citation link for a local document."""
    s = SOURCES[source]
    USED["local"].add(source)
    where = f", p. {page}" if isinstance(page, int) else (f", {page}" if page else "")
    label = f"{s['publisher']}, {s['title']} ({dt.date.fromisoformat(str(s['date'])).strftime('%B %Y')}){where}"
    return Markup(f'<a class="cite" href="{escape(s["url"])}" rel="noopener">{escape(label)}</a>')


def cite_dfe(keys):
    parts = []
    for k in keys:
        USED["dfe"].add(k)
        m = MANIFEST[k]
        pub = PUBS[m["publication"]]
        parts.append(
            f'DfE, <a class="cite" href="{escape(pub["url"])}" rel="noopener">{escape(pub["title"])}</a>: '
            f'<a class="cite" href="{escape(m["dataset_url"])}" rel="noopener">{escape(m["title"])}</a>'
            f' (downloaded {escape(m["fetched"])})'
        )
    return Markup("Source: " + "; ".join(parts))


def figure(m, ranked=False, note=None, y_max=None, areas=AREAS):
    """A chart (or ranked bars) with legend, data table and source line."""
    series = {a: m["series"].get(a, {}) for a in areas if m["series"].get(a)}
    parts = [f'<figure class="metric" id="{escape(m["id"])}">',
             f'<figcaption><h3>{escape(m["title"])}</h3><p class="explain">{escape(m["explain"])}</p></figcaption>']
    if len(m["periods"]) > 1:
        parts.append(charts.legend(series.keys()))
        parts.append(charts.line_chart(series, m["periods"], unit=m["unit"], title=m["title"], y_max=y_max))
    if ranked and m["boroughs"]:
        latest = m["latest_period"]
        parts.append(f'<h4 class="sub">London boroughs, {escape(latest)}</h4>')
        refs = {a: m["series"].get(a, {}).get(latest) for a in ("London", "England")}
        parts.append(charts.ranked_bars(m["boroughs"], unit=m["unit"],
                                        higher_is_better=m.get("higher_is_better", True), refs=refs))
    parts.append("<details><summary>Show the numbers</summary>"
                 + charts.table(series, m["periods"], unit=m["unit"]) + "</details>")
    if note:
        parts.append(f'<p class="note">{note}</p>')
    parts.append(f'<p class="source">{cite_dfe(m["sources"])}</p></figure>')
    return Markup("\n".join(parts))


def rank_text(m):
    r = m.get("rank")
    if not r:
        return ""
    best = m.get("rank_label") or ("best" if m.get("higher_is_better", True) else "lowest")
    joint = "joint " if r.get("joint") else ""
    return f"{joint}{ordinal(r['pos'])} of {r['of']} London boroughs ({ordinal(1)} = {best})"


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def compute():
    req_out = M.request_outcomes()
    ar = M.annual_reviews()
    return {
        "timeliness": M.timeliness(),
        "plans_issued": M.plans_issued(),
        "requests": M.requests(),
        "refused": req_out["refused"],
        "undecided": req_out["undecided"],
        "six_weeks": req_out["six_weeks"],
        "not_issued": M.assessments_not_issued(),
        "caseload": M.caseload(),
        "growth": M.caseload_growth(),
        "placements": M.placements(),
        "prevalence": M.sen_prevalence(),
        "ar": ar,
        "appeal_rate": M.appeal_rate(),
        "ks2": M.ks2(),
        "ks4": M.ks4(),
        "exclusions": M.exclusions(),
        "ombudsman": M.ombudsman(),
        "spending": M.spending(),
        "absence": M.absence(),
        "eyfs": M.eyfs(),
        "ks4_destinations": M.ks4_destinations(),
        "neet": M.neet(),
    }


def headline_rows(d, local):
    """Every headline number on the home page, for the downloadable CSV."""
    t, ar = d["timeliness"], d["ar"]
    rows = []

    def add(label, period, value, unit, source):
        rows.append({"measure": label, "period": period, "waltham_forest": value, "unit": unit, "source": source})
    for m in (t, d["six_weeks"], ar["completed"], ar["decision"], d["appeal_rate"]):
        add(m["title"], m["latest_period"], round(m["latest"][M.WF], 1) if m["latest"][M.WF] is not None else "", m["unit"],
            "; ".join(MANIFEST[k]["dataset_url"] for k in m["sources"]))
    add(d["caseload"]["title"], d["caseload"]["latest_period"], d["caseload"]["latest"][M.WF], "count",
        MANIFEST["ehcp_caseload"]["dataset_url"])
    for key, meas in local["measures"].items():
        o = meas["observations"][-1]
        add(meas["title"], o["period"], o["value"], meas["unit"], SOURCES[o["source"]]["url"] + f" (p. {o['page']})")
    lgo = d["ombudsman"]["stats"][-1]
    add("Ombudsman: complaints about the council upheld (all services)", lgo["reporting_year"],
        int(lgo["upheld"]), "count", LGO_MANIFEST["statistics_url"])
    for y in d["ombudsman"]["by_year"]:
        add("Ombudsman: published SEND decisions upheld", y["year"], y["upheld"], "count", LGO_MANIFEST["decisions_url"])
    for f in local["finance"]:
        add(f["label"], "", f["value"], "", SOURCES[f["source"]]["url"] + f" (p. {f['page']})")
    return rows


def write_csv(path, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


PAGES = [
    ("index.html", "Overview"),
    ("assessments.html", "Assessments"),
    ("plans.html", "EHC plans"),
    ("reviews.html", "Annual reviews"),
    ("outcomes.html", "Outcomes"),
    ("health.html", "Health"),
    ("disputes.html", "Complaints & appeals"),
    ("targets.html", "Targets"),
    ("inspection.html", "Inspection"),
    ("money.html", "Money"),
    ("sources.html", "Sources"),
]


def main():
    d = compute()
    local = read_yaml("council_reported.yaml")
    inspection = read_yaml("inspection.yaml")
    releases = read_yaml("release_calendar.yaml")

    env = Environment(loader=FileSystemLoader(SITE / "templates"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.globals.update(figure=figure, cite=cite, cite_dfe=cite_dfe, fmt=fmt, rank_text=rank_text,
                       ordinal=ordinal, charts=charts, Markup=Markup, WF=M.WF, AREAS=AREAS, pages=PAGES,
                       contact_email=CONTACT_EMAIL, domain=DOMAIN)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    shutil.copytree(SITE / "static", OUT / "static")

    built = dt.date.today().isoformat()
    ctx = dict(d=d, local=local, inspection=inspection, releases=releases, built=built, SOURCES=SOURCES,
               MANIFEST=MANIFEST, LGO_MANIFEST=LGO_MANIFEST, PUBS=PUBS, USED=USED)
    # sources.html last, so it can list every citation the other pages used
    for name, _ in PAGES:
        if name == "sources.html":
            continue
        html = env.get_template(name).render(page=name, **ctx)
        (OUT / name).write_text(html, encoding="utf-8")
    (OUT / "sources.html").write_text(env.get_template("sources.html").render(page="sources.html", **ctx), encoding="utf-8")

    # downloadable data
    for f in (ROOT / "data" / "dfe").glob("*"):
        shutil.copy(f, OUT / "data" / f.name)
    for f in (ROOT / "data" / "lgo").glob("*.csv"):
        shutil.copy(f, OUT / "data" / f"ombudsman_{f.name}")
    for f in (ROOT / "data" / "local").glob("*.yaml"):
        shutil.copy(f, OUT / "data" / f.name)
    write_csv(OUT / "data" / "headlines.csv", headline_rows(d, local))
    (OUT / ".nojekyll").write_text("")
    (OUT / "CNAME").write_text(DOMAIN + "\n")  # custom domain for GitHub Pages
    print(f"Built {len(PAGES)} pages into {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
