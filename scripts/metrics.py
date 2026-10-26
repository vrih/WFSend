"""Metrics computed from the DfE extracts in data/dfe/.

Each metric function returns a dict with the series for Waltham Forest,
London, England and its statistical neighbours ("Similar areas"), the latest
London ranking where one makes sense, and the manifest keys of the files it
was computed from (used for source links).
Rates are recomputed from counts where DfE publishes counts, so the
calculation is visible here rather than taken on trust.
"""
import csv
import datetime as dt
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DFE = ROOT / "data" / "dfe"
ONS = ROOT / "data" / "ons"
WF = "Waltham Forest"
SUPPRESSED = {"", "x", "c", "z", "u", "low", "~", ":", ".."}

# Statistical neighbours: the DfE's 10 councils most like Waltham Forest.
_SN = yaml.safe_load((ROOT / "data" / "dfe_sources.yaml").read_text())["statistical_neighbours"]["areas"]
NEIGHBOURS = [a["name"] for a in _SN]
OUTSIDE_LONDON = {a["name"] for a in _SN if a["region"] != "London"}  # kept out of London rankings
SN = "Similar areas"
SN_MIN = 7  # neighbours with a value needed before an average is shown


def sn_average(values):
    """Simple average over the neighbours, as the DfE's LAIT tool does."""
    vs = [values.get(a) for a in NEIGHBOURS]
    vs = [v for v in vs if v is not None]
    return sum(vs) / len(vs) if len(vs) >= SN_MIN else None


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


def _rank(values, hib):
    v = values[WF]
    better = sum(1 for x in values.values() if (x > v if hib else x < v))
    tied = sum(1 for x in values.values() if x == v) > 1
    return {"pos": better + 1, "of": len(values), "joint": tied}


def build(series_by_area, periods, **meta):
    """Package a metric. series_by_area includes every London borough and
    the statistical neighbours."""
    main = {a: series_by_area.get(a, {}) for a in (WF, "London", "England")}
    # Averaging counts across councils of different sizes means nothing, so
    # the neighbour average is only given for rates, shares and spend per head.
    if meta.get("unit") != "count":
        main[SN] = {p: sn_average({a: series_by_area.get(a, {}).get(p) for a in NEIGHBOURS}) for p in periods}
    latest = periods[-1]
    boroughs = {a: s.get(latest) for a, s in series_by_area.items()
                if a not in ("London", "England") and a not in OUTSIDE_LONDON}
    boroughs = {a: v for a, v in boroughs.items() if v is not None}
    neighbours = {a: series_by_area.get(a, {}).get(latest) for a in [WF] + NEIGHBOURS}
    neighbours = {a: v for a, v in neighbours.items() if v is not None}
    hib = meta.get("higher_is_better", True)
    rank = sn_rank = None
    if meta.pop("rank", True):
        if WF in boroughs and len(boroughs) > 5:
            rank = _rank(boroughs, hib)
        if WF in neighbours and len(neighbours) > SN_MIN:
            sn_rank = _rank(neighbours, hib)
    # latest period where Waltham Forest has a value
    wf_latest = next((p for p in reversed(periods) if main[WF].get(p) is not None), None)
    return {
        "series": main,
        "periods": periods,
        "latest_period": latest,
        "wf_latest_period": wf_latest,
        "latest": {a: main[a].get(latest) for a in main},
        "boroughs": boroughs,
        "neighbours": neighbours,
        "rank": rank,
        "sn_rank": sn_rank,
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


TIMELINESS_BANDS = (("within20", "Plans issued within 20 weeks"),
                    ("20to52", "Plans issued between 20 and 52 weeks"),
                    ("over52", "Plans issued after 52 weeks"))


def timeliness_bands():
    """How long new plans took, in the DfE's three bands, as shares of all plans
    issued in the year (excluding exemptions, as timeliness() does)."""
    rows = [r for r in load("ehcp_timeliness") if r["exemptions_flag"] == "Excluding exemptions"
            and r["breakdown_topic"].lower().startswith("all ehc plans") and area_of(r) in (WF, "London", "England")]
    by = {}
    for r in rows:
        by.setdefault(r["time_period"], {}).setdefault(area_of(r), {})[r["timeliness"]] = num(r["ehc_plan_count"])
    out = {}
    for p, areas in sorted(by.items()):
        out[p] = {a: {"total": v.get("Total plans issued"),
                      **{k: pct(v.get(label), v.get("Total plans issued")) for k, label in TIMELINESS_BANDS}}
                  for a, v in areas.items()}
    periods = [p for p in out if all(out[p].get(a, {}).get("over52") is not None for a in (WF, "London", "England"))]
    return {"periods": periods, "latest_period": periods[-1], "values": out, "sources": ["ehcp_timeliness"]}


def plans_issued():
    rows = [r for r in load("ehcp_timeliness")
            if r["exemptions_flag"] == "Including exemptions" and r["timeliness"] == "Total plans issued"]
    series, periods = collect(rows, lambda r: num(r["ehc_plan_count"]))
    return build(series, periods, id="plans_issued", unit="count", rank=False,
                 title="New EHC plans issued each year",
                 explain="The number of new EHC plans issued in each calendar year, including those where an exception applied.",
                 sources=["ehcp_timeliness"])


def _request_counts():
    rows = [r for r in load("ehcp_requests") if r["request_type"] == "Total" and r["request_outcome"] == "Total"]
    return collect(rows, lambda r: num(r["request_count"]))


def requests():
    series, periods = _request_counts()
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


# --- Rates per 1,000 children ----------------------------------------------
# Counts are divided by the ONS mid-year estimate of children aged 2 to 18,
# where most EHC plans are. A wider 0 to 25 base would be swayed by the
# number of students and young workers, which is higher in London.

def population():
    """{area: {mid-year: people aged 2 to 18}}, summed from single years of age."""
    out = {}
    with (ONS / "population.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            a = None if r["area_name"] == "City of London" else r["area_name"]
            if a:
                out.setdefault(a, {}).setdefault(int(r["year"]), 0)
                out[a][int(r["year"])] += int(r["population"])
    return out


def per_1000(counts, periods, year_of, **meta):
    """Rate per 1,000 children aged 2 to 18 from {area: {period: count}}.
    year_of maps a period to the mid-year population estimate used."""
    pop = population()
    periods = [p for p in periods if year_of(p) in pop["England"]]
    series = {a: {p: 1000 * s[p] / pop[a][year_of(p)] if s.get(p) is not None and year_of(p) in pop.get(a, {}) else None
                  for p in periods}
              for a, s in counts.items()}
    children = {p: pop[WF][year_of(p)] for p in periods if year_of(p) in pop.get(WF, {})}
    return build(series, periods, unit="rate", rank_label="highest", population=True, wf_children=children, **meta)


def requests_rate():
    return per_1000(*_request_counts(), int, id="requests_rate",
                    title="Requests for an assessment per 1,000 children aged 2 to 18",
                    explain="Requests for an EHC needs assessment received in the calendar year, for every 1,000 children aged 2 to 18 living in the area. Population from the ONS estimate for June of that year.",
                    sources=["ehcp_requests"])


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
        if a in (WF, "London", "England", *NEIGHBOURS) and r["time_period"] == latest:
            vals.setdefault(a, {})[r["setting_type"]] = num(r["ehc_plan_count"])
    table = []
    for label, setting in PLACEMENT_GROUPS:
        shares = {a: pct(vals[a].get(setting), vals[a].get("Total")) for a in vals}
        table.append({"label": label, **{a: shares[a] for a in (WF, "London", "England")}, SN: sn_average(shares)})
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
    rows = [r for r in load("sen_pupils") if r["phase_type_grouping"] == "Total"]
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


SCHOOL_PHASES = {"State-funded primary": "primary", "State-funded secondary": "secondary"}


def school_sen():
    """Pupils with an EHC plan or on SEN support in each Waltham Forest mainstream
    school, from the DfE's school-level file, with the borough, London and England
    shares for the same phase from the main SEN file."""
    rows = load("sen_schools")
    period = january(rows[0]["time_period"])
    schools = {}
    for r in rows:
        if r["phase_type_grouping"] not in SCHOOL_PHASES:
            continue
        s = schools.setdefault(r["school_urn"], {"urn": r["school_urn"], "name": r["school_name"],
                                                 "phase": SCHOOL_PHASES[r["phase_type_grouping"]],
                                                 "type": r["establishment_type"], "rp": False, "unit": False})
        unit, prov, n = r["specialist_provision_unit_type"], r["sen_provision"], num(r["pupil_count"])
        if unit == "Resourced provision":
            s["rp"] = bool(n)  # 1 if the school has resourced provision, not a pupil count
        elif unit == "SEN unit":
            s["unit"] = bool(n)
        elif prov == "All pupils":
            s["pupils"] = n
        elif prov == "Education, health and care plans":
            s["ehcp"] = n
        elif prov == "SEN support":
            s["support"] = n
    for s in schools.values():
        s["ehcp_pct"] = pct(s["ehcp"], s["pupils"])
        s["support_pct"] = pct(s["support"], s["pupils"])

    wanted = {"Education, health and care plan": "ehcp", "SEN support / SEN without an EHC plan": "support"}
    areas = {}
    for r in load("sen_pupils"):
        a = area_of(r)
        if (a in (WF, "London", "England") and january(r["time_period"]) == period
                and r["phase_type_grouping"] in SCHOOL_PHASES and r["establishment_type"] == "Total"
                and r["sen_provision"] in wanted):
            areas.setdefault(SCHOOL_PHASES[r["phase_type_grouping"]], {}).setdefault(a, {})[wanted[r["sen_provision"]]] = num(r["pupil_percent"])

    phases = {}
    for ph in SCHOOL_PHASES.values():
        ss = sorted((s for s in schools.values() if s["phase"] == ph), key=lambda s: s["name"])
        by_ehcp = sorted(ss, key=lambda s: s["ehcp_pct"])
        phases[ph] = {
            "schools": ss,
            "areas": areas[ph],
            "lowest": by_ehcp[0],
            "highest": by_ehcp[-1],
            "median": by_ehcp[len(by_ehcp) // 2]["ehcp_pct"] if len(by_ehcp) % 2 else
                      (by_ehcp[len(by_ehcp) // 2 - 1]["ehcp_pct"] + by_ehcp[len(by_ehcp) // 2]["ehcp_pct"]) / 2,
            "with_provision": [s for s in ss if s["rp"] or s["unit"]],
        }
    return {"period": period, "phases": phases, "sources": ["sen_schools", "sen_pupils"]}


NEED_SHORT = {
    "Autistic spectrum disorder": "autism",
    "Speech, language and communications needs": "speech, language and communication needs",
    "Social, emotional and mental health": "social, emotional and mental health needs",
    "Moderate learning difficulty": "moderate learning difficulty",
    "Severe learning difficulty": "severe learning difficulty",
}


def primary_need():
    """Pupils' primary type of need, as a share of pupils with an EHC plan or
    on SEN support. School census, so it counts pupils at the borough's schools."""
    rows = load("sen_primary_need")
    counts = {}  # (provision, need, area, period) -> pupils
    for r in rows:
        a = area_of(r)
        if a:
            counts[(r["sen_provision"], r["sen_primary_need"], a, january(r["time_period"]))] = num(r["pupil_count"])
    periods = sorted({k[3] for k in counts}, key=lambda p: int(p[-4:]))
    latest = periods[-1]
    areas = {k[2] for k in counts}
    out = {"period": latest, "sources": ["sen_primary_need"]}
    for key, prov in (("ehcp", "Education, health and care plan"), ("support", "SEN support / SEN without an EHC plan")):
        needs = sorted({k[1] for k in counts if k[0] == prov} - {"Total"})
        share = {n: {a: {p: pct(counts.get((prov, n, a, p)), counts.get((prov, "Total", a, p))) for p in periods}
                     for a in areas} for n in needs}
        rows_ = []
        for n in needs:
            vals = {a: share[n][a][latest] for a in areas}
            rows_.append({"label": n, "count": counts.get((prov, n, WF, latest)),
                          **{a: vals.get(a) for a in (WF, "London", "England")}, SN: sn_average(vals)})
        rows_ = [r for r in rows_ if any(r[a] for a in (WF, "London", "England"))]  # e.g. "Unknown", always 0
        rows_.sort(key=lambda r: -(r[WF] or 0))
        group = "pupils with an EHC plan" if key == "ehcp" else "pupils on SEN support"
        # trend charts for the three most common needs in Waltham Forest
        trends = [build({a: share[r["label"]][a] for a in areas}, periods, id=f"need_{key}_{i}", unit="percent", rank=False,
                        title=f"Primary need is {NEED_SHORT.get(r['label'], r['label'].lower())}: share of {group}",
                        explain=f"Of {group} at schools in the area, the share whose main (primary) need is recorded as {r['label'].lower()}. School census, January.",
                        sources=["sen_primary_need"])
                  for i, r in enumerate(rows_[:3])]
        out[key] = {"rows": rows_, "total": counts.get((prov, "Total", WF, latest)), "trends": trends,
                    "title": f"Primary type of need: {group}, {latest}"}
    return out


# --- Outcomes --------------------------------------------------------------

# Suffixes for figure ids, so each pupil group's chart has its own anchor.
# Every outcome breakdown lists the groups in this order.
GROUP_IDS = ("ehcp", "support", "nosen")

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
    for g, group in zip(GROUP_IDS, ("Education, health and care plan", "SEN support / SEN without an EHC plan", "No SEN provision")):
        sub = [r for r in rows if r["breakdown"] == group]
        a8s, periods = collect(sub, lambda r: num(r["attainment8_average"]), label=academic)
        ems, _ = collect(sub, lambda r: num(r["engmath_94_percent"]), label=academic)
        res[group] = {
            "a8": build(a8s, periods, unit="score", rank=False, sources=["ks4_sen"], id=f"a8_{g}",
                        title=f"Average Attainment 8 score: {short_group(group)}",
                        explain="Average GCSE-equivalent score across eight subjects at the end of Year 11, in all state-funded schools (including special schools)."),
            "em": build(ems, periods, unit="percent", rank=False, sources=["ks4_sen"], id=f"em_{g}",
                        title=f"Grade 4 or above in English and maths GCSE: {short_group(group)}",
                        explain="Pupils at the end of Year 11 achieving at least a grade 4 (a standard pass) in both English and maths, in all state-funded schools."),
        }
    return res


def exclusions():
    rows = load("exclusions_characteristics")
    res = {}
    for g, (ch, label) in zip(GROUP_IDS, (("EHC plan", "pupils with an EHC plan"), ("SEN support", "pupils on SEN support"), ("No identified SEN", "pupils with no SEN"))):
        sub = [r for r in rows if r["characteristic"] == ch]
        susp, periods = collect(sub, lambda r: num(r["susp_rate"]), label=academic)
        perm, _ = collect(sub, lambda r: num(r["perm_excl_rate"]), label=academic)
        res[ch] = {
            "susp": build(susp, periods, unit="score", rank=False, higher_is_better=False, sources=["exclusions_characteristics"],
                          id=f"susp_{g}", title=f"Suspensions per 100 {label}",
                          explain="The number of suspensions in the school year for every 100 pupils in the group. One pupil can be suspended more than once."),
            "perm": build(perm, periods, unit="score", rank=False, higher_is_better=False, sources=["exclusions_characteristics"],
                          id=f"perm_{g}", title=f"Permanent exclusions per 100 {label}",
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


# --- Spending (section 251 outturn) ---------------------------------------

SPEND_LINES = [
    ("2.1.1", "Educational psychology service", "ep"),
    ("2.1.2", "SEN administration, assessment and coordination", "sen_admin"),
    ("1.2.3", "Top-up funding for independent and non-maintained providers", "independent"),
    ("2.1.4", "SEN transport (under 16)", "transport"),
    ("1.2.1", "Top-up funding for maintained schools", "topup_maintained"),
    ("1.2.2", "Top-up funding for academies, free schools and colleges", "topup_academies"),
]


def spending():
    rows = load("s251_outturn")
    out = {}
    for code, label, key in SPEND_LINES:
        sub = [r for r in rows if r["category_of_expenditure"].startswith(code + " ")]
        per_head, periods = collect(sub, lambda r: num(r["net_per_capita_expenditure"]), label=academic)
        total, _ = collect(sub, lambda r: (num(r["net_expenditure"]) or 0) / 1e6 if num(r["net_expenditure"]) is not None else None, label=academic)
        out[key] = {
            "label": label,
            "code": code,
            "total": total.get(WF, {}),
            "per_head": build(per_head, periods, id=f"spend_{key}", unit="gbp", rank_label="highest",
                              title=f"{label}: net spend per head",
                              explain="Net spending per head as published by the DfE. The population used depends on the budget line (pupils or children), so compare places on the same line, not different lines.",
                              sources=["s251_outturn"]),
        }
    periods = out["ep"]["per_head"]["periods"]
    return {"lines": out, "periods": periods}


# --- Contracts (Contracts Finder and Find a Tender notices) ----------------

CONTRACTS = ROOT / "data" / "contracts"
# A notice is about SEND if its title or description matches one of these.
# "SEND" is matched in capitals only, so the verb "send" doesn't count.
SEND_NOTICE = re.compile(r"\bSEND\b|(?i:special educational|\bEHC|education,? health and care|home to school|"
                         r"travel assistance|travel training|short breaks?\b|disabled child|alternative provision|high needs|"
                         r"\btuition\b|autis|resourced provision|special school|educational psycholog|"
                         r"speech and language|occupational therap|delivering better value|safety valve|"
                         r"disagreement resolution)")
# Adult services that mention autism or learning disability.
NOT_SEND = re.compile(r"(?i)supported living|supported employment")
UPCOMING_MONTHS = 24
# Plain names for Contracts Finder notice types and Find a Tender release tags.
STAGES = [("tender", "Tender"), ("Opportunity", "Tender"), ("planning", "Planned"), ("Pipeline", "Planned"),
          ("FutureOpportunity", "Planned"), ("EarlyEngagement", "Early market engagement")]


def _stage(stage):
    """Find a Tender tags can carry a suffix, such as "planningUpdate"."""
    tags = stage.split(", ")
    return next((label for key, label in STAGES if any(t == key or t.startswith(key) for t in tags)), stage)


def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def contracts():
    """The council's SEND procurement notices: contracts awarded, and procurements
    announced in the last UPCOMING_MONTHS months with no award notice yet."""
    manifest = json.loads((CONTRACTS / "manifest.json").read_text())
    with (CONTRACTS / "notices.csv").open(encoding="utf-8") as f:
        notices = [n for n in csv.DictReader(f)
                   if SEND_NOTICE.search(n["title"] + " " + n["description"]) and not NOT_SEND.search(n["title"])]
    for n in notices:
        n["amount"] = num(n["awarded_value"]) or num(n["value"]) or num(n["value_high"])
        n["awarded"] = bool(n["suppliers"])
        n["stage_label"] = _stage(n["stage"])
        names = [s.strip() for s in re.split(r"[;,]", n["suppliers"]) if s.strip()]
        n["supplier_short"] = ", ".join(names[:3]) + (f" and {len(names) - 3} others" if len(names) > 3 else "")
        # A wider contract mentions SEND only further into its description,
        # not in its title or opening words.
        n["wider"] = not SEND_NOTICE.search(n["title"] + " " + n["description"][:200])

    # The same award is often published on both services, or more than once.
    # Keep one per title and supplier list, preferring Find a Tender.
    awarded, seen = [], set()
    for n in sorted((n for n in notices if n["awarded"]), key=lambda n: (n["source"] != "Find a Tender", n["published"])):
        key = (_norm(n["title"]), _norm(n["suppliers"])[:30])
        if key not in seen:
            seen.add(key)
            awarded.append(n)
    awarded.sort(key=lambda n: n["published"], reverse=True)

    fetched = dt.date.fromisoformat(manifest["fetched"])
    since = dt.date(fetched.year - UPCOMING_MONTHS // 12, fetched.month, 1).isoformat()
    done = {n["procurement_id"] for n in awarded} | {_norm(n["title"]) for n in awarded if n["published"] >= since}
    upcoming, seen = [], set()
    for n in sorted((n for n in notices if not n["awarded"] and n["published"] >= since),
                    key=lambda n: n["published"], reverse=True):
        key = _norm(n["title"])
        if n["procurement_id"] in done or key in done or key in seen or n["status"].lower() in ("withdrawn", "cancelled"):
            continue
        seen.add(key)
        upcoming.append(n)
    return {"awarded": awarded, "upcoming": upcoming, "since": since,
            "since_label": dt.date.fromisoformat(since).strftime("%B %Y"), "manifest": manifest}


# --- Payments to suppliers (council transparency reports) ------------------

SPEND = ROOT / "data" / "spend"
# From the April 2026 report the council lists far fewer payments each month,
# across every service, not just SEND. Only financial years up to March 2026
# are shown until the council explains the change or republishes those months.
SPEND_LAST_COMPLETE = (2026, 3)
TOP_SUPPLIERS = 15


def supplier_payments():
    """SEND payments over £500 by service and financial year (April to March),
    and the largest suppliers in the latest complete year."""
    manifest = json.loads((SPEND / "manifest.json").read_text())
    with (SPEND / "reports.csv").open(encoding="utf-8") as f:
        reports = list(csv.DictReader(f))
    with (SPEND / "send_payments.csv").open(encoding="utf-8") as f:
        payments = list(csv.DictReader(f))

    def ym(r):
        return int(r["report_month"][:4]), int(r["report_month"][5:])

    def fy(m):
        y = m[0] if m[1] >= 4 else m[0] - 1
        return f"{y}/{str(y + 1)[2:]}"

    first = tuple(int(x) for x in payments[0]["report_month"].split("-"))
    months = {ym(r) for r in reports if first <= ym(r) <= SPEND_LAST_COMPLETE}
    years = sorted({fy(m) for m in months if sum(fy(n) == fy(m) for n in months) == 12})
    rows = [dict(p, year=fy(ym(p)), amount=float(p["Invoice Amount"])) for p in payments if fy(ym(p)) in years]

    services = []
    for code in manifest["send_services"]:
        rs = [r for r in rows if r["Service"][:6] == code]
        if not rs:
            continue
        services.append({
            "label": rs[-1]["Service"][7:],  # the latest name the council uses
            "total": {y: sum(r["amount"] for r in rs if r["year"] == y) for y in years},
            "payments": {y: sum(r["year"] == y for r in rs) for y in years},
        })
    services.sort(key=lambda s: -s["total"][years[-1]])

    latest = [r for r in rows if r["year"] == years[-1]]
    by_supplier = {}
    for r in latest:
        s = by_supplier.setdefault(r["Supplier Name"], {"name": r["Supplier Name"], "total": 0, "payments": 0, "by_service": {}})
        s["total"] += r["amount"]
        s["payments"] += 1
        s["by_service"][r["Service"][7:]] = s["by_service"].get(r["Service"][7:], 0) + r["amount"]
    top = sorted(by_supplier.values(), key=lambda s: -s["total"])[:TOP_SUPPLIERS]
    for s in top:
        s["service"] = max(s["by_service"], key=s["by_service"].get)

    def per_report(sel):
        rs = [r for r in reports if sel(ym(r))]
        return {"reports": len(rs), "payments": sum(int(r["payments"]) for r in rs) / len(rs) if rs else None}

    return {
        "years": years,
        "latest_year": years[-1],
        "services": services,
        "total": {y: sum(r["amount"] for r in rows if r["year"] == y) for y in years},
        "count": {y: sum(r["year"] == y for r in rows) for y in years},
        "top": top,
        "suppliers": len(by_supplier),
        "top_share": 100 * sum(s["total"] for s in top) / sum(s["total"] for s in by_supplier.values()),
        "redacted": by_supplier.get("REDACTED PERSONAL DATA", {"total": 0, "payments": 0}),
        "before": per_report(lambda m: fy(m) == years[-1]),
        "after": per_report(lambda m: m > SPEND_LAST_COMPLETE),
        "first_report": manifest["first_report"],
        "first_coded_label": dt.date(*first, 1).strftime("%B %Y"),
        "manifest": manifest,
    }


# --- More outcomes ----------------------------------------------------------

def absence():
    rows = load("absence_sen")
    res = {}
    for g, (group, label) in zip(GROUP_IDS, (("EHC plan", "pupils with an EHC plan"), ("SEN support", "pupils on SEN support"), ("No identified SEN", "pupils with no SEN"))):
        sub = [r for r in rows if r["characteristic_breakdown"] == group]
        overall, periods = collect(sub, lambda r: num(r["sess_overall_percent"]), label=academic)
        persistent, _ = collect(sub, lambda r: num(r["enrolments_pa_10_exact_percent"]), label=academic)
        res[group] = {
            "overall": build(overall, periods, id=f"abs_overall_{g}", unit="percent", rank=False, higher_is_better=False,
                             title=f"Overall absence: {label}",
                             explain="Share of school sessions missed, for any reason, in the autumn and spring terms. Each year's figure covers those two terms only.",
                             sources=["absence_sen"]),
            "persistent": build(persistent, periods, id=f"abs_persistent_{g}", unit="percent", higher_is_better=False,
                                title=f"Persistently absent: {label}",
                                explain="Share of pupils who missed 10% or more of sessions in the autumn and spring terms.",
                                sources=["absence_sen"]),
        }
    return res


def eyfs():
    rows = load("eyfs_sen")
    res = {}
    for g, (group, label) in zip(GROUP_IDS, (("Education, health and care plan", "children with an EHC plan"),
                                             ("SEN support / SEN without an EHC plan", "children on SEN support"),
                                             ("No SEN provision", "children with no SEN"))):
        sub = [r for r in rows if r["breakdown"] == group]
        series, periods = collect(sub, lambda r: num(r["gld_children_percent"]), label=academic)
        res[group] = build(series, periods, id=f"eyfs_gld_{g}", unit="percent", rank=False,
                           title=f"Good level of development at the end of Reception: {label}",
                           explain="Children reaching the expected level in the early learning goals for communication, physical development, personal and social development, literacy and maths, assessed at the end of Reception.",
                           sources=["eyfs_sen"])
    return res


def ks4_destinations():
    rows = [r for r in load("ks4_destinations_sen")
            if r["destination_description"] == "Sustained education, employment & apprenticeships"]
    # Use revised figures where both versions exist for a year.
    best = {}
    for r in rows:
        k = (area_of(r), r["time_period"], r["breakdown"])
        if k[0] and (k not in best or r["version"] == "Revised"):
            best[k] = r
    res = {}
    for g, (group, label) in zip(GROUP_IDS, (("SEN with EHC plan or statement", "pupils with an EHC plan"), ("SEN support", "pupils on SEN support"), ("No identified SEN", "pupils with no SEN"))):
        series, periods = collect([r for r in best.values() if r["breakdown"] == group],
                                  lambda r: num(r["pupil_percent"]), label=academic)
        res[group] = build(series, periods, id=f"ks4_dest_{g}", unit="percent", rank=False,
                           title=f"In education, employment or an apprenticeship after Year 11: {label}",
                           explain="Pupils who stayed in education, employment or an apprenticeship for at least two terms in the year after finishing Year 11. The year shown is the year they left Year 11. The latest year is provisional.",
                           sources=["ks4_destinations_sen"])
    return res


def neet():
    rows = [r for r in load("neet_sen") if r["age"] == "16 to 17"]
    res = {}
    for g, (group, label) in zip(GROUP_IDS, (("SEN EHC/statement", "young people with an EHC plan"), ("SEN support", "young people on SEN support"), ("No SEN", "young people with no SEN"))):
        series, periods = collect([r for r in rows if r["characteristic"] == group],
                                  lambda r: num(r["neet_nk_percent"]))
        res[group] = build(series, periods, id=f"neet_{g}", unit="percent", higher_is_better=False,
                           title=f"16 and 17 year olds not in education, employment or training, or not known: {label}",
                           explain="Average of December, January and February. Includes young people whose activity the council does not know, as the DfE's headline measure does.",
                           sources=["neet_sen"])
    return res


# --- NHS community health services waiting lists (hand-downloaded) --------

NHS = ROOT / "data" / "nhs"
CHS_SERVICES = [
    ("(CYP) Community paediatric service", "Community paediatrics"),
    ("(CYP) Therapy interventions: Speech and language", "Speech and language therapy"),
    ("(CYP) Therapy interventions: Occupational therapy", "Occupational therapy"),
    ("(CYP) Therapy interventions: Physiotherapy", "Physiotherapy"),
]
CHS_AREAS = {"RAT": "NELFT", "QMF": "North East London", "Y56": "London", "": "England"}
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}


def _chs_table(path):
    """Read one extracted 'Table 4x' sheet: returns (month, {area: {service: value}})."""
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    title = rows[0][0]
    m = re.search(r"(" + "|".join(MONTHS) + r") (\d{4})", title)
    month = (int(m.group(2)), MONTHS[m.group(1)]) if m else None
    header = next(r for r in rows if r[:2] == ["Organisation Type", "Organisation Code"])
    out = {}
    for r in rows[rows.index(header) + 1:]:
        if len(r) < 3:
            continue
        code = "" if r[0] == "National" else r[1]
        if code in CHS_AREAS:
            out[CHS_AREAS[code]] = {h: num(r[i]) if i < len(r) else None for i, h in enumerate(header)}
    return month, out


def community_waits():
    folders = sorted(p for p in (NHS / "community_waits").glob("*/") if (p / "source.json").exists())
    if not folders:
        return None
    months = {}
    for folder in folders:
        tables = {}
        for key in ("Table_4", "Table_4f", "Table_4g", "Table_4h"):
            hits = list(folder.glob(f"*__{key}.csv"))
            if hits:
                tables[key] = _chs_table(hits[0])
        if "Table_4" not in tables:
            continue
        month = tables["Table_4"][0]
        src = json.loads((folder / "source.json").read_text())
        months[month] = {"tables": tables, "source": src}
    order = sorted(months)
    label = lambda ym: f"{list(MONTHS)[ym[1] - 1][:3]} {ym[0]}"
    periods = [label(m) for m in order]

    services = []
    for col, name in CHS_SERVICES:
        total, over18, over52, pct18 = {}, {}, {}, {}
        for ym in order:
            t = months[ym]["tables"]
            p = label(ym)
            for area in CHS_AREAS.values():
                get = lambda k: t.get(k, (None, {}))[1].get(area, {}).get(col)
                tot = get("Table_4")
                bands = [get(k) for k in ("Table_4f", "Table_4g", "Table_4h")]
                o18 = sum(b for b in bands if b is not None) if any(b is not None for b in bands) else None
                o52 = sum(b for b in bands[1:] if b is not None) if any(b is not None for b in bands[1:]) else None
                total.setdefault(area, {})[p] = tot
                over18.setdefault(area, {})[p] = o18
                over52.setdefault(area, {})[p] = o52
                pct18.setdefault(area, {})[p] = pct(o18, tot) if tot else None
        services.append({
            "name": name, "column": col, "total": total, "over18": over18, "over52": over52,
            "pct18": {"id": "chs_" + re.sub(r"\W+", "_", name.lower()), "unit": "percent",
                      "title": f"Children waiting over 18 weeks: {name.lower()}",
                      "explain": "Share of children on the waiting list who had waited more than 18 weeks at the end of the month.",
                      "series": {a: pct18.get(a, {}) for a in ("NELFT", "London", "England")},
                      "periods": periods, "sources": [], "boroughs": {}, "rank": None,
                      "latest_period": periods[-1]},
        })
    latest = order[-1]
    return {"periods": periods, "latest": label(latest), "services": services,
            "sources": [months[m]["source"] for m in order]}


# NHS England autism waiting time statistics (long format, one row per metric).
# NELFT is the provider; QMF counts patients by GP practice or residence in NEL.
AUTISM_AREAS = {"RAT": "NELFT", "QMF": "North East London", "Y56": "London", "England": "England"}
AUTISM_METRICS = ("ASD16b", "ASD16c", "ASD25a")
# From April 2026 NELFT's children's figures fall by almost 90% in one month
# (4,305 to 505 children waiting). NHS England gives no reason, so months from
# here on are shown separately rather than joined onto the trend.
AUTISM_BREAK = (2026, 4)


def autism():
    folders = sorted(p for p in (NHS / "autism").glob("*/") if (p / "source.json").exists())
    if not folders:
        return None
    vals = {}  # (year, month) -> area -> metric -> value
    sources = []
    for folder in folders:  # later releases sort last, so they win for any overlap
        sources.append(json.loads((folder / "source.json").read_text()))
        for f in folder.glob("AutismStats_*.csv"):
            if f.name.startswith("AutismStatsDQ"):
                continue
            with f.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    area = AUTISM_AREAS.get(r["PRIMARY_LEVEL"])
                    if not area or "Age Group" in r["BREAKDOWN"] or r["METRIC"] not in AUTISM_METRICS:
                        continue
                    d, m, y = r["REPORTING_PERIOD_START"].split("/")
                    vals.setdefault((int(y), int(m)), {}).setdefault(area, {})[r["METRIC"]] = num(r["METRIC_VALUE"])
    label = lambda ym: f"{list(MONTHS)[ym[1] - 1][:3]} {ym[0]}"
    order = sorted(vals)

    def series(fn, months):
        return {a: {label(ym): fn(vals[ym].get(a, {})) for ym in months} for a in AUTISM_AREAS.values()}

    waiting = lambda v: v.get("ASD16b")
    over13 = lambda v: pct(v.get("ASD16c"), v["ASD16b"]) if v.get("ASD16b") else None
    median = lambda v: v.get("ASD25a")
    before = [ym for ym in order if ym < AUTISM_BREAK]
    after = [ym for ym in order if ym >= AUTISM_BREAK]

    def metric(id_, fn, unit, title, explain):
        s = series(fn, before)
        top = max((v for a in s.values() for v in a.values() if v is not None), default=0)
        return {"id": id_, "unit": unit, "title": title, "explain": explain, "series": s,
                "periods": [label(m) for m in before],
                # round the axis up to a multiple of 400 so the 4 gridlines land on round numbers
                "y_max": 100 if unit == "percent" else -(-top // 400) * 400 or None}
    return {
        "latest": label(before[-1]),
        "periods": [label(m) for m in before],
        "after_periods": [label(m) for m in after],
        "waiting": metric("autism_waiting", waiting, "count", "Children with an open autism referral",
                          "Children aged 0 to 17 with a suspected autism referral still open at the end of the month."),
        "over13": metric("autism_over13", over13, "percent", "Children whose autism referral has been open 13 weeks or more",
                         "Share of children with an open suspected autism referral whose referral had been open for at least 13 weeks."),
        "median": metric("autism_median", median, "count", "Median wait for a first appointment (days)",
                         "Median days from referral to first appointment, for children whose first appointment was in the quarter up to that month."),
        "after": {k: series(fn, after) for k, fn in (("waiting", waiting), ("over13", over13), ("median", median))},
        "sources": sources,
    }


# --- School places and children out of school ------------------------------

TERMS = {"Autumn term": (0, "Autumn"), "Spring term": (1, "Spring"), "Summer term": (2, "Summer")}


def _term_label(r):
    """'202526' + 'Autumn term' -> 'Autumn 2025'; spring and summer fall in the second year."""
    order, name = TERMS[r["time_identifier"]]
    year = int(r["time_period"][:4]) + (0 if order == 0 else 1)
    return f"{name} {year}"


def _termly(key, **meta):
    rows = [r for r in load(key) if r["breakdown"] == "Total"]
    series, _ = collect(rows, lambda r: num(r["rate_per_100"]), period_fn=_term_label)
    order = sorted({(r["time_period"], TERMS[r["time_identifier"]][0]): _term_label(r) for r in rows}.items())
    # No ranking: the DfE rounds rates to one decimal place, so most boroughs tie.
    m = build(series, [label for _, label in order], unit="score", rank=False, **meta)
    counts, _ = collect(rows, lambda r: num(r["child_count"]), period_fn=_term_label)
    m["wf_count"] = counts.get(WF, {}).get(m["latest_period"])
    return m


def home_education():
    return _termly("ehe_census", id="ehe_rate", sources=["ehe_census"],
                   title="Children electively home educated, per 100 children",
                   explain="Children of compulsory school age whose parents have chosen to educate them at home, on the census day each term, for every 100 children living in the area. The DfE publishes this rate to one decimal place.")


def missing_education():
    return _termly("cme_census", id="cme_rate", sources=["cme_census"],
                   title="Children missing education, per 100 children",
                   explain="Children of compulsory school age who are not on a school roll and not receiving a suitable education otherwise, on the census day each term, for every 100 children living in the area. Counts are rounded by the DfE.")


def ehcp_home_educated():
    """EHC plans where the child is electively home educated, as a share of all plans."""
    rows = load("ehcp_caseload")
    by = {}
    for r in rows:
        a = area_of(r)
        if a:
            by.setdefault((a, january(r["time_period"])), {})[r["setting_type"]] = num(r["ehc_plan_count"])
    series, other = {}, {}
    for (a, p), d in by.items():
        series.setdefault(a, {})[p] = pct(d.get("Elective home education"), d.get("Total"))
        other.setdefault(a, {})[p] = d.get("Other arrangements parents")
    periods = sorted({p for _, p in by}, key=lambda p: int(p[-4:]))
    periods = [p for p in periods if series.get("England", {}).get(p) is not None]  # not published before 2020
    m = build(series, periods, id="ehcp_ehe", unit="percent", rank=False,
              title="EHC plans where the child is home educated",
              explain="Plans where the setting recorded is elective home education, as a share of all plans the council maintains. Counted each January.",
              sources=["ehcp_caseload"])
    m["counts"] = {p: by.get((WF, p), {}).get("Elective home education") for p in periods}
    m["other"] = {p: other.get(WF, {}).get(p) for p in periods}
    return m


def _region_of(row):
    return "London" if row.get("region_code") in ("E12000007", "E13000001", "E13000002") else None


def special_schools():
    """Special school places and pupils on roll, added up from the school-level file."""
    rows = load("special_school_capacity")
    periods = sorted({r["time_period"] for r in rows})
    tot = {}  # (area, period) -> [places, pupils]
    schools = []
    for r in rows:
        places, pupils = num(r["school_places"]), num(r["pupils_on_roll_count"])
        region = _region_of(r)
        la = r["la_name"] if region or r["la_name"] in NEIGHBOURS else None  # the file covers every school in England
        areas = {"England", la, region} - {None}
        for a in areas:
            t = tot.setdefault((a, r["time_period"]), [0, 0])
            t[0] += places or 0
            t[1] += pupils or 0
        if r["la_name"] == WF and r["time_period"] == periods[-1]:
            schools.append({"name": r["school_name"], "phase": r["education_phase"], "places": places, "pupils": pupils})
    occ = {}
    for (a, p), (places, pupils) in tot.items():
        occ.setdefault(a, {})[academic(p)] = pct(pupils, places)
    # Fuller isn't simply better or worse, so no ranking.
    m = build(occ, [academic(p) for p in periods], id="special_occupancy", unit="percent", rank=False,
              title="Special school places filled",
              explain="Pupils on roll in state-funded and non-maintained special schools in the area, as a share of the places the council reported each May. Over 100% means more pupils than places.",
              sources=["special_school_capacity"])
    m["schools"] = sorted(schools, key=lambda s: -(s["places"] or 0))
    m["wf_totals"] = {academic(p): tot.get((WF, p)) for p in periods}
    return m


def specialist_units():
    rows = [r for r in load("specialist_unit_capacity") if r["education_phase"] == "Total"]
    out = {}
    for r in rows:
        a = area_of(r)
        if a == WF:
            out[academic(r["time_period"])] = {
                "units": num(r["send_unit_capacity_count"]), "resourced": num(r["resourced_provision_capacity_count"]),
                "primary": (num(r["primary_send_unit_capacity_count"]) or 0) + (num(r["primary_resourced_provision_capacity_count"]) or 0),
                "secondary": (num(r["secondary_send_unit_capacity_count"]) or 0) + (num(r["secondary_resourced_provision_capacity_count"]) or 0),
            }
    return {"by_year": dict(sorted(out.items())), "sources": ["specialist_unit_capacity"]}


GIAS = ROOT / "data" / "gias"
GIAS_URL = "https://get-information-schools.service.gov.uk/Establishments/Establishment/Details/{urn}"


def _census_month(s):
    """'15-01-2026' -> 'January 2026'."""
    return f"{list(MONTHS)[int(s[3:5]) - 1]} {s[6:]}" if s else ""


def specialist_settings():
    """Waltham Forest's special schools, resourced provision and SEN units as
    listed on Get Information About Schools. Closed settings are kept in the
    extract but left out here."""
    with (GIAS / "specialist_settings.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    special, other = [], []
    for r in rows:
        status = r["EstablishmentStatus (name)"]
        if status == "Closed":
            continue
        # "ASD - Autistic Spectrum Disorder" -> "Autistic Spectrum Disorder"
        needs = [r[f"SEN{i} (name)"].split(" - ", 1)[-1] for i in range(1, 14) if r[f"SEN{i} (name)"]]
        s = {
            "urn": r["URN"], "url": GIAS_URL.format(urn=r["URN"]), "name": r["EstablishmentName"],
            "type": r["TypeOfEstablishment (name)"], "status": status,
            "phase": r["PhaseOfEducation (name)"], "ages": f'{r["StatutoryLowAge"]} to {r["StatutoryHighAge"]}',
            "capacity": num(r["SchoolCapacity"]), "pupils": num(r["NumberOfPupils"]), "census": _census_month(r["CensusDate"]),
            "provision": r["TypeOfResourcedProvision (name)"], "needs": needs,
            "rp_capacity": num(r["ResourcedProvisionCapacity"]), "rp_pupils": num(r["ResourcedProvisionOnRoll"]),
            "unit_capacity": num(r["SenUnitCapacity"]), "unit_pupils": num(r["SenUnitOnRoll"]),
        }
        # Special academies are grouped with other academies, so go by the type.
        (special if "special" in s["type"].lower() else other).append(s)
    manifest = json.loads((GIAS / "manifest.json").read_text())
    return {"special": sorted(special, key=lambda s: s["name"]), "other": sorted(other, key=lambda s: s["name"]),
            "manifest": manifest}


def specialist_forecasts():
    """Council forecasts of resident pupils with an EHC plan who will need a
    specialist place, indexed to the first forecast year so areas compare."""
    rows = [r for r in load("specialist_forecasts") if r["education_phase"] == "Total"]
    counts, periods = collect(rows, lambda r: num(r["pupil_forecast_and_202425_actuals"]), label=academic)
    periods = [p for p in periods if counts.get("England", {}).get(p) is not None]  # 2024/25 actuals are not published
    first = periods[0]
    index = {a: {p: 100 * s[p] / s[first] if s.get(p) is not None and s.get(first) else None for p in periods}
             for a, s in counts.items()}
    m = build(index, periods, id="specialist_forecast", unit="score", rank_label="fastest growth",
              title=f"Forecast growth in pupils needing a specialist place ({first} = 100)",
              explain=f"Each council's forecast of pupils living in its area, in Reception to Year 11, who will have an EHC plan and need a place in specialist provision: special schools, SEN units and resourced provision, independent and alternative provision. Shown as an index, where {first} = 100, so councils of different sizes can be compared.",
              sources=["specialist_forecasts"])
    m["wf_counts"] = counts.get(WF, {})
    m["england_counts"] = counts.get("England", {})
    return m


# --- NHS ADHD management information (hand-downloaded) --------------------

def _dmy(s):
    """'01/06/2026' -> (2026, 6). The national file sometimes uses '2026-06-01'."""
    if "/" in s:
        d, m, y = s.split("/")
    else:
        y, m, d = s.split("-")
    return int(y), int(m)


def _month(ym):
    return f"{list(MONTHS)[ym[1] - 1][:3]} {ym[0]}"


def _nhs_folders(name):
    return sorted(p for p in (NHS / name).glob("*/") if (p / "source.json").exists())


ADHD_AGE = "5 to 17"  # under-5s are almost all suppressed


def adhd():
    """People who may be waiting for an ADHD assessment (MHSDS referrals for
    neurodevelopmental conditions other than autism), children aged 5 to 17."""
    folders = _nhs_folders("adhd")
    if not folders:
        return None
    files = []
    for folder in folders:
        for f in folder.glob("*.csv"):
            with f.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            area = ("North East London" if "ICB_CODE" in rows[0] else "London" if "REGION_CODE" in rows[0] else "England")
            latest = max(_dmy(r["REPORTING_PERIOD_START_DATE"]) for r in rows)
            files.append((latest, area, rows))
    vals = {}  # (year, month) -> area -> indicator -> value
    for _, area, rows in sorted(files, key=lambda t: t[0]):  # later releases overwrite revised months
        for r in rows:
            if r["PRIMARY_LEVEL"] == ADHD_AGE:
                vals.setdefault(_dmy(r["REPORTING_PERIOD_START_DATE"]), {}).setdefault(area, {})[r["INDICATOR_ID"]] = num(r["VALUE"])
    order = sorted(m for m, v in vals.items() if all(v.get(a, {}).get("ADHD003") for a in ("North East London", "London", "England")))
    areas = ("North East London", "London", "England")

    def series(fn):
        return {a: {_month(m): fn(vals[m].get(a, {})) for m in order} for a in areas}

    def share(*ids):
        def f(v):
            parts = [v.get(i) for i in ids]
            return pct(sum(parts), v.get("ADHD003")) if None not in parts else None
        return f
    periods = [_month(m) for m in order]

    def metric(id_, fn, unit, title, explain):
        return {"id": id_, "unit": unit, "title": title, "explain": explain, "series": series(fn), "periods": periods}
    return {
        "latest": periods[-1], "periods": periods,
        "waiting": metric("adhd_waiting", lambda v: v.get("ADHD003"), "count", "Children with an open referral",
                          "Children aged 5 to 17 with an open referral that may be for an ADHD assessment, at the end of the month."),
        "over52": metric("adhd_over52", share("ADHD003c", "ADHD003d"), "percent", "Open referrals that have been open for a year or more",
                         "Of children aged 5 to 17 with an open referral, the share whose referral had been open 52 weeks or more."),
        "over104": metric("adhd_over104", share("ADHD003d"), "percent", "Open referrals that have been open for two years or more",
                          "Of children aged 5 to 17 with an open referral, the share whose referral had been open 104 weeks or more."),
        "no_contact": metric("adhd_no_contact", share("ADHD004"), "percent", "Open referrals with no contact yet",
                             "Of children aged 5 to 17 with an open referral, the share who had not yet had any contact with the service."),
        "counts": {a: vals[order[-1]].get(a, {}) for a in areas},
        "first_counts": {a: vals[order[0]].get(a, {}) for a in areas},
        "sources": [json.loads((f / "source.json").read_text()) for f in folders],
    }


# --- NHS Mental Health Services Monthly Statistics (hand-downloaded) --------

MHSDS_AREAS = {"RAT": "NELFT", "QMF": "North East London", "Y56": "London", "England": "England"}
# NELFT's children's mental health caseload halves in April 2026 (33,380 to
# 16,825 children), the same month as the break in its autism figures, while
# North East London barely changes. NHS England gives no reason, so NELFT's
# months from here on are kept off the trend charts.
MHSDS_NELFT_BREAK = AUTISM_BREAK


def cyp_mental_health():
    """Waits for a first contact with children and young people's mental health
    services (MHS130 to MHS135, rolling 3 months)."""
    folders = _nhs_folders("mhsds")
    if not folders:
        return None
    vals = {}  # (year, month) of the period end -> area -> measure -> value
    for folder in folders:
        for f in folder.glob("*.csv"):
            with f.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    area = MHSDS_AREAS.get(r["PRIMARY_LEVEL"])
                    if area:
                        vals.setdefault(_dmy(r["REPORTING_PERIOD_END"]), {}).setdefault(area, {})[r["MEASURE_ID"]] = num(r["MEASURE_VALUE"])
    have = sorted(m for m, v in vals.items() if v.get("England", {}).get("MHS134") is not None)
    # every month from first to last, so a missing month shows as a gap in the line
    order = [(y, mo) for y in range(have[0][0], have[-1][0] + 1) for mo in range(1, 13)
             if have[0] <= (y, mo) <= have[-1]]
    periods = [_month(m) for m in order]
    areas = tuple(MHSDS_AREAS.values())

    def metric(id_, measure, unit, title, explain):
        series = {a: {_month(m): (None if a == "NELFT" and m >= MHSDS_NELFT_BREAK else vals.get(m, {}).get(a, {}).get(measure))
                      for m in order} for a in areas}
        top = max((v for s in series.values() for v in s.values() if v is not None), default=0)
        # round the axis up to a multiple of 400 so the 4 gridlines land on round numbers
        return {"id": id_, "unit": unit, "title": title, "explain": explain, "periods": periods,
                "series": series, "y_max": -(-top // 400) * 400 or None}
    before = [m for m in have if m < MHSDS_NELFT_BREAK]
    after = [m for m in have if m >= MHSDS_NELFT_BREAK]
    nelft = lambda m, k: vals[m].get("NELFT", {}).get(k)
    return {
        "latest": periods[-1], "periods": periods,
        "missing": [_month(m) for m in order if m not in have],
        "nelft_break": {"before": _month(before[-1]), "after": _month(after[0]),
                        "caseload": (nelft(before[-1], "CYP01"), nelft(after[0], "CYP01")),
                        "waiting": (nelft(before[-1], "MHS133"), nelft(after[0], "MHS133")),
                        "median": (nelft(before[-1], "MHS134"), nelft(after[0], "MHS134"))} if before and after else None,
        "latest_values": {a: vals[order[-1]].get(a, {}) for a in areas},
        "median_waiting": metric("cyp_mh_median", "MHS134", "count", "Median wait so far for children still waiting (days)",
                                 "Children and young people under 18 referred to NHS-funded mental health services and still waiting for a first contact: the median number of days they had waited so far."),
        "p90_waiting": metric("cyp_mh_p90", "MHS135", "count", "Longest waits for children still waiting: 90th percentile (days)",
                              "One in ten children still waiting for a first contact had waited at least this many days."),
        "sources": [json.loads((f / "source.json").read_text()) for f in folders],
    }
