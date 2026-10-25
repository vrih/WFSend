"""Inline SVG charts. No JavaScript library: charts render without JS, and a
small script in the page adds hover tooltips (see site/static/site.js).

Colours come from CSS custom properties (see site/static/style.css), so light
and dark mode are handled by the stylesheet, not here.
"""
from html import escape

# Series identity is fixed per area so a colour always means the same place.
AREA_CLASS = {"Waltham Forest": "s1", "London": "s2", "England": "s3"}


def _fmt(v, unit):
    if v is None:
        return "no data"
    if unit == "percent":
        # whole numbers from council papers are shown as printed ("12%", not "12.0%")
        return f"{v:.0f}%" if isinstance(v, int) else f"{v:.1f}%"
    if unit == "gbp_m":
        return f"£{v:,.1f}m"
    if unit == "score":
        return f"{v:.1f}"
    return f"{v:,.0f}"


def _nice_max(v, unit):
    if unit == "percent" and v > 60:
        return 100.0
    for step in (1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000):
        if v <= step * 5:
            return step * (int(v / step) + 1)
    return v * 1.1


def line_chart(series, periods, unit="percent", title="", y_max=None, height=260):
    """series: {area: {period: value}}; periods: ordered list of period labels."""
    W, H = 640, height
    left, right, top, bottom = 44, 150, 16, 34
    pw, ph = W - left - right, H - top - bottom
    vals = [v for s in series.values() for v in s.values() if v is not None]
    if not vals:
        return ""
    ymax = y_max or _nice_max(max(vals), unit)
    n = len(periods)

    def x(i):
        return left + (pw * i / (n - 1) if n > 1 else pw / 2)

    def y(v):
        return top + ph - ph * v / ymax

    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    # gridlines and y ticks
    for k in range(5):
        tv = ymax * k / 4
        yy = y(tv)
        out.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(f'<text class="tick" x="{left - 6}" y="{yy + 4:.1f}" text-anchor="end">{escape(_fmt(tv, unit).replace(".0%", "%").replace(".0", ""))}</text>')
    out.append(f'<line class="axis" x1="{left}" x2="{left + pw}" y1="{top + ph}" y2="{top + ph}"/>')
    # x labels: thin out if crowded
    stride = 1 if n <= 8 else 2
    for i, p in enumerate(periods):
        if i % stride == 0 or i == n - 1:
            out.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 12}" text-anchor="middle">{escape(p)}</text>')

    # direct end labels, nudged apart so they never overlap
    ends = []
    for area, s in series.items():
        pts = [(i, s.get(p)) for i, p in enumerate(periods) if s.get(p) is not None]
        if pts:
            ends.append([y(pts[-1][1]), area, pts[-1][1], x(pts[-1][0])])
    ends.sort()
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < 15:
            ends[i][0] = ends[i - 1][0] + 15

    for area, s in series.items():
        cls = AREA_CLASS.get(area, "s4")
        segs, cur = [], []
        for i, p in enumerate(periods):
            v = s.get(p)
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append((x(i), y(v)))
        if cur:
            segs.append(cur)
        for seg in segs:
            d = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}" for j, (px, py) in enumerate(seg))
            out.append(f'<path class="line {cls}" d="{d}"/>')
        for i, p in enumerate(periods):
            v = s.get(p)
            if v is None:
                continue
            tip = f"{area}, {p}: {_fmt(v, unit)}"
            out.append(f'<circle class="dot {cls}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4"/>')
            out.append(f'<circle class="hit" cx="{x(i):.1f}" cy="{y(v):.1f}" r="12" data-tip="{escape(tip)}"><title>{escape(tip)}</title></circle>')
    for ly, area, v, lx in ends:
        out.append(f'<text class="endlabel" x="{lx + 10:.1f}" y="{ly + 4:.1f}"><tspan class="endname">{escape(area)}</tspan> {escape(_fmt(v, unit))}</text>')
    out.append("</svg>")
    return "\n".join(out)


def legend(areas):
    items = "".join(
        f'<span class="key"><span class="swatch {AREA_CLASS.get(a, "s4")}"></span>{escape(a)}</span>' for a in areas
    )
    return f'<div class="legend">{items}</div>'


def ranked_bars(values, highlight="Waltham Forest", unit="percent", higher_is_better=True, refs=None):
    """Horizontal bars for every London borough, sorted best first.

    values: {area: value}. refs: {"London": v, "England": v} drawn as markers.
    """
    items = sorted(((a, v) for a, v in values.items() if v is not None),
                   key=lambda t: t[1], reverse=higher_is_better)
    if not items:
        return ""
    refs = {k: v for k, v in (refs or {}).items() if v is not None}
    vmax = max([v for _, v in items] + list(refs.values()))
    vmax = _nice_max(vmax, unit) if unit != "percent" else (100.0 if vmax > 60 else _nice_max(vmax, unit))
    refpos = [(name, v, 100 * v / vmax) for name, v in refs.items()]
    lines = "".join(f'<span class="refline {AREA_CLASS.get(n, "")}" style="left:{x:.1f}%"></span>' for n, _, x in refpos)
    head = "".join(
        f'<span class="reflabel {AREA_CLASS.get(n, "")}" style="left:{x:.1f}%">{escape(n)} {escape(_fmt(v, unit))}</span>'
        for n, v, x in refpos)
    rows = [f'<li class="rb rhead" aria-hidden="true"><span></span><span></span><span class="bar">{head}{lines}</span></li>']
    for rank, (area, v) in enumerate(items, 1):
        hl = " hl" if area == highlight else ""
        pct = 100 * v / vmax if vmax else 0
        tip = f"{rank}. {area}: {_fmt(v, unit)}"
        label = f'<span class="val">{escape(_fmt(v, unit))}</span>' if hl else ""
        rows.append(
            f'<li class="rb{hl}" data-tip="{escape(tip)}" title="{escape(tip)}">'
            f'<span class="rn">{rank}</span><span class="an">{escape(area)}</span>'
            f'<span class="bar"><span class="fill" style="width:{pct:.1f}%">{label}</span>{lines}</span></li>'
        )
    return f'<div class="ranked"><ol>{"".join(rows)}</ol></div>'


def table(series, periods, unit="percent", caption=""):
    head = "".join(f"<th scope='col'>{escape(p)}</th>" for p in periods)
    body = ""
    for area, s in series.items():
        cells = "".join(f"<td>{escape(_fmt(s.get(p), unit)) if s.get(p) is not None else '–'}</td>" for p in periods)
        body += f"<tr><th scope='row'>{escape(area)}</th>{cells}</tr>"
    cap = f"<caption>{escape(caption)}</caption>" if caption else ""
    return f'<div class="tablewrap"><table>{cap}<thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>'
