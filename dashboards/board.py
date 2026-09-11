"""Shared board chrome for ~/exasol-recipes dashboards — the persona-metrics look.

WHERE THIS CAME FROM. `~/.claude/skills/persona-metrics/assets/build_dashboard.py`
emits a complete app whose *chrome* is what makes these dashboards look the way the
user wants: the warm-neutral card design, KPI tiles with accent bars, insight cards
with an ACTION line, and a self-contained shareable HTML snapshot. Its *data layer*
is derived mechanically from the metric plan and is not reused — on a plan whose
measures are rates it emits `MEASURES = []` and skips most of the SQL its own layout
needs. So the chrome lives here once and each recipe supplies its own
signal-checked queries, figures and findings.

The generated original also shipped an XLSX workbook and a reportlab PDF board
pack. Both are removed: the user does not want them, so the code that imported
`openpyxl` and `reportlab` is gone rather than left dead.

USAGE. Each recipe's app.py does:

    from board import (CARD, H2, INK, ..., configure, kpi_tile, insight_card,
                       data_table, base_fig, empty_fig, fmt, _f, share_html, _run)
    configure(schema="TPCH", table="LINEITEM", measures=[...], rates=[...],
              negatives=[...], refused=[...], kinds={...})

`configure()` must run at import time, before any export is rendered: the export
builders read this module's state, which is how the generated original addressed
them too.

TILE AND FINDING CONTRACTS — each of these cost a 500 to discover:

  * A tile dict needs **label, value, delta, note, good** — all five. `share_html`
    reads `t["delta"]` unconditionally, so omitting it kills the whole report with a
    bare KeyError. Pass an empty string when there is no prior period to compare.
  * A finding dict needs **text, tone, meaning, action**, with tone one of
    good / bad / warn / info.
  * `share_html`'s `figures` argument is a dict keyed **"trend", "composition",
    "rates", "concentration"**, rendered in that order. Any other key is ignored
    silently, so a chart under the wrong name simply will not appear.
"""

import importlib.util
import re
from pathlib import Path

import plotly.graph_objects as go
from dash import dcc, html

_SPEC = importlib.util.spec_from_file_location(
    "gen_exasol_helper", Path(__file__).with_name("dash_server_exasol.py"))
_MOD = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(_MOD)
load_row, load_rows = _MOD.load_row, _MOD.load_rows
has_error, render_error_panel = _MOD.has_error, _MOD.render_error_panel


# --- palette: validated categorical hues on a warm neutral ground -------------
INK, INK_2, MUTED = "#12100e", "#4b463f", "#8a837a"
SURFACE, PAGE = "#ffffff", "#f4f1ec"
LINE, HAIR = "#e6e1d8", "#f0ece4"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#7c5cd6"]
TINT = ["#eaf2fd", "#fdefe9", "#e8f7f1", "#fdf5e3", "#f1ecfd"]
GOOD, GOOD_BG = "#0a7d4b", "#e6f5ee"
BAD, BAD_BG = "#c0392b", "#fdecea"
WARN, WARN_BG = "#a8730a", "#fdf3e0"
FONT = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", sans-serif'
JAKARTA = ("https://fonts.googleapis.com/css2?"
           "family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap")

CARD = {"backgroundColor": SURFACE, "border": "1px solid " + LINE,
        "borderRadius": "14px", "padding": "1.15rem 1.3rem",
        "boxShadow": "0 1px 2px rgba(18,16,14,0.04), 0 8px 24px -16px rgba(18,16,14,0.18)"}
H2 = {"fontSize": "13px", "margin": 0, "color": INK, "fontWeight": 700,
      "letterSpacing": "0.02em", "textTransform": "uppercase"}

# --- per-recipe configuration -------------------------------------------------
# The export builders and formatters read these. Defaults keep the module
# importable on its own; configure() rebinds them.
SCHEMA, TABLE = "", ""
MEASURES, RATES = [], []
NEGATIVES, REFUSED = [], []
HAS_TIME = False
KINDS = {}
_SNAPSHOT = {}
# Currency symbol for every money formatter. Defaults to "$" so existing recipes
# are unchanged; a rupee/euro dataset passes currency="₹" to configure().
CURRENCY = "$"


def configure(*, schema="", table="", measures=(), rates=(), negatives=(),
              refused=(), has_time=False, kinds=None, currency="$"):
    """Bind one recipe's schema facts into module state, once, at import time."""
    global SCHEMA, TABLE, MEASURES, RATES, NEGATIVES, REFUSED, HAS_TIME, KINDS
    global CURRENCY
    SCHEMA, TABLE = schema, table
    CURRENCY = currency
    MEASURES, RATES = list(measures), list(rates)
    NEGATIVES, REFUSED = list(negatives), list(refused)
    HAS_TIME = has_time
    KINDS = dict(kinds or {})


def pipe(values):
    """Delimited-string filter pattern: '|A|B|' so one predicate covers a
    multi-select, with '*' meaning "no constraint" — also the state on first paint.

    Deliberately not a hardcoded list of known values: that stops matching reality
    the moment the column gains a new distinct value, and every automated check
    still reports healthy.
    """
    if not values:
        return "*"
    return "|" + "|".join(str(v) for v in values) + "|"


def snapshot_route(server, url_base_pathname):
    """Register the /__report/snapshot.html route that serves the Share output.

    Returns (public_path, mount_key). Store the rendered page under mount_key in
    SNAPSHOT before pointing anyone at public_path.
    """
    mount = url_base_pathname.rstrip("/")
    endpoint = "snapshot_" + (mount.strip("/").replace("/", "_") or "root")
    if endpoint not in server.view_functions:
        def _serve():
            from flask import Response
            page = _SNAPSHOT.get(mount)
            if not page:
                return Response("No snapshot yet — press Share on the dashboard first.",
                                mimetype="text/plain", status=404)
            return Response(page, mimetype="text/html; charset=utf-8")
        server.add_url_rule("/__report/snapshot.html", endpoint, _serve)
    return mount + "/__report/snapshot.html", mount


def store_snapshot(mount, page):
    _SNAPSHOT[mount] = page


# --- formatters, tiles, cards, tables (from the persona-metrics chrome) -------
def pretty(name):
    """Turn a warehouse column name into something a board will read."""
    text = re.sub(r"^[A-Z]{1,3}_", "", str(name))
    text = re.sub(r"[_\-]+", " ", text).strip()
    if text.isupper() or text.islower():
        text = text.title()
    return text


def _f(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d


def fmt(value, measure=None):
    a = _f(value)
    money = KINDS.get(measure) == "money"
    prefix = CURRENCY if money else ""
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(a) >= cut:
            return f"{prefix}{a/cut:,.1f}{suffix}"
    if money:
        return f"{prefix}{a:,.0f}"
    return f"{a:,.0f}" if a == int(a) else f"{a:,.2f}"


def fmt_rate(value, measure=None):
    """Not every non-additive measure is a fraction.

    Formatting all of them as percentages turns an average of 4.24 days into
    "424.4%". Trust the measure's declared kind instead.
    """
    kind = KINDS.get(measure)
    if kind == "percent":
        return f"{_f(value):.1%}"
    if kind == "money":
        return fmt(value, measure)
    return f"{_f(value):,.2f}"


def delta_pill(pct, good_when_up=True):
    up = pct >= 0
    good = up if good_when_up else not up
    colour, background = (GOOD, GOOD_BG) if good else (BAD, BAD_BG)
    return html.Span(f"{'▲' if up else '▼'} {abs(pct):,.1f}%",
                     style={"color": colour, "backgroundColor": background,
                            "fontSize": "11.5px", "fontWeight": 700,
                            "padding": "0.15rem 0.45rem", "borderRadius": "999px"})


def window_label(asof):
    """The period a KPI covers, on the KPI itself.

    Every headline is a trailing twelve months, but only the page header said so.
    A reader who totals the same measure elsewhere gets a different number and no
    way to see why.
    """
    if not HAS_TIME or not asof:
        return None
    text = str(asof)[:10]
    try:
        year, month, day = (int(part) for part in text.split("-"))
    except ValueError:
        return f"12 months to {text}"
    names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    start_month, start_year = month + 1, year - 1
    if start_month > 12:
        start_month, start_year = start_month - 12, start_year + 1
    return f"{names[start_month - 1]} {start_year} - {names[month - 1]} {year}"


def kpi_tile(label, value, index, delta=None, note=None, good_when_up=True, period=None):
    accent = SERIES[index % len(SERIES)]
    body = [html.Div(label, style={"fontSize": "11.5px", "color": MUTED, "fontWeight": 600,
                                   "letterSpacing": "0.04em", "textTransform": "uppercase"})]
    if period:
        body.append(html.Div(period, style={"fontSize": "10.5px", "color": MUTED,
                                            "marginTop": "0.15rem", "opacity": 0.85}))
    body.append(html.Div(value, style={"fontSize": "31px", "fontWeight": 700, "color": INK,
                                       "margin": "0.35rem 0 0.45rem",
                                       "letterSpacing": "-0.02em"}))
    row = []
    if delta is not None:
        row.append(delta_pill(delta, good_when_up))
    if note:
        row.append(html.Span(note, style={"fontSize": "11.5px", "color": MUTED,
                                          "marginLeft": "0.4rem" if row else 0}))
    if row:
        body.append(html.Div(row, style={"display": "flex", "alignItems": "center",
                                         "flexWrap": "wrap", "gap": "0.15rem"}))
    return html.Div([html.Div(style={"height": "3px", "backgroundColor": accent,
                                     "borderRadius": "999px", "width": "34px",
                                     "marginBottom": "0.75rem"}),
                     html.Div(body)], style=CARD)


def insight_card(finding):
    """One finding, with its meaning and its action attached rather than split
    across parallel columns that never balance."""
    # An unrecognised tone falls back to "info" rather than raising: a typo in one
    # finding used to take the whole page down with a KeyError from inside a
    # callback, which surfaces as a bare 500 while every health probe still passes.
    tone = finding.get("tone", "info")
    colour, background, icon = {"good": (GOOD, GOOD_BG, "▲"), "bad": (BAD, BAD_BG, "▼"),
                                "warn": (WARN, WARN_BG, "!"),
                                "info": (INK_2, PAGE, "•")}.get(tone, (INK_2, PAGE, "•"))
    body = [html.Div(finding["text"], style={"fontSize": "13.5px", "color": INK,
                                             "fontWeight": 600, "lineHeight": 1.45})]
    if finding.get("meaning"):
        body.append(html.Div(finding["meaning"],
                             style={"fontSize": "12.5px", "color": INK_2,
                                    "lineHeight": 1.5, "marginTop": "0.25rem"}))
    if finding.get("action"):
        body.append(html.Div([
            html.Span("ACTION", style={"fontSize": "9.5px", "fontWeight": 800,
                                       "letterSpacing": "0.08em", "color": colour,
                                       "marginRight": "0.45rem"}),
            html.Span(finding["action"], style={"fontSize": "12.5px", "color": INK_2}),
        ], style={"marginTop": "0.45rem", "paddingTop": "0.45rem",
                  "borderTop": "1px dashed " + LINE}))
    return html.Div([
        html.Div(icon, style={"color": colour, "backgroundColor": background,
                              "fontWeight": 800, "fontSize": "12px", "minWidth": "24px",
                              "height": "24px", "borderRadius": "8px", "display": "flex",
                              "alignItems": "center", "justifyContent": "center",
                              "flexShrink": 0}),
        html.Div(body),
    ], style={"display": "flex", "gap": "0.7rem", "alignItems": "flex-start",
              "padding": "0.75rem 0.85rem", "borderRadius": "12px",
              "backgroundColor": SURFACE, "border": "1px solid " + LINE,
              "borderLeft": f"3px solid {colour}"})


def base_fig(title, y_title, height=340):
    figure = go.Figure()
    figure.update_layout(
        title={"text": title, "font": {"size": 13, "color": INK, "family": FONT},
               "x": 0, "xanchor": "left", "y": 0.95},
        height=height, margin={"l": 62, "r": 26, "t": 52, "b": 46},
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font={"family": FONT, "color": INK_2, "size": 12}, hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0,
                "font": {"size": 11}, "bgcolor": "rgba(0,0,0,0)"},
        xaxis={"showgrid": False, "linecolor": LINE, "tickfont": {"color": MUTED},
               "ticks": "outside", "tickcolor": LINE},
        yaxis={"title": {"text": y_title, "font": {"size": 11, "color": MUTED}},
               "gridcolor": HAIR, "zerolinecolor": LINE, "linecolor": "rgba(0,0,0,0)",
               "tickfont": {"color": MUTED}})
    return figure


def empty_fig(message, height=340):
    figure = base_fig("", "", height)
    figure.add_annotation(text=message, showarrow=False, font={"color": MUTED, "size": 12})
    figure.update_xaxes(visible=False); figure.update_yaxes(visible=False)
    return figure


MONEY_WORDS = ("sales", "revenue", "price", "cost", "amount", "profit", "spend",
               "discount given", "margin", "value", "total")


# A rate wins over a money word, and must: the Ask panel lets the model name its
# own columns, and MARGIN_PCT_OF_REVENUE matches two money words while being a
# percentage. Rendering 45.02 as ₹45.02 on a shared board is a real misread.
RATE_WORDS = ("pct", "percent", "rate", "share", "ratio", "%", "per cent")


def looks_monetary(column_name):
    text = str(column_name).lower().replace("_", " ")
    if any(word in text for word in RATE_WORDS):
        return False
    return any(word in text for word in MONEY_WORDS)


def cell_value(column_name, value):
    """Render a raw query value for display: money as a currency amount."""
    if isinstance(value, bool) or value is None:
        return "" if value is None else str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if looks_monetary(column_name):
        for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(number) >= cut:
                return f"{CURRENCY}{number/cut:,.1f}{suffix}"
        return f"{CURRENCY}{number:,.2f}"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def data_table(rows, columns, aligns=None, raw=False):
    aligns = aligns or (["left"] + ["right"] * (len(columns) - 1))
    head = html.Thead(html.Tr([
        html.Th(c, style={"textAlign": a, "padding": "0.55rem 0.75rem",
                          "borderBottom": "2px solid " + LINE, "fontSize": "11px",
                          "color": MUTED, "fontWeight": 700, "letterSpacing": "0.04em",
                          "textTransform": "uppercase", "whiteSpace": "nowrap"})
        for c, a in zip(columns, aligns)]))
    body = html.Tbody([
        html.Tr([html.Td(str(r.get(c, "")) if raw else cell_value(c, r.get(c)), style={
            "textAlign": a, "padding": "0.5rem 0.75rem", "borderBottom": "1px solid " + HAIR,
            "fontSize": "13px", "color": INK, "fontVariantNumeric": "tabular-nums",
            "whiteSpace": "nowrap"}) for c, a in zip(columns, aligns)],
            style={"backgroundColor": SURFACE if i % 2 == 0 else PAGE})
        for i, r in enumerate(rows)])
    return html.Div(html.Table([head, body], style={"borderCollapse": "collapse",
                    "width": "100%", "minWidth": "560px"}), style={"overflowX": "auto"})


# --- the shareable self-contained HTML snapshot -------------------------------
def share_html(title, caption, tiles, findings, figures, tables):
    """A single self-contained HTML file: charts, insights and tables, no server.

    Plotly is inlined rather than pulled from a CDN, so the file still renders in
    five years, on a plane, from an email attachment.
    """
    import plotly.io as pio

    tone_css = {"good": ("#0a7d4b", "#e6f5ee"), "bad": ("#c0392b", "#fdecea"),
                "warn": ("#a8730a", "#fdf3e0"), "info": ("#4b463f", "#f4f1ec")}

    def cards(group):
        if not group:
            return '<p class="muted">Nothing to report.</p>'
        out = []
        for finding in group:
            colour, background = tone_css.get(finding["tone"], tone_css["info"])
            meaning = (f'<div class="mean">{finding["meaning"]}</div>'
                       if finding.get("meaning") else "")
            action = (f'<div class="act"><span style="color:{colour}">ACTION</span> '
                      f'{finding["action"]}</div>' if finding.get("action") else "")
            out.append(f'<div class="ins" style="border-left:3px solid {colour}">'
                       f'<span class="dot" style="color:{colour};background:{background}">'
                       f'&#9632;</span><div><div class="head">{finding["text"]}</div>'
                       f'{meaning}{action}</div></div>')
        return "".join(out)

    tile_html = "".join(
        f'<div class="tile"><div class="accent" style="background:{SERIES[i % len(SERIES)]}">'
        f'</div><div class="lbl">{t["label"]}</div><div class="val">{t["value"]}</div>'
        f'<div class="delta" style="color:{"#0a7d4b" if t["good"] else "#c0392b"}">'
        f'{t["delta"]}</div><div class="note">{t["note"]}</div></div>'
        for i, t in enumerate(tiles))

    chart_html, first = [], True
    for key in ("trend", "composition", "rates", "concentration"):
        figure = figures.get(key)
        if figure is None:
            continue
        chart_html.append(
            '<div class="card">' +
            pio.to_html(figure, include_plotlyjs=(True if first else False),
                        full_html=False, config={"displayModeBar": False},
                        default_height="360px") + "</div>")
        first = False

    table_html = []
    for name, rows in tables:
        if not rows:
            continue
        columns = list(rows[0].keys())[:8]
        head = "".join(f"<th>{pretty(c)}</th>" for c in columns)
        body = "".join("<tr>" + "".join(f"<td>{cell_value(c, r.get(c))}</td>"
                                        for c in columns) + "</tr>" for r in rows)
        table_html.append(f'<div class="card"><h2>{name}</h2>'
                          f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                          f"<tbody>{body}</tbody></table></div></div>")

    notes = "".join(f"<li>{n}</li>" for n in (NEGATIVES + REFUSED)) or \
        "<li>Nothing was refused for this persona.</li>"

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="{JAKARTA}" rel="stylesheet">
<style>
 :root {{ --ink:{INK}; --ink2:{INK_2}; --muted:{MUTED}; --line:{LINE}; --hair:{HAIR};
          --surface:{SURFACE}; --page:{PAGE}; }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:{FONT}; background:var(--page); color:var(--ink);
         margin:0; padding:1.6rem; }}
 .wrap {{ max-width:1600px; margin:0 auto; }}
 header {{ padding:1.4rem 1.6rem; background:linear-gradient(180deg,var(--surface),var(--page));
           border:1px solid var(--line); border-radius:16px 16px 0 0; }}
 h1 {{ font-size:24px; margin:0; letter-spacing:-.02em; }}
 .cap {{ color:var(--muted); font-size:12.5px; margin-top:.3rem; }}
 .grid {{ display:grid; gap:.85rem; margin-top:.85rem; }}
 .kpis {{ grid-template-columns:repeat(auto-fit,minmax(196px,1fr)); }}
 .three {{ grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); }}
 .two {{ grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); }}
 .card,.tile {{ background:var(--surface); border:1px solid var(--line);
                border-radius:14px; padding:1.15rem 1.3rem;
                box-shadow:0 1px 2px rgba(18,16,14,.04),0 8px 24px -16px rgba(18,16,14,.18); }}
 .accent {{ height:3px; width:34px; border-radius:999px; margin-bottom:.75rem; }}
 .lbl {{ font-size:11.5px; color:var(--muted); font-weight:600; letter-spacing:.04em;
         text-transform:uppercase; }}
 .val {{ font-size:31px; font-weight:700; margin:.35rem 0 .45rem; letter-spacing:-.02em; }}
 .delta {{ font-size:11.5px; font-weight:700; }}
 .note {{ font-size:11.5px; color:var(--muted); margin-top:.2rem; }}
 h2 {{ font-size:13px; margin:0 0 .7rem; font-weight:700; letter-spacing:.02em;
       text-transform:uppercase; }}
 .ins {{ display:flex; gap:.7rem; padding:.75rem .85rem; border-radius:12px;
         background:var(--surface); border:1px solid var(--line); line-height:1.45; }}
 .dot {{ font-weight:800; font-size:12px; width:24px; height:24px; border-radius:8px;
         display:flex; align-items:center; justify-content:center; flex:0 0 24px; }}
 .head {{ font-size:13.5px; font-weight:600; color:var(--ink); }}
 .mean {{ font-size:12.5px; color:var(--ink2); margin-top:.25rem; line-height:1.5; }}
 .act {{ font-size:12.5px; color:var(--ink2); margin-top:.45rem; padding-top:.45rem;
         border-top:1px dashed var(--line); }}
 .act span {{ font-size:9.5px; font-weight:800; letter-spacing:.08em; margin-right:.45rem; }}
 table {{ border-collapse:collapse; width:100%; font-size:13px; }}
 th {{ text-align:right; padding:.55rem .75rem; border-bottom:2px solid var(--line);
       font-size:11px; color:var(--muted); font-weight:700; letter-spacing:.04em;
       text-transform:uppercase; white-space:nowrap; }}
 th:first-child,td:first-child {{ text-align:left; }}
 td {{ text-align:right; padding:.5rem .75rem; border-bottom:1px solid var(--hair);
       font-variant-numeric:tabular-nums; white-space:nowrap; }}
 tbody tr:nth-child(even) {{ background:var(--page); }}
 .scroll {{ overflow-x:auto; }}
 .muted {{ color:var(--muted); font-size:12px; }}
 footer {{ color:var(--muted); font-size:12px; margin-top:1.2rem; line-height:1.6; }}
 .noprint {{ position:fixed; top:14px; right:16px; z-index:99; display:flex;
             gap:.5rem; align-items:center; }}
 .btn {{ font-family:inherit; font-size:12.5px; font-weight:600; padding:.55rem .95rem;
         border-radius:10px; border:1px solid var(--ink); background:var(--ink);
         color:#fff; cursor:pointer; box-shadow:0 6px 18px -8px rgba(18,16,14,.5); }}
 .btn:hover {{ opacity:.88; }}
 .hint {{ font-size:11px; color:var(--muted); background:var(--surface);
          border:1px solid var(--line); padding:.35rem .55rem; border-radius:8px; }}
 @page {{ size:A4 landscape; margin:12mm 10mm; }}
 @media print {{
   .noprint {{ display:none !important; }}
   html,body {{ background:#fff; }}
   body {{ padding:0; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
   .wrap {{ max-width:none; }}
   .card,.tile,.ins {{ box-shadow:none; break-inside:avoid; page-break-inside:avoid; }}
   header,h2 {{ break-after:avoid; page-break-after:avoid; }}
   .kpis {{ grid-template-columns:repeat(4,1fr); }}
   .three,.two {{ grid-template-columns:repeat(2,1fr); }}
   .scroll {{ overflow:visible; }}
   table {{ font-size:11px; }}
   thead {{ display:table-header-group; }}
   tr {{ break-inside:avoid; page-break-inside:avoid; }}
 }}
</style></head><body><div class="wrap">
<div class="noprint"><span class="hint">Pick &ldquo;Save as PDF&rdquo; as the destination</span>
<button class="btn" onclick="window.print()">Download PDF</button></div>
<header><h1>{title}</h1><div class="cap">{caption}</div></header>
<div class="grid kpis">{tile_html}</div>
<div class="card" style="margin-top:.85rem"><h2>Insights</h2>
  <p class="muted" style="margin:-.35rem 0 .85rem">What moved, what it means, and what to
  do about it. Every figure is read from a query.</p>
  <div class="grid three" style="margin-top:0">{cards(findings)}</div>
</div>
<div class="grid">{"".join(chart_html)}</div>
<div class="grid">{"".join(table_html)}</div>
<footer><strong>How these numbers are built</strong>
<ul><li>Source: {SCHEMA}.{TABLE}</li>
<li>Measures: {", ".join(pretty(m) for m in MEASURES)}</li>
<li>Rates are averaged, never summed: {", ".join(pretty(r) for r in RATES) or "none"}</li>
</ul><strong>Not derivable from this dataset</strong><ul>{notes}</ul>
<p>Snapshot generated from a live Exasol query. Figures reflect the filters shown above.</p>
</footer></div>
<script>
 // Plotly sizes itself to the screen; without this the charts keep their screen
 // width on the printed page and spill off the sheet.
 window.addEventListener("beforeprint", function () {{
   if (!window.Plotly) return;
   document.querySelectorAll(".js-plotly-plot").forEach(function (node) {{
     window.Plotly.Plots.resize(node);
   }});
 }});
</script>
</body></html>"""


# --- ad-hoc SQL through the bound profile, for the Ask panel ------------------
def _run(server, metadata, sql):
    service = server.extensions.get("exasol_dashboard_service")
    if service is None:
        return None, "The Exasol service is not available in this context."
    profile = metadata["data_sources"]["primary"]["profile"]
    try:
        result = service.execute_profile_query(profile, sql, params={})
    except Exception as exc:
        return None, f"Query failed: {str(exc)[:200]}"
    # The service reports a SQL error IN the payload rather than by raising, so
    # without this check a rejected statement arrives as an empty result and the
    # panel says "ran and returned no rows" about a query that never ran.
    if has_error(result):
        return None, f"Query failed: {str(result.get('_error'))[:200]}"
    rows = result.get("records") or result.get("rows") or []
    if has_error(rows):
        return None, f"Query failed: {str(rows.get('_error'))[:200]}"
    if rows and not isinstance(rows[0], dict):
        cols = [c if isinstance(c, str) else c.get("name") for c in result.get("columns", [])]
        rows = [dict(zip(cols, r)) for r in rows]
    return rows, None



# --- the standard page --------------------------------------------------------
# All five dashboards share this shape: header with filters and Share, a KPI row,
# an insights grid, four chart cards, a detail table, and the negatives panel, with
# the Ask panel down the right. Only the content differs, so the shape lives here
# and each recipe supplies its own queries, tiles, findings and figures.

BUTTON = {"fontSize": "12px", "fontWeight": 600, "padding": "0.45rem 0.85rem",
          "borderRadius": "9px", "border": "1px solid " + LINE, "background": SURFACE,
          "color": INK, "cursor": "pointer"}
PRIMARY = {**BUTTON, "background": INK, "color": "#fff", "border": "1px solid " + INK}


def _filter_control(key, label):
    return html.Div([
        html.Label(label, style={"fontSize": "10.5px", "color": MUTED, "fontWeight": 700,
                                 "letterSpacing": "0.04em", "textTransform": "uppercase"}),
        dcc.Dropdown(id=f"filter-{key}", options=[], value=[], multi=True,
                     placeholder="All", style={"minWidth": "185px", "fontSize": "13px"})])


def standard_layout(*, title, filter_spec, charts, table_title, table_note,
                    ask_placeholder, negatives, extra_header=None):
    """Assemble the page.

    filter_spec  [(param_key, dim_name, label), ...]
    charts       [(component_id, ...), ...] rendered two per row, in order
    extra_header a component dropped under the caption — used by the multi-persona
                 recipe for its persona switcher. Omit for a single-persona board.

    The table heading, table note and "not derivable" list carry slot-* ids so a
    recipe whose page changes at runtime (again: personas) can rewrite them from a
    callback. A recipe that never targets them is unaffected.
    """
    header = html.Div([
        html.Div([
            html.Div(title, style={"fontSize": "24px", "fontWeight": 700, "color": INK,
                                   "letterSpacing": "-0.02em"}),
            html.Div(id="caption", style={"color": MUTED, "fontSize": "12.5px",
                                          "marginTop": "0.3rem"}),
        ] + ([extra_header] if extra_header is not None else [])),
        html.Div([_filter_control(k, lbl) for k, _d, lbl in filter_spec] + [
            html.Div([
                html.Button("Share", id="btn-share", n_clicks=0, style=PRIMARY),
                html.Div(id="share-link", style={"fontSize": "11px", "color": MUTED,
                         "maxWidth": "220px", "wordBreak": "break-all"}),
            ], style={"display": "flex", "gap": "0.4rem", "alignItems": "flex-end",
                      "flexWrap": "wrap"}),
        ], style={"display": "flex", "gap": "0.7rem", "alignItems": "flex-end",
                  "flexWrap": "wrap"}),
    ], style={"display": "flex", "justifyContent": "space-between",
              "alignItems": "flex-end", "flexWrap": "wrap", "gap": "1.2rem",
              "padding": "1.4rem 1.6rem",
              "background": f"linear-gradient(180deg, {SURFACE} 0%, {PAGE} 100%)",
              "borderBottom": "1px solid " + LINE, "borderRadius": "16px 16px 0 0"})

    chart_rows = []
    for i in range(0, len(charts), 2):
        pair = charts[i:i + 2]
        chart_rows.append(html.Div(
            [html.Div(dcc.Graph(id=cid, config={"displayModeBar": False}), style=CARD)
             for cid in pair],
            style={"display": "grid", "gap": "0.85rem", "marginTop": "0.85rem",
                   "gridTemplateColumns": "repeat(auto-fit, minmax(330px, 1fr))"}))

    main = html.Div([
        html.Div(id="kpis", style={"display": "grid", "gap": "0.85rem",
                 "gridTemplateColumns": "repeat(auto-fit, minmax(196px, 1fr))"}),
        html.Div([
            html.H2("Insights", style=H2),
            html.Div("What moved, what it means, and what to do about it. Every figure "
                     "is read from a query — nothing here is generated prose.",
                     style={"fontSize": "12px", "color": MUTED,
                            "margin": "0.35rem 0 0.85rem"}),
            html.Div(id="insights", style={"display": "grid", "gap": "0.55rem",
                     "gridTemplateColumns": "repeat(auto-fit, minmax(330px, 1fr))"}),
        ], style={**CARD, "marginTop": "0.85rem"})] + chart_rows + [
        html.Div([html.H2(table_title, style=H2, id="slot-table-title"),
                  html.Div(table_note, id="slot-table-note",
                           style={"fontSize": "12px", "color": MUTED,
                                  "margin": "0.35rem 0 0.8rem"}),
                  html.Div(id="detail")], style={**CARD, "marginTop": "0.85rem"}),
        html.Div([html.H2("Not derivable from this dataset", style=H2),
                  html.Ul([html.Li(x, style={"marginBottom": "0.35rem"})
                           for x in negatives], id="slot-negatives",
                          style={"margin": "0.7rem 0 0", "paddingLeft": "1.1rem",
                                 "fontSize": "12px", "color": MUTED, "lineHeight": 1.6})],
                 style={**CARD, "marginTop": "0.85rem"}),
    ], style={"flex": "1 1 640px", "minWidth": 0})

    ask = html.Div([
        html.H2("Ask the data", style=H2),
        html.Div("Answers are generated as SQL, checked, then run read-only. "
                 "The query is always shown.",
                 style={"fontSize": "11.5px", "color": MUTED,
                        "margin": "0.5rem 0 0.6rem", "lineHeight": 1.5}),
        dcc.Input(id="q-input", type="text", debounce=True,
                  placeholder=ask_placeholder,
                  style={"width": "100%", "padding": "0.55rem 0.7rem", "fontSize": "13px",
                         "borderRadius": "9px", "border": "1px solid " + LINE,
                         "boxSizing": "border-box"}),
        html.Button("Run", id="q-run", n_clicks=0,
                    style={**PRIMARY, "marginTop": "0.55rem"}),
        dcc.Loading(html.Div(id="q-out", style={"marginTop": "0.9rem"}),
                    type="dot", color=SERIES[0]),
    ], style={**CARD, "flex": "0 0 350px", "alignSelf": "flex-start",
              "position": "sticky", "top": "0.9rem"})

    return html.Div([
        dcc.Interval(id="boot", interval=350, n_intervals=0, max_intervals=1),
        dcc.Download(id="dl"),
        html.Div([header, html.Div([main, ask],
                 style={"display": "flex", "gap": "0.85rem", "alignItems": "flex-start",
                        "flexWrap": "wrap", "padding": "0.85rem"})],
                 style={"backgroundColor": PAGE, "border": "1px solid " + LINE,
                        "borderRadius": "16px", "overflow": "hidden"}),
    ], style={"fontFamily": FONT, "backgroundColor": PAGE, "padding": "1.4rem",
              "minHeight": "100vh", "boxSizing": "border-box"})


def ask_catalog(table, filter_spec, measures, additive, keys=(), extra=()):
    """Build the Ask catalog from a board's own specs.

    Two mistakes this exists to prevent, both of which produce SQL that Exasol
    rejects rather than SQL that is merely wrong:

      1. FILTER_SPEC carries (widget_key, COLUMN, 'Human Label'). The label is
         for the dropdown. Handing it to the model yields `"Order Status"`,
         which does not exist — the column is ORDER_STATUS. Only the column is
         ever emitted here.
      2. A catalog of dimensions alone leaves the model no measure to aggregate,
         so it answers "booked revenue by category" with COUNT(*) and invents a
         literal ('Booked') to stand in for the measure it was never shown.

    MEASURES are query aliases (REVENUE_SUM); the underlying column is REVENUE.
    """
    out, seen = [], set()
    for _key, col, _label in filter_spec:
        if col in seen:
            continue
        seen.add(col)
        out.append((table, col, "categorical_dim", "count_only"))
    for measure in measures:
        col = re.sub(r"_(SUM|AVG|PCT|N)$", "", measure)
        if not col or col in seen:
            continue
        seen.add(col)
        out.append((table, col, "monetary_amount" if KINDS.get(measure) == "money"
                    else "quantity",
                    "additive" if measure in additive else "non_additive"))
    for col in keys:
        if col not in seen:
            seen.add(col)
            out.append((table, col, "entity_key", "count_only"))
    for row in extra:
        if row[1] not in seen:
            seen.add(row[1])
            out.append(row)
    return out


_ASK_VALUES = {}


def _ask_values(server, metadata, schema, table, columns):
    """The distinct values of each low-cardinality dimension, cached per table.

    Without these the model has to guess what lives in a column, and a guess
    that looks plausible ('Booked' for ORDER_STATUS) returns zero rows with no
    error — the least debuggable outcome there is.
    """
    cache_key = (schema, table, tuple(columns))
    if cache_key in _ASK_VALUES:
        return _ASK_VALUES[cache_key]
    if not columns:
        return {}
    parts = [f"SELECT DISTINCT '{c}' AS DIM, TO_CHAR(g.\"{c}\") AS VAL "
             f"FROM \"{schema}\".\"{table}\" g" for c in columns]
    # No `VAL <> ''`: in Exasol the empty string IS NULL and that predicate
    # returns nothing at all.
    sql = ("SELECT DIM, VAL FROM (" + " UNION ALL ".join(parts) +
           ") WHERE VAL IS NOT NULL ORDER BY DIM, VAL LIMIT 500")
    rows, error = _run(server, metadata, sql)
    values = {}
    if not error and rows:
        for row in rows:
            values.setdefault(row["DIM"], []).append(str(row["VAL"]))
    _ASK_VALUES[cache_key] = values
    return values


def wire_ask(app, server, metadata, llm, catalog, joins, schema, table):
    """The Ask panel: model-written SQL, guarded, then run read-only.

    The guard — not the prompt — is the security boundary, and the read-only
    database user is the floor beneath it.
    """
    from dash import Input, Output, State

    @app.callback(Output("q-out", "children"), Input("q-run", "n_clicks"),
                  Input("q-input", "value"), State("q-input", "value"),
                  prevent_initial_call=True)
    def _ask(_clicks, _typed, text):
        if not (text or "").strip():
            return html.Div("Type a question first.",
                            style={"fontSize": "12px", "color": MUTED})
        dims = [n for _t, n, r, _a in catalog
                if r in ("categorical_dim", "state_flag")]
        values = _ask_values(server, metadata, schema, table, dims)
        cols = []
        for t, n, r, a in catalog:
            allowed = values.get(n) or []
            # Only for a genuinely small domain: pasting 400 SKUs into the
            # prompt buries the columns that matter.
            if allowed and len(allowed) <= 25:
                r = f"{r} (values: {' | '.join(allowed)})"
            cols.append({"table": t, "name": n, "role": r, "additivity": a})
        sql, error = llm.propose_sql(text, schema, table, cols, joins=joins)
        blocks = []
        if error:
            blocks.append(html.Div(f"Model unavailable — {error}",
                          style={"fontSize": "11.5px", "color": WARN,
                                 "backgroundColor": WARN_BG, "padding": "0.5rem 0.6rem",
                                 "borderRadius": "8px"}))
        if not sql:
            if not error:
                blocks.append(html.Div(
                    "No model key is configured, so free-text questions are "
                    "unavailable. The rest of the dashboard is unaffected.",
                    style={"fontSize": "11.5px", "color": WARN,
                           "backgroundColor": WARN_BG, "padding": "0.5rem 0.6rem",
                           "borderRadius": "8px"}))
            return blocks
        safe, guard_error = llm.guard(sql, schema, table)
        blocks.append(html.Details([
            html.Summary("SQL", style={"fontSize": "11px", "color": MUTED,
                         "cursor": "pointer", "fontWeight": 700,
                         "letterSpacing": "0.04em", "textTransform": "uppercase"}),
            html.Pre(sql, style={"fontSize": "11px", "background": PAGE,
                     "padding": "0.6rem", "borderRadius": "8px", "overflowX": "auto",
                     "border": "1px solid " + LINE, "whiteSpace": "pre-wrap",
                     "marginTop": "0.4rem", "color": INK_2})], open=False))
        if guard_error:
            blocks.append(html.Div(f"Query {guard_error}.",
                          style={"fontSize": "12px", "color": BAD,
                                 "backgroundColor": BAD_BG, "padding": "0.5rem 0.6rem",
                                 "borderRadius": "8px", "marginTop": "0.5rem"}))
            return blocks
        rows, run_error = _run(server, metadata, safe)
        if run_error:
            blocks.append(html.Div(run_error, style={"fontSize": "12px", "color": BAD,
                          "backgroundColor": BAD_BG, "padding": "0.5rem 0.6rem",
                          "borderRadius": "8px", "marginTop": "0.5rem"}))
        elif not rows:
            blocks.append(html.Div("The query ran and returned no rows.",
                          style={"fontSize": "12px", "color": MUTED,
                                 "marginTop": "0.5rem"}))
        else:
            blocks.append(html.Div(data_table(rows[:25], list(rows[0].keys())),
                                   style={"marginTop": "0.6rem"}))
            blocks.append(html.Div(f"{len(rows)} row(s)",
                          style={"fontSize": "11px", "color": MUTED,
                                 "marginTop": "0.35rem"}))
        return blocks
