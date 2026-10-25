"""Metrics computed from the DfE extracts in data/dfe/.

Each metric function returns a dict with the series for Waltham Forest,
London and England, the latest London ranking where one makes sense, and the
manifest keys of the files it was computed from (used for source links).
Rates are recomputed from counts where DfE publishes counts, so the
calculation is visible here rather than taken on trust.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DFE = ROOT / "data" / "dfe"
WF = "Waltham Forest"
SUPPRESSED = {"", "x", "c", "z", "u", "low", "~", ":", ".."}


def load(key):
    with (DFE / f"{key}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(s):
    s = (s or "").strip().replace(",", "")
    if s in SUPPRESSED:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pct(a, b):
    return 100 * a / b if a is not None and b else None


def area_of(row):
    lvl = row["geographic_level"]
    if lvl == "National":
        return "England"
    if lvl == "Regional":
        return "London" if row.get("region_name") == "London" else None
    if lvl == "Local authority":
        name = row.get("la_name")
        return None if name == "City of London" else name  # too small to compare
    return None


def academic(p):
    """'202526' -> '2025/26'."""
    return f"{p[:4]}/{p[4:]}" if len(p) == 6 else p


def january(p):
    """Academic year of a January census -> 'Jan 2026'."""
    return f"Jan {int(p[:4]) + 1}" if len(p) == 6 else p


def build(series_by_area, periods, **meta):
    """Package a metric. series_by_area includes every London borough."""
    main = {a: series_by_area.get(a, {}) for a in (WF, "London", "England")}
    latest = periods[-1]
    boroughs = {a: s.get(latest) for a, s in series_by_area.items() if a not in ("London", "England")}
    boroughs = {a: v for a, v in boroughs.items() if v is not None}
    hib = meta.get("higher_is_better", True)
    rank = None
    if WF in boroughs and len(boroughs) > 5 and meta.get("rank", True):
        order = sorted(boroughs, key=lambda a: boroughs[a], reverse=hib)
        rank = {"pos": order.index(WF) + 1, "of": len(order)}
    # latest period where Waltham Forest has a value
    wf_latest = next((p for p in reversed(periods) if main[WF].get(p) is not None), None)
    return {
        "series": main,
        "periods": periods,
        "latest_period": latest,
        "wf_latest_period": wf_latest,
        "latest": {a: main[a].get(latest) for a in main},
        "boroughs": boroughs,
        "rank": rank,
        **meta,
    }


def collect(rows, value_fn, period_fn=lambda r: r["time_period"], label=lambda p: p):
    out, periods = {}, set()
    for r in rows:
        a = area_of(r)
        if not a:
            continue
        v = value_fn(r)
        p = label(period_fn(r))
        periods.add(p)
        out.setdefault(a, {})[p] = v
    return out, sorted(periods)


# --- EHC needs assessments and plans --------------------------------------

def timeliness():
    rows = [r for r in load("ehcp_timeliness") if r["exemptions_flag"] == "Excluding exemptions"]
    tot = {(area_of(r), r["time_period"]): num(r["ehc_plan_count"]) for r in rows if r["timeliness"] == "Total plans issued"}
    series, periods = {}, set()
    for r in rows:
        if r["timeliness"] != "Plans issued within 20 weeks" or not area_of(r):
            continue
        a, p = area_of(r), r["time_period"]
        periods.add(p)
        series.setdefault(a, {})[p] = pct(num(r["ehc_plan_count"]), tot.get((a, p)))
    return build(series, sorted(periods), id="timeliness", unit="percent",
                 title="New EHC plans issued within 20 weeks",
                 short="Plans issued on time",
                 explain="The share of new EHC plans finalised within the 20-week legal deadline, not counting cases where a legal exception applies. Calendar years.",
                 sources=["ehcp_timeliness"])


def plans_issued():
    rows = [r for r in load("ehcp_timeliness")
            if r["exemptions_flag"] == "Including exemptions" and r["timeliness"] == "Total plans issued"]
    series, periods = collect(rows, lambda r: num(r["ehc_plan_count"]))
    return build(series, periods, id="plans_issued", unit="count", rank=False,
                 title="New EHC plans issued each year",
                 explain="The number of new EHC plans issued in each calendar year, including those where an exception applied.",
                 sources=["ehcp_timeliness"])


def requests():
    rows = [r for r in load("ehcp_requests") if r["request_type"] == "Total" and r["request_outcome"] == "Total"]
    series, periods = collect(rows, lambda r: num(r["request_count"]))
    return build(series, periods, id="requests", unit="count", rank=False,
                 title="Requests for an EHC needs assessment",
                 explain="The number of new requests for an EHC needs assessment the council received each calendar year.",
                 sources=["ehcp_requests"])


def request_outcomes():
    """Share of requests refused, and share with no recorded decision."""
    rows = [r for r in load("ehcp_requests") if r["request_type"] == "Total"]
    by = {}
    for r in rows:
        a = area_of(r)
        if a:
            by.setdefault((a, r["time_period"]), {})[r["request_outcome"]] = num(r["request_count"])
    refused, undecided, six, periods = {}, {}, {}, set()
    for (a, p), d in by.items():
        total = d.get("Total")
        if d.get("Requests decided to assess") is None:
            continue  # outcome split only published from 2023
        periods.add(p)
        refused.setdefault(a, {})[p] = pct(d.get("Requests decided not to assess"), total)
        undecided.setdefault(a, {})[p] = pct(d.get("Requests decision not made"), total)
        decided6 = d.get("Request outcome six weeks")
        over6 = d.get("Request outcome over 6 weeks")
        six.setdefault(a, {})[p] = pct(decided6, (decided6 or 0) + (over6 or 0)) if decided6 is not None else None
    periods = sorted(periods)
    common = dict(unit="percent", sources=["ehcp_requests"])
    return {
        "refused": build(refused, periods, id="refused", rank=False, higher_is_better=False,
                         title="Requests refused (decided not to assess)",
                         explain="Requests where the council decided not to carry out an assessment, as a share of all requests received in the year.", **common),
        "undecided": build(undecided, periods, id="undecided", rank=False, higher_is_better=False,
                           title="Requests with no decision recorded",
                           explain="Requests received in the year with no decision recorded by the time of the DfE data return.", **common),
        "six_weeks": build(six, periods, id="six_weeks",
                           title="Decisions on whether to assess made within 6 weeks",
                           explain="Of the requests decided, the share where the council said within 6 weeks whether it would assess. This is the legal deadline.", **common),
    }


def caseload():
    rows = [r for r in load("ehcp_caseload") if r["setting_type"] == "Total"]
    series, periods = collect(rows, lambda r: num(r["ehc_plan_count"]), label=january)
    periods = sorted(periods, key=lambda p: int(p[-4:]))
    return build(series, periods, id="caseload", unit="count", rank=False,
                 title="EHC plans maintained by the council",
                 explain="All EHC plans (ages 0 to 25) the council maintains, counted each January.",
                 sources=["ehcp_caseload"])


def caseload_growth():
    m = caseload()
    out = {}
    first, last = m["periods"][0], m["periods"][-1]
    for a, s in m["series"].items():
        if s.get(first) and s.get(last):
            out[a] = 100 * (s[last] / s[first] - 1)
    return {"from": first, "to": last, "growth": out}


PLACEMENT_GROUPS = [
    ("Mainstream school", "Mainstream total"),
    ("Special school", "Special total"),
    ("of which independent special", "Special independent"),
    ("Further education", "Total further Education"),
    ("Alternative provision / PRU", "AP PRU total"),
    ("Educated elsewhere", "Total educated elsewhere"),
    ("Not in education, employment or training", "Not in employment, education or training"),
]


def placements():
    rows = load("ehcp_caseload")
    latest = max(r["time_period"] for r in rows)
    vals = {}
    for r in rows:
        a = area_of(r)
        if a in (WF, "London", "England") and r["time_period"] == latest:
            vals.setdefault(a, {})[r["setting_type"]] = num(r["ehc_plan_count"])
    table = []
    for label, setting in PLACEMENT_GROUPS:
        table.append({"label": label, **{a: pct(vals[a].get(setting), vals[a].get("Total")) for a in vals}})
    return {"period": january(latest), "rows": table, "sources": ["ehcp_caseload"],
            "title": "Where children and young people with EHC plans are placed"}


def assessments_not_issued():
    rows = load("ehcp_assessments")

    def v(r):
        issued, not_issued = num(r["assess_issued"]), num(r["assess_not_issued"])
        return pct(not_issued, (issued or 0) + (not_issued or 0)) if not_issued is not None else None
    series, periods = collect(rows, v)
    return build(series, periods, id="not_issued", unit="percent", rank=False, higher_is_better=False,
                 title="Assessments that ended without a plan",
                 explain="Of the EHC needs assessments completed in the year, the share where the council decided not to issue a plan.",
                 sources=["ehcp_assessments"])


def annual_reviews():
    rows = load("ehcp_annual_reviews")
    out = {}
    for r in rows:
        a = area_of(r)
        if not a:
            continue
        expected = num(r["review_expected_2025"])
        done = num(r["review_completed_2025"])
        d4, dover = num(r["decision_4_weeks"]), num(r["decision_over_4_weeks"])
        out[a] = {
            "plans": num(r["total_ehc_plans"]),
            "expected": expected,
            "completed": done,
            "not_completed": num(r["review_not_completed"]),
            "completed_pct": pct(done, expected),
            "not_completed_pct": pct(num(r["review_not_completed"]), expected),
            "decision_4wk_pct": pct(d4, (d4 or 0) + (dover or 0)) if d4 is not None else None,
            "d4": d4, "dover": dover,
        }
    period = rows[0]["time_period"]
    completed = build({a: {period: d["completed_pct"]} for a, d in out.items()}, [period],
                      id="ar_completed", unit="percent",
                      title="Annual reviews due in 2025 that were completed in 2025",
                      explain="EHC plans due a review in 2025, and the share where the review was completed in the year.",
                      sources=["ehcp_annual_reviews"])
    decision = build({a: {period: d["decision_4wk_pct"]} for a, d in out.items()}, [period],
                     id="ar_decision", unit="percent",
                     title="Annual review decisions made within 4 weeks",
                     explain="Of the annual reviews completed, the share where the council issued its decision within the legal 4 weeks of the review meeting.",
                     sources=["ehcp_annual_reviews"])
    return {"period": period, "detail": out, "completed": completed, "decision": decision}


def appeal_rate():
    rows = load("send_appeal_rate")
    series, periods = {}, set()
    appeals = {}
    for r in rows:
        a = r["area"] if r["area"] != "City of London" else None
        if not a:
            continue
        p = r["time_period"]
        periods.add(p)
        series.setdefault(a, {})[p] = num(r["appeal_rate"])
        appeals.setdefault(a, {})[p] = num(r["appeals"])
    m = build(series, sorted(periods), id="appeal_rate", unit="percent", higher_is_better=False,
              title="SEND Tribunal appeal rate",
              explain="Appeals registered with the SEND Tribunal as a share of all decisions that could be appealed, such as refusals to assess, plans issued or not, annual review outcomes and plans ceased. Calendar years.",
              sources=["send_appeal_rate"])
    m["appeals"] = appeals
    return m


# --- Prevalence ------------------------------------------------------------

def sen_prevalence():
    rows = load("sen_pupils")
    ehcp, support = {}, {}
    periods = set()
    for r in rows:
        a = area_of(r)
        if not a:
            continue
        p = january(r["time_period"])
        periods.add(p)
        if r["sen_provision"] == "Education, health and care plan":
            ehcp.setdefault(a, {})[p] = num(r["pupil_percent"])
        elif r["sen_provision"] == "SEN support / SEN without an EHC plan":
            support.setdefault(a, {})[p] = num(r["pupil_percent"])
    periods = sorted(periods, key=lambda p: int(p[-4:]))
    common = dict(unit="percent", rank=False, sources=["sen_pupils"])
    return {
        "ehcp": build(ehcp, periods, id="pupils_ehcp", title="Pupils with an EHC plan",
                      explain="Pupils in the borough's schools with an EHC plan, as a share of all pupils. School census, January.", **common),
        "support": build(support, periods, id="pupils_support", title="Pupils on SEN support",
                         explain="Pupils whose needs are met through SEN support without an EHC plan, as a share of all pupils. School census, January.", **common),
    }


# --- Outcomes --------------------------------------------------------------

def ks2():
    rows = load("ks2_attainment")
    res = {}
    for group in ("Education, health and care plan", "SEN support / SEN without an EHC plan", "No SEN provision"):
        def v(r, g=group):
            if r["sen_provision"] != g:
                return None
            return pct(num(r["expected_standard_pupil_count"]), num(r["eligible_pupil_count"]))
        sub = [r for r in rows if r["sen_provision"] == group]
        series, periods = collect(sub, v, label=academic)
        res[group] = build(series, periods, unit="percent", rank=False, sources=["ks2_attainment"],
                           id="ks2_" + group[:4].lower(),
                           title=f"Meeting the expected standard in reading, writing and maths (KS2): {short_group(group)}",
                           explain="Pupils at the end of primary school (Year 6) reaching the expected standard in all three of reading, writing and maths. No tests were taken in 2019/20 or 2020/21.")
    return res


def short_group(g):
    return {"Education, health and care plan": "pupils with an EHC plan",
            "SEN support / SEN without an EHC plan": "pupils on SEN support",
            "No SEN provision": "pupils with no SEN"}.get(g, g)


def ks4():
    rows = load("ks4_sen")
    res = {}
    for group in ("Education, health and care plan", "SEN support / SEN without an EHC plan", "No SEN provision"):
        sub = [r for r in rows if r["breakdown"] == group]
        a8s, periods = collect(sub, lambda r: num(r["attainment8_average"]), label=academic)
        ems, _ = collect(sub, lambda r: num(r["engmath_94_percent"]), label=academic)
        res[group] = {
            "a8": build(a8s, periods, unit="score", rank=False, sources=["ks4_sen"], id="a8",
                        title=f"Average Attainment 8 score: {short_group(group)}",
                        explain="Average GCSE-equivalent score across eight subjects at the end of Year 11, in all state-funded schools (including special schools)."),
            "em": build(ems, periods, unit="percent", rank=False, sources=["ks4_sen"], id="em",
                        title=f"Grade 4 or above in English and maths GCSE: {short_group(group)}",
                        explain="Pupils at the end of Year 11 achieving at least a grade 4 (a standard pass) in both English and maths, in all state-funded schools."),
        }
    return res


def exclusions():
    rows = load("exclusions_characteristics")
    res = {}
    for ch, label in (("EHC plan", "pupils with an EHC plan"), ("SEN support", "pupils on SEN support"), ("No identified SEN", "pupils with no SEN")):
        sub = [r for r in rows if r["characteristic"] == ch]
        susp, periods = collect(sub, lambda r: num(r["susp_rate"]), label=academic)
        perm, _ = collect(sub, lambda r: num(r["perm_excl_rate"]), label=academic)
        res[ch] = {
            "susp": build(susp, periods, unit="score", rank=False, higher_is_better=False, sources=["exclusions_characteristics"],
                          id="susp", title=f"Suspensions per 100 {label}",
                          explain="The number of suspensions in the school year for every 100 pupils in the group. One pupil can be suspended more than once."),
            "perm": build(perm, periods, unit="score", rank=False, higher_is_better=False, sources=["exclusions_characteristics"],
                          id="perm", title=f"Permanent exclusions per 100 {label}",
                          explain="Permanent exclusions in the school year for every 100 pupils in the group."),
        }
    return res


# --- Local Government and Social Care Ombudsman ---------------------------

LGO = ROOT / "data" / "lgo"
SEND_CATEGORY = "Special educational needs"


def _lgo(name):
    with (LGO / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ombudsman():
    """Published Ombudsman decisions about SEND, by reporting year (April to March),
    plus the Ombudsman's headline statistics for all council services."""
    decisions = _lgo("decisions.csv")
    send = sorted((d for d in decisions if d["category"] == SEND_CATEGORY),
                  key=lambda d: d["date"], reverse=True)
    years = sorted({d["reporting_year"] for d in decisions})
    by_year = []
    for y in years:
        ds = [d for d in send if d["reporting_year"] == y]
        by_year.append({
            "year": y,
            "published": len(ds),
            "upheld": sum(d["outcome"] == "Upheld" for d in ds),
            "not_upheld": sum(d["outcome"] == "Not upheld" for d in ds),
            "closed": sum(d["outcome"] == "Closed after initial enquiries" for d in ds),
            "all_published": sum(d["reporting_year"] == y for d in decisions),
        })
    # The Ombudsman deletes decision statements after five years, so the first
    # year is incomplete; the current reporting year is still in progress.
    fetched = json.loads((LGO / "manifest.json").read_text())["fetched"]
    fy, fm = int(fetched[:4]), int(fetched[5:7])
    current = f"{fy if fm >= 4 else fy - 1}/{str((fy if fm >= 4 else fy - 1) + 1)[2:]}"
    for i, row in enumerate(by_year):
        row["partial"] = "year to date" if row["year"] == current else ("incomplete: older decisions deleted" if i == 0 else "")
    stats = []
    for r in _lgo("annual_stats.csv"):
        stats.append({k: (num(v) if k != "reporting_year" else v) for k, v in r.items()})
    return {"send": send, "by_year": by_year, "stats": stats}
