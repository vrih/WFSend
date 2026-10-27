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
import re
import shutil
import sys
from html import escape, unescape
from html.parser import HTMLParser
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
SITE_URL = f"https://{DOMAIN}/"
ORG_ID = SITE_URL + "#organization"
LICENCE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"

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
# Dates of the data on the page being rendered: when each DfE, NHS or other file
# was last downloaded with changed figures, or the date of each document quoted.
# The latest is the page's "figures last updated" date.
PAGE_DATES = set()
# Placeholders filled in once a page has rendered and its dates are known
JSONLD = Markup("<!--jsonld-->")
UPDATED = Markup("<!--updated-->")


def fmt(v, unit="percent"):
    return charts._fmt(v, unit)


def cite(source, page=None):
    """Inline citation link for a local document."""
    s = SOURCES[source]
    USED["local"].add(source)
    if "short" not in s:  # legislation is not data, and would date a page to 2014
        PAGE_DATES.add(str(s["date"]))
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
        PAGE_DATES.add(m["fetched"])
        pub = PUBS[m["publication"]]
        parts.append(
            f'DfE, <a class="cite" href="{escape(pub["url"])}" rel="noopener">{escape(pub["title"])}</a>: '
            f'<a class="cite" href="{escape(m["dataset_url"])}" rel="noopener">{escape(m["title"])}</a>'
            f' (downloaded {escape(m["fetched"])})'
        )
    return Markup("Source: " + "; ".join(parts))


def cite_ons():
    m = ONS_MANIFEST
    PAGE_DATES.add(m["fetched"])
    return Markup(f'ONS, <a class="cite" href="{escape(m["url"])}" rel="noopener">{escape(m["title"])}</a>: '
                  f'<a class="cite" href="{escape(m["dataset_url"])}" rel="noopener">{escape(m["dataset"])}</a>'
                  f' (downloaded {escape(m["fetched"])})')


def cite_moj(m):
    PAGE_DATES.add(m["fetched"])
    return Markup(f'{escape(m["publisher"])}, <a class="cite" href="{escape(m["url"])}" rel="noopener">{escape(m["title"])}</a>: '
                  f'<a class="cite" href="{escape(m["dataset_url"])}" rel="noopener">{escape(m["dataset"])}</a>'
                  f' (downloaded {escape(m["fetched"])})')


def fetched(manifest, key="fetched"):
    """A download date from a manifest, counted towards the page's date."""
    PAGE_DATES.add(manifest[key])
    return manifest[key]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-") or "section"


HEADING = re.compile(r"<(h[23])(\s[^>]*)?>(.*?)</\1>", re.S)
FIGURE = re.compile(r'<figure\b[^>]*\bid="([^"]+)"[^>]*>\s*<figcaption>\s*<h3', re.S)


def add_anchors(page):
    """Give every h2 and h3 an id, and a link to itself, so any section or chart
    can be linked to. A chart's heading links to its <figure> id."""
    taken = set(re.findall(r'\bid="([^"]+)"', page))
    figure_at = {m.end() - 3: m.group(1) for m in FIGURE.finditer(page)}  # offset of the <h3

    def heading(m):
        tag, attrs, inner = m.group(1), m.group(2) or "", m.group(3)
        if 'class="anchor"' in inner:
            return m.group(0)
        target = figure_at.get(m.start())
        if not target:
            found = re.search(r'\bid="([^"]+)"', attrs)
            if found:
                target = found.group(1)
            else:
                base = target = slug(re.sub(r"<[^>]+>", "", inner))
                n = 2
                while target in taken:
                    target, n = f"{base}-{n}", n + 1
                taken.add(target)
                attrs += f' id="{target}"'
        label = escape("Link to " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip(), quote=True)
        return f'<{tag}{attrs}>{inner}<a class="anchor" href="#{target}" aria-label="{label}"></a></{tag}>'

    return HEADING.sub(heading, page)


def figure(m, ranked=False, note=None, y_max=None, areas=AREAS, also=None, start=None):
    """A chart (or ranked bars) with legend, data table and source line.
    also: a second metric on the same measure (for example pupils on SEN
    support), shown as a table under the chart rather than a chart of its own.
    start: the first period to show."""
    periods = m["periods"][m["periods"].index(start):] if start else m["periods"]
    series = {a: m["series"].get(a, {}) for a in areas if m["series"].get(a)}
    parts = [f'<figure class="metric" id="{escape(m["id"])}">',
             f'<figcaption><h3>{escape(m["title"])}</h3><p class="explain">{escape(m["explain"])}</p></figcaption>']
    if len(periods) > 1:
        parts.append(charts.legend(series.keys()))
        parts.append(charts.line_chart(series, periods, unit=m["unit"], title=m["title"], y_max=y_max))
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
                 + charts.table(series, periods, unit=m["unit"]) + "</details>")
    if also:
        a_periods = [p for p in also["periods"] if p in periods] or also["periods"]
        a_series = {a: also["series"].get(a, {}) for a in areas if also["series"].get(a)}
        parts.append(f'<h4 class="sub">{escape(also["title"])}</h4>'
                     + charts.table(a_series, a_periods, unit=also["unit"]))
    if note:
        parts.append(f'<p class="note">{note}</p>')
    ons = f"; {cite_ons()}" if m.get("population") else ""
    src = Markup("Source: ") + cite_moj(m["manifest"]) if m.get("manifest") else cite_dfe(m["sources"])
    parts.append(f'<p class="source">{src}{ons}</p></figure>')
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
        out[page] = {"faq": faq, "description": faq[0][1], "teaser": teasers[page]}
    return out


def page_url(name):
    return SITE_URL + ("" if name == "index.html" else name)


def text_of(fragment):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def unique(items):
    return list(dict.fromkeys(items))


def page_info(name, html):
    """The title, description and main content of a rendered page."""
    return {"title": text_of(re.search(r"<title>(.*?) \| ", html).group(1)),
            "description": text_of(re.search(r'<meta name="description" content="([^"]*)"', html).group(1)),
            "main": re.search(r'<main id="main"[^>]*>(.*)</main>', html, re.S).group(1)}


def structured_data(name, info, updated, waits):
    """schema.org data for search engines and AI tools: who publishes the site,
    and what each page holds. Data pages are described as a Dataset, listing the
    charts as the variables measured, the sources cited and the files to download,
    so they can be found in Google Dataset Search."""
    url, main = page_url(name), info["main"]
    org = {"@type": "Organization", "@id": ORG_ID, "name": "Waltham Forest SEND data", "url": SITE_URL,
           "email": CONTACT_EMAIL, "logo": SITE_URL + "icon-512.png",
           "description": "An independent site showing how special educational needs and disability (SEND) services "
                          "in Waltham Forest are performing, from public sources. It is not run by or affiliated with "
                          "the London Borough of Waltham Forest."}
    graph = [org]
    if name == "index.html":
        graph.append({"@type": "WebSite", "@id": SITE_URL + "#website", "name": "Waltham Forest SEND data",
                      "url": SITE_URL, "inLanguage": "en-GB", "description": org["description"],
                      "publisher": {"@id": ORG_ID},
                      "about": {"@type": "Thing", "name": "Special educational needs and disability (SEND) "
                                                          "services in Waltham Forest, London"}})
    base = {"name": info["title"], "description": info["description"], "url": url, "inLanguage": "en-GB",
            "publisher": {"@id": ORG_ID}, "dateModified": updated}
    if name in waits:
        graph.append({"@type": "FAQPage", **base, "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in waits[name]["faq"]]})
    elif name in DATASETS:
        files = unique(re.findall(r'href="(data/[^"#]+)"', main) + (["data/headlines.csv"] if name == "index.html" else []))
        kind = {".csv": "text/csv", ".zip": "application/zip", ".yaml": "application/yaml"}
        graph.append({"@type": "Dataset", "@id": url + "#dataset", **base, "creator": {"@id": ORG_ID},
                      "isAccessibleForFree": True, "license": LICENCE_URL,
                      "spatialCoverage": {"@type": "Place", "name": "London Borough of Waltham Forest, England"},
                      "variableMeasured": unique(text_of(h) for pair in re.findall(  # headline tiles and charts
                          r'<p class="label">(.*?)</p>|<figure\b[^>]*>\s*<figcaption>\s*<h3[^>]*>(.*?)</h3>', main, re.S)
                          for h in pair if h),
                      "isBasedOn": unique(unescape(u) for u in re.findall(r'<a class="cite" href="([^"]+)"', main)),
                      "distribution": [{"@type": "DataDownload", "contentUrl": SITE_URL + f,
                                        "encodingFormat": kind[Path(f).suffix]} for f in files]})
    else:
        graph.append({"@type": "WebPage", **base})
    graph = [{k: v for k, v in g.items() if v} for g in graph]
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{ld}</script>'


class PlainText(HTMLParser):
    """Turns a page's main content into Markdown for llms-full.txt: headings,
    paragraphs, lists, links and the "Show the numbers" tables. Charts are left
    out because every chart's numbers are in its table."""
    SKIP = {"svg", "script", "style", "summary", "form", "button"}
    BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "figcaption", "dt", "dd", "div", "ul", "ol", "table", "details"}

    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.out, self.buf, self.skip, self.links, self.prefix = url, [], [], [], [], ""
        self.rows = self.row = None
        self.spans, self.in_list = [], False

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if self.row is not None:
            if self.row:
                self.row[-1] += text
        elif text:
            if self.prefix == "- " and self.in_list:  # list items on consecutive lines
                self.out[-1] += "\n- " + text
            else:
                self.out.append(self.prefix + text)
            self.in_list = self.prefix == "- "
        self.prefix = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.skip or tag in self.SKIP or "anchor" in (a.get("class") or "").split() or a.get("aria-hidden") == "true":
            if tag not in ("br", "input", "img", "meta", "hr"):
                self.skip.append(tag)
            return
        if tag in self.BLOCKS or tag in ("tr", "th", "td"):
            self.flush()
        if tag in ("h1", "h2", "h3", "h4"):
            self.prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self.prefix = "- "
        elif tag == "blockquote":
            self.prefix = "> "
        elif tag == "table":
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.row = []
            self.rows.append(self.row)
        elif tag in ("th", "td") and self.row is not None:
            self.row.append("")
        elif tag == "a":
            href = a.get("href") or ""
            if href.startswith("#"):
                href = self.url + href
            elif href and not re.match(r"[a-z]+:", href):
                href = SITE_URL + href
            self.links.append((len(self.buf), href))
        elif tag == "br":
            self.buf.append(" ")
        elif tag == "span":  # ranked bars: "1. Sutton: 87.5%"
            cls = a.get("class") or ""
            self.spans.append(". " if cls == "rn" else "")
            if cls == "val":
                self.buf.append(": ")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag == "a" and self.links:
            start, href = self.links.pop()
            text = "".join(self.buf[start:]).strip()
            if text and href:
                self.buf[start:] = [f"[{text}]({href})"]
        elif tag == "span" and self.spans:
            self.buf.append(self.spans.pop())
        elif tag in ("th", "td"):
            self.flush()
        elif tag == "tr":
            self.row = None
        elif tag == "table" and self.rows is not None:
            rows, self.rows = [r for r in self.rows if any(r)], None
            if rows:
                width = max(len(r) for r in rows)
                rows = [[c.replace("|", "\\|") for c in r] + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(r) + " |" for r in rows]
                lines.insert(1, "|" + " --- |" * width)
                self.out.append("\n".join(lines))
        elif tag in self.BLOCKS:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def text(self):
        self.flush()
        return "\n\n".join(self.out) + "\n"


def plain_text(name, main):
    parser = PlainText(page_url(name))
    parser.feed(main)
    return parser.text()


def long_date(iso):
    return dt.date.fromisoformat(iso).strftime("%-d %B %Y")


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
        "placement_counts": M.placement_counts(),
        "primary_need": M.primary_need(),
        "special_schools": M.special_schools(),
        "specialist_units": M.specialist_units(),
        "specialist_settings": M.specialist_settings(),
        "school_sen": M.school_sen(),
        "specialist_forecasts": M.specialist_forecasts(),
        "home_education": M.home_education(),
        "missing_education": M.missing_education(),
        "ehcp_home_educated": M.ehcp_home_educated(),
        "ehcp_school_age_neet": M.ehcp_school_age_neet(),
        "prevalence": M.sen_prevalence(),
        "ar": ar,
        "appeal_rate": M.appeal_rate(),
        "tribunal_outcomes": M.tribunal_outcomes(),
        "ks2": M.ks2(),
        "ks4": M.ks4(),
        "exclusions": M.exclusions(),
        "exclusion_counts": M.exclusion_counts(),
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
    ("targets.html", "Inspection & targets"),
    ("money.html", "Money"),
    ("resources.html", "Resources"),
    ("sources.html", "Sources"),
]

# Pages that sit under a menu item rather than in the menu, with the item
# they belong to
SUBPAGES = [
    ("deadlines.html", "Deadlines calculator", "resources.html"),
    ("schools.html", "SEND in each school", "places.html"),
    ("spending.html", "Where the money goes", "money.html"),
]
SECTION = {name: parent for name, _, parent in SUBPAGES}
# Subpages of each menu item, shown as tabs on the item and its subpages
CHILDREN = {}
for _name, _label, _parent in SUBPAGES:
    CHILDREN.setdefault(_parent, []).append((_name, _label))

# Old addresses, sent on to where their content now lives
REDIRECTS = {
    "inspection.html": "targets.html#inspection",
}

# Plain-language answers for families starting out. Linked from the home page
# rather than the menu.
GUIDES = [
    ("ehcp-waiting-time.html", "How long does an EHC plan take?"),
    ("autism-assessment-waiting-time.html", "How long is the wait for an autism assessment?"),
    ("adhd-assessment-waiting-time.html", "How long is the wait for an ADHD assessment?"),
]

# Pages described to search engines as a Dataset
DATASETS = ({name for name, _ in PAGES} | {name for name, _, parent in SUBPAGES if parent != "resources.html"}) - {"resources.html", "sources.html"}


def asset(path):
    """URL for a file in site/static/, versioned by its content so browsers
    fetch the new copy as soon as it changes rather than when their cache expires."""
    digest = hashlib.sha256((SITE / "static" / path).read_bytes()).hexdigest()[:10]
    return f"static/{path}?v={digest}"


def main():
    d = compute()
    local = read_yaml("council_reported.yaml")
    foi = read_yaml("foi.yaml")["responses"]
    inspection = read_yaml("inspection.yaml")
    releases = read_yaml("release_calendar.yaml")

    env = Environment(loader=FileSystemLoader(SITE / "templates"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["month"] = long_month
    env.globals.update(figure=figure, cite=cite, cite_dfe=cite_dfe, cite_moj=cite_moj, fmt=fmt, rank_text=rank_text, sn_rank_text=sn_rank_text,
                       ordinal=ordinal, charts=charts, Markup=Markup, WF=M.WF, AREAS=AREAS, pages=PAGES, section=SECTION, subpages=CHILDREN,
                       guides=GUIDES, asset=asset, contact_email=CONTACT_EMAIL, domain=DOMAIN, fetched=fetched,
                       JSONLD=JSONLD, UPDATED=UPDATED, root="",
                       SN=M.SN, SN_MIN=M.SN_MIN, NEIGHBOURS=M.NEIGHBOURS)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    shutil.copytree(SITE / "static", OUT / "static")
    # browsers and iOS look for these at the site root, whatever the page links to
    for f in (SITE / "icons").iterdir():
        shutil.copy(f, OUT / f.name)
    (OUT / "site.webmanifest").write_text(json.dumps({
        "name": "Waltham Forest SEND data", "short_name": "WF SEND data", "start_url": "./",
        "display": "browser", "background_color": "#f7f6f1", "theme_color": "#24543a",
        "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
    }, indent=2) + "\n", encoding="utf-8")

    built = dt.date.today().isoformat()
    waits = wait_answers(d, local)
    ctx = dict(d=d, waits=waits, local=local, foi=foi, inspection=inspection, releases=releases, built=built, SOURCES=SOURCES,
               MANIFEST=MANIFEST, LGO_MANIFEST=LGO_MANIFEST, ONS_MANIFEST=ONS_MANIFEST, PUBS=PUBS, USED=USED, SN_CFG=SN_CFG)
    # sources.html last, so it can list every citation the other pages used
    rendered = {}
    names = [n for n, _ in PAGES] + [n for n, _, _ in SUBPAGES] + [n for n, _ in GUIDES]
    for name in sorted(names, key=lambda n: n == "sources.html"):
        PAGE_DATES.clear()
        html = add_anchors(env.get_template(name).render(page=name, **ctx))
        rendered[name] = (html, max(PAGE_DATES, default=None))
    info = {}
    for name, (html, updated) in rendered.items():
        info[name] = page_info(name, html)
        html = html.replace(JSONLD, structured_data(name, info[name], updated, waits))
        html = html.replace(UPDATED, f"Figures last updated {long_date(updated)}. " if updated else "")
        (OUT / name).write_text(html, encoding="utf-8")
    for name, target in REDIRECTS.items():
        (OUT / name).write_text(
            f'<!doctype html>\n<html lang="en-GB">\n<head>\n<meta charset="utf-8">\n<title>Moved | Waltham Forest SEND data</title>\n'
            f'<meta name="robots" content="noindex">\n<link rel="canonical" href="{SITE_URL}{target.split("#")[0]}">\n'
            f'<meta http-equiv="refresh" content="0; url={target}">\n</head>\n'
            f'<body>\n<p>This page has moved to <a href="{target}">{SITE_URL}{target}</a>.</p>\n</body>\n</html>\n',
            encoding="utf-8")
    # GitHub Pages serves this for any missing address, so its links start from the site root
    html = env.get_template("404.html").render(page="404.html", **{**ctx, "root": "/"})
    (OUT / "404.html").write_text(add_anchors(html).replace(JSONLD, "").replace(UPDATED, ""), encoding="utf-8")

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
    shutil.copy(ROOT / "data" / "moj" / "send_tribunal.csv", OUT / "data" / "moj_send_tribunal.csv")
    for f in [*(ROOT / "data" / "local").glob("*.yaml"), *(ROOT / "data" / "local").glob("*.csv")]:
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
    urls = "".join(f"  <url><loc>{page_url(name)}</loc>"
                   + (f"<lastmod>{rendered[name][1]}</lastmod>" if rendered[name][1] else "") + "</url>\n"
                   for name in names)
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
    lines += [f"- [{label}]({page_url(name)}): {info[name]['description']}" for name, label in PAGES]
    lines += [f"- [{label}]({page_url(name)}): {info[name]['description']}" for name, label, _ in SUBPAGES]
    lines += ["", "## Data", "",
              f"- [Every page as plain text]({SITE_URL}llms-full.txt): all the figures, tables and sources in one file",
              f"- [Headline figures (CSV)]({SITE_URL}data/headlines.csv)", ""]
    (OUT / "llms.txt").write_text("\n".join(lines), encoding="utf-8")
    full = [f"# Waltham Forest SEND data: every page\n\n> {lines[2][2:]}\n\n"
            "Each page below is converted from the website. Charts are left out: their figures are in the tables. "
            f"Links in brackets are the public sources. Built {built}.\n"]
    for name in names:
        updated = rendered[name][1]
        full.append(f"---\n\nPage: {page_url(name)}\n" + (f"Figures last updated: {updated}\n" if updated else "")
                    + "\n" + plain_text(name, info[name]["main"]))
    (OUT / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")
    print(f"Built {len(names)} pages into {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
