#!/usr/bin/env python3
"""Build the static site into _site/ from data/ and site/.

  python scripts/build.py

No network access is needed: it reads the committed DfE and ONS extracts
(data/dfe/, data/ons/) and the curated local figures (data/local/).
"""
import csv
import datetime as dt
import hashlib
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

AREAS = (M.WF, "London", "England", M.SN)


def read_yaml(name):
    return yaml.safe_load((ROOT / "data" / "local" / name).read_text())


SOURCES = read_yaml("sources.yaml")
MANIFEST = json.loads((ROOT / "data" / "dfe" / "manifest.json").read_text())
LGO_MANIFEST = json.loads((ROOT / "data" / "lgo" / "manifest.json").read_text())
ONS_MANIFEST = json.loads((ROOT / "data" / "ons" / "manifest.json").read_text())
DFE_CFG = yaml.safe_load((ROOT / "data" / "dfe_sources.yaml").read_text())
PUBS = DFE_CFG["publications"]
SN_CFG = DFE_CFG["statistical_neighbours"]

# Every citation used on the site, so sources.html can list exactly those.
USED = {"local": set(), "dfe": set()}


def fmt(v, unit="percent"):
    return charts._fmt(v, unit)


def cite(source, page=None):
    """Inline citation link for a local document."""
    s = SOURCES[source]
    USED["local"].add(source)
    where = f", p. {page}" if isinstance(page, int) else (f", {page}" if page else "")
    if "short" in s:  # legislation: "SEND Regulations 2014, regulation 5"; full title on sources.html
        label = s["short"] + where
        return Markup(f'<a class="cite" href="{escape(s["url"])}" title="{escape(s["title"])}" rel="noopener">{escape(label)}</a>')
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


def cite_ons():
    m = ONS_MANIFEST
    return Markup(f'ONS, <a class="cite" href="{escape(m["url"])}" rel="noopener">{escape(m["title"])}</a>: '
                  f'<a class="cite" href="{escape(m["dataset_url"])}" rel="noopener">{escape(m["dataset"])}</a>'
                  f' (downloaded {escape(m["fetched"])})')


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
    if ranked and m.get("sn_rank"):
        latest = m["latest_period"]
        parts.append(f'<details><summary>Compare with similar areas, {escape(latest)}</summary>'
                     f'<p class="note">Waltham Forest is {escape(sn_rank_text(m))}. '
                     f'<a href="sources.html#similar-areas">How similar areas are chosen</a>.</p>'
                     + charts.ranked_bars(m["neighbours"], unit=m["unit"], higher_is_better=m.get("higher_is_better", True),
                                          refs={M.SN: m["latest"].get(M.SN)})
                     + "</details>")
    parts.append("<details><summary>Show the numbers</summary>"
                 + charts.table(series, m["periods"], unit=m["unit"]) + "</details>")
    if note:
        parts.append(f'<p class="note">{note}</p>')
    ons = f"; {cite_ons()}" if m.get("population") else ""
    parts.append(f'<p class="source">{cite_dfe(m["sources"])}{ons}</p></figure>')
    return Markup("\n".join(parts))


def rank_text(m):
    r = m.get("rank")
    if not r:
        return ""
    best = m.get("rank_label") or ("best" if m.get("higher_is_better", True) else "lowest")
    joint = "joint " if r.get("joint") else ""
    return f"{joint}{ordinal(r['pos'])} of {r['of']} London boroughs ({ordinal(1)} = {best})"


def sn_rank_text(m):
    r = m.get("sn_rank")
    if not r:
        return ""
    best = m.get("rank_label") or ("best" if m.get("higher_is_better", True) else "lowest")
    joint = "joint " if r.get("joint") else ""
    return f"{joint}{ordinal(r['pos'])} of {r['of']} with its similar areas ({ordinal(1)} = {best})"


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def one_in(v):
    """A share in words: 25.7 -> 'about 1 in 4', 70.4 -> 'about 7 in 10'."""
    if v >= 90:
        return "more than 9 in 10"
    if v >= 30:
        return f"about {round(v / 10)} in 10"
    return f"about 1 in {round(100 / v)}"


def long_month(p):
    """'Mar 2026' -> 'March 2026'."""
    return dt.datetime.strptime(p, "%b %Y").strftime("%B %Y")


def months(days):
    return f"about {round(days / 30.44)} months"


def wait_answers(d, local):
    """The plain-language answers at the top of each waiting-time page. They are
    also used for the meta description, the FAQ structured data and llms.txt, so
    search engines and AI tools quote the same words people read."""
    pc = lambda v: f"{v:.0f}%"
    b = d["timeliness_bands"]
    y = b["latest_period"]
    wf, ldn, eng = (b["values"][y][a] for a in (M.WF, "London", "England"))
    lt = local["measures"]["timeliness_20_weeks"]["observations"][-1]
    ehcp = [
        ("How long does an EHC plan take in Waltham Forest?",
         f"Of the new EHC plans Waltham Forest issued in {y}, {pc(wf['within20'])} ({one_in(wf['within20'])}) were issued "
         f"within the 20-week legal limit. {pc(wf['20to52'])} took between 20 weeks and a year, and {pc(wf['over52'])} "
         f"({one_in(wf['over52'])}) took more than a year. In London {pc(ldn['within20'])} were on time, and in England "
         f"{pc(eng['within20'])}. The council's own latest figure ({lt['period']}) is {lt['value']}% within 20 weeks."),
        ("What is the legal time limit for an EHC plan?",
         "The council must tell you within 6 weeks of the request whether it will carry out an EHC needs assessment. "
         "If it assesses and decides to issue a plan, the final plan must be issued within 20 weeks of the request. "
         "A few exceptions apply, such as school holidays of 4 weeks or more."),
        ("Does my child need a diagnosis to get an EHC needs assessment?",
         "No. The council must assess if your child has or may have special educational needs and may need "
         "support through an EHC plan. A diagnosis is not part of the legal test, and parents can ask for an "
         "assessment themselves."),
    ]
    au = d["autism"]
    p = long_month(au["latest"])
    med = {a: au["median"]["series"][a][au["latest"]] for a in au["median"]["series"]}
    over13 = au["over13"]["series"]["NELFT"][au["latest"]]
    autism = [
        ("How long is the wait for an autism assessment in Waltham Forest?",
         f"Children seen by NELFT, the NHS trust that assesses children in Waltham Forest, who had their first "
         f"autism assessment appointment in the 3 months to {p}, had waited a median of {med['NELFT']:,.0f} days "
         f"({months(med['NELFT'])}) since referral. Half waited longer. NICE says an assessment should start within "
         f"3 months. Across North East London the median was {med['North East London']:,.0f} days, in London "
         f"{med['London']:,.0f} days and in England {med['England']:,.0f} days."),
        ("How many children are waiting more than 3 months for an autism assessment?",
         f"In {p}, {pc(over13)} ({one_in(over13)}) of children with an open autism referral at NELFT had been "
         f"waiting 13 weeks or more."),
        ("Can I ask to be referred somewhere else for an autism or ADHD assessment?",
         "In England, if your GP refers you to a mental health service, you can usually choose which NHS-funded "
         "provider you are referred to for your first appointment. Ask your GP. This is sometimes called "
         "\"right to choose\"."),
    ]
    ad = d["adhd"]
    p = ad["latest"]
    o52, o104 = ad["over52"]["series"], ad["over104"]["series"]
    teasers = {
        "ehcp-waiting-time.html": f"In {y}, {pc(wf['within20'])} of new plans were issued within the legal 20 weeks.",
        "autism-assessment-waiting-time.html": f"A median of {months(med['NELFT'])} from referral to a first appointment at NELFT.",
        "adhd-assessment-waiting-time.html": f"{pc(o52['North East London'][p])} of children waiting in North East London had waited a year or more.",
    }
    adhd = [
        ("How long is the wait for an ADHD assessment in Waltham Forest?",
         f"The NHS does not publish how long children wait from referral to an ADHD assessment. It does publish how "
         f"long children still on the waiting list have waited so far. In North East London in {long_month(p)}, "
         f"{pc(o52['North East London'][p])} ({one_in(o52['North East London'][p])}) of children aged 5 to 17 "
         f"with an open referral had been waiting a year or more, and {pc(o104['North East London'][p])} two "
         f"years or more. In London the figures were {pc(o52['London'][p])} and {pc(o104['London'][p])}, and in "
         f"England {pc(o52['England'][p])} and {pc(o104['England'][p])}."),
        autism[2],
    ]
    out = {}
    for page, faq in (("ehcp-waiting-time.html", ehcp), ("autism-assessment-waiting-time.html", autism),
                      ("adhd-assessment-waiting-time.html", adhd)):
        ld = {"@context": "https://schema.org", "@type": "FAQPage",
              "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                             for q, a in faq]}
        out[page] = {"faq": faq, "description": faq[0][1], "teaser": teasers[page],
                     "jsonld": Markup(json.dumps(ld, ensure_ascii=False).replace("</", "<\\/"))}
    return out


def compute():
    req_out = M.request_outcomes()
    ar = M.annual_reviews()
    return {
        "timeliness": M.timeliness(),
        "timeliness_bands": M.timeliness_bands(),
        "plans_issued": M.plans_issued(),
        "requests": M.requests(),
        "requests_rate": M.requests_rate(),
        "refused": req_out["refused"],
        "undecided": req_out["undecided"],
        "six_weeks": req_out["six_weeks"],
        "not_issued": M.assessments_not_issued(),
        "caseload": M.caseload(),
        "growth": M.caseload_growth(),
        "placements": M.placements(),
        "primary_need": M.primary_need(),
        "special_schools": M.special_schools(),
        "specialist_units": M.specialist_units(),
        "specialist_settings": M.specialist_settings(),
        "school_sen": M.school_sen(),
        "specialist_forecasts": M.specialist_forecasts(),
        "home_education": M.home_education(),
        "missing_education": M.missing_education(),
        "ehcp_home_educated": M.ehcp_home_educated(),
        "prevalence": M.sen_prevalence(),
        "ar": ar,
        "appeal_rate": M.appeal_rate(),
        "ks2": M.ks2(),
        "ks4": M.ks4(),
        "exclusions": M.exclusions(),
        "ombudsman": M.ombudsman(),
        "spending": M.spending(),
        "supplier_payments": M.supplier_payments(),
        "contracts": M.contracts(),
        "absence": M.absence(),
        "eyfs": M.eyfs(),
        "ks4_destinations": M.ks4_destinations(),
        "neet": M.neet(),
        "community_waits": M.community_waits(),
        "autism": M.autism(),
        "adhd": M.adhd(),
        "cyp_mental_health": M.cyp_mental_health(),
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
    ("places.html", "Places"),
    ("reviews.html", "Annual reviews"),
    ("outcomes.html", "Outcomes"),
    ("health.html", "Health"),
    ("disputes.html", "Complaints & appeals"),
    ("targets.html", "Targets"),
    ("deadlines.html", "Deadlines"),
    ("inspection.html", "Inspection"),
    ("money.html", "Money"),
    ("sources.html", "Sources"),
]

# Plain-language answers for families starting out. Linked from the home page
# rather than the menu.
GUIDES = [
    ("ehcp-waiting-time.html", "How long does an EHC plan take?"),
    ("autism-assessment-waiting-time.html", "How long is the wait for an autism assessment?"),
    ("adhd-assessment-waiting-time.html", "How long is the wait for an ADHD assessment?"),
]


def asset(path):
    """URL for a file in site/static/, versioned by its content so browsers
    fetch the new copy as soon as it changes rather than when their cache expires."""
    digest = hashlib.sha256((SITE / "static" / path).read_bytes()).hexdigest()[:10]
    return f"static/{path}?v={digest}"


def main():
    d = compute()
    local = read_yaml("council_reported.yaml")
    inspection = read_yaml("inspection.yaml")
    releases = read_yaml("release_calendar.yaml")

    env = Environment(loader=FileSystemLoader(SITE / "templates"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["month"] = long_month
    env.globals.update(figure=figure, cite=cite, cite_dfe=cite_dfe, fmt=fmt, rank_text=rank_text, sn_rank_text=sn_rank_text,
                       ordinal=ordinal, charts=charts, Markup=Markup, WF=M.WF, AREAS=AREAS, pages=PAGES,
                       guides=GUIDES, asset=asset, contact_email=CONTACT_EMAIL, domain=DOMAIN,
                       SN=M.SN, SN_MIN=M.SN_MIN, NEIGHBOURS=M.NEIGHBOURS)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    shutil.copytree(SITE / "static", OUT / "static")

    built = dt.date.today().isoformat()
    waits = wait_answers(d, local)
    ctx = dict(d=d, waits=waits, local=local, inspection=inspection, releases=releases, built=built, SOURCES=SOURCES,
               MANIFEST=MANIFEST, LGO_MANIFEST=LGO_MANIFEST, ONS_MANIFEST=ONS_MANIFEST, PUBS=PUBS, USED=USED, SN_CFG=SN_CFG)
    # sources.html last, so it can list every citation the other pages used
    for name, _ in PAGES + GUIDES:
        if name == "sources.html":
            continue
        html = env.get_template(name).render(page=name, **ctx)
        (OUT / name).write_text(html, encoding="utf-8")
    (OUT / "sources.html").write_text(env.get_template("sources.html").render(page="sources.html", **ctx), encoding="utf-8")

    # downloadable data
    for f in (ROOT / "data" / "dfe").glob("*"):
        shutil.copy(f, OUT / "data" / f.name)
    shutil.copy(ROOT / "data" / "ons" / "population.csv", OUT / "data" / "ons_population.csv")
    for f in (ROOT / "data" / "lgo").glob("*.csv"):
        shutil.copy(f, OUT / "data" / f"ombudsman_{f.name}")
    shutil.copy(ROOT / "data" / "gias" / "specialist_settings.csv", OUT / "data" / "gias_specialist_settings.csv")
    for f in (ROOT / "data" / "spend").glob("*.csv"):
        shutil.copy(f, OUT / "data" / f"spend_{f.name}")
    shutil.copy(ROOT / "data" / "contracts" / "notices.csv", OUT / "data" / "contract_notices.csv")
    for f in (ROOT / "data" / "local").glob("*.yaml"):
        shutil.copy(f, OUT / "data" / f.name)
    write_csv(OUT / "data" / "headlines.csv", headline_rows(d, local))
    # NHS extracts are folders of CSVs, so publish each dataset as one zip
    for ds in ("community_waits", "autism", "adhd", "mhsds"):
        src = ROOT / "data" / "nhs" / ds
        if src.is_dir() and any(src.iterdir()):
            shutil.make_archive(str(OUT / "data" / f"nhs_{ds}"), "zip", src)
    (OUT / ".nojekyll").write_text("")
    (OUT / "CNAME").write_text(DOMAIN + "\n")  # custom domain for GitHub Pages
    # for search engines; submit https://DOMAIN/sitemap.xml in Search Console
    urls = "".join(f"  <url><loc>https://{DOMAIN}/{'' if name == 'index.html' else name}</loc></url>\n"
                   for name, _ in PAGES + GUIDES)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n",
        encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: https://{DOMAIN}/sitemap.xml\n")
    # a plain-text map of the site for AI tools (https://llmstxt.org)
    lines = ["# Waltham Forest SEND data", "",
             "> Independent site showing how special educational needs and disability (SEND) services in Waltham "
             "Forest, London, are performing. Every figure links to a public source (DfE, NHS England, Ofsted, "
             "council papers). Not run by Waltham Forest Council.", "", "## Waiting times", ""]
    for name, title in GUIDES:
        lines.append(f"- [{title}](https://{DOMAIN}/{name}): {waits[name]['description']}")
    lines += ["", "## Data pages", ""]
    lines += [f"- [{label}](https://{DOMAIN}/{'' if name == 'index.html' else name})" for name, label in PAGES]
    lines += ["", "## Data", "", f"- [Headline figures (CSV)](https://{DOMAIN}/data/headlines.csv)", ""]
    (OUT / "llms.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Built {len(PAGES) + len(GUIDES)} pages into {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
