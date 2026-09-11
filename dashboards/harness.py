"""Shared dashboard plumbing for every ~/exasol-recipes dashboard.

MASTER COPY: ~/exasol-recipes/harness.py. deploy_dashboard.py pushes this file
into each app's workspace, so fix a formatter or a table bug ONCE here and
redeploy — do not edit the copy inside an app workspace.

Everything domain-specific (the SQL, and the insight builder) lives in the
recipe's own app.py.
"""
import importlib.util
from pathlib import Path

import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

_HELPER_SPEC = importlib.util.spec_from_file_location(
    "dash_server_generated_exasol_helper",
    Path(__file__).with_name("dash_server_exasol.py"),
)
assert _HELPER_SPEC is not None and _HELPER_SPEC.loader is not None
_HELPER_MODULE = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_HELPER_MODULE)
load_row = _HELPER_MODULE.load_row
load_rows = _HELPER_MODULE.load_rows
has_error = _HELPER_MODULE.has_error
render_error_panel = _HELPER_MODULE.render_error_panel

INK = "#0f172a"
MUTED = "#64748b"
LINE = "#e2e8f0"
BLUE = "#1e5eff"
TEAL = "#0d9488"
RED = "#dc2626"
AMBER = "#d97706"
SEV = {"critical": RED, "warning": AMBER, "info": BLUE, "good": TEAL}


def _pipe(values):
    """Delimited-string pattern: '|A|B|' so one SQL predicate covers a multi-select.

    An empty selection becomes the '*' sentinel, which every query reads as
    "no constraint on this dimension" — that is also the state on first paint,
    before the option-loading callback has run.
    """
    if not values:
        return "*"
    return "|" + "|".join(str(v) for v in values) + "|"


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value):
    """Abbreviate only when the magnitude warrants it; keep cents for catalogue-
    scale figures, where rounding $2,798.49 to "$3K" destroys the number."""
    v = _num(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        return f"{sign}${v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.2f}M"
    if v >= 100_000:
        return f"{sign}${v / 1_000:.0f}K"
    if v and v < 10_000 and abs(v - round(v)) > 0.004:
        return f"{sign}${v:,.2f}"
    return f"{sign}${v:,.0f}"


def _pct(value):
    return f"{_num(value):.1f}%"


def _card(label, value, note=None, color=INK):
    body = [
        html.Div(label, style={"fontSize": "11px", "color": MUTED, "textTransform": "uppercase",
                               "letterSpacing": "0.04em"}),
        html.Div(value, style={"fontSize": "26px", "fontWeight": "600", "color": color,
                               "marginTop": "4px"}),
    ]
    if note:
        body.append(html.Div(note, style={"fontSize": "11px", "color": MUTED, "marginTop": "2px"}))
    return html.Div(body, style={"padding": "14px 16px", "border": f"1px solid {LINE}",
                                 "borderRadius": "10px", "background": "#ffffff"})


def _insight(severity, headline, detail):
    color = SEV.get(severity, BLUE)
    return html.Div(
        [
            html.Div(severity.upper(), style={"fontSize": "10px", "fontWeight": "700", "color": color,
                                              "letterSpacing": "0.06em"}),
            html.Div(headline, style={"fontSize": "14px", "fontWeight": "600", "color": INK,
                                      "margin": "3px 0"}),
            html.Div(detail, style={"fontSize": "12.5px", "color": MUTED, "lineHeight": "1.5"}),
        ],
        style={"padding": "12px 14px", "borderLeft": f"3px solid {color}", "background": "#f8fafc",
               "borderRadius": "0 8px 8px 0"},
    )


def _blank(message):
    figure = go.Figure()
    figure.add_annotation(text=message, showarrow=False, font={"color": MUTED})
    figure.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         margin={"t": 30, "b": 30, "l": 30, "r": 30}, height=380)
    return figure


def _style(figure, height=380):
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=height,
        margin={"t": 40, "b": 50, "l": 60, "r": 60}, font={"color": INK, "size": 12},
        legend={"orientation": "h", "y": -0.18, "x": 0}, hovermode="x unified",
    )
    figure.update_xaxes(gridcolor=LINE, zeroline=False)
    figure.update_yaxes(gridcolor=LINE, zeroline=True, zerolinecolor="#cbd5e1")
    return figure


def _table(rows, columns, money_cols=(), pct_cols=()):
    """Alignment is derived from the data: numeric/money/percent columns right,
    text left, for both header and body — so the two never disagree."""
    if not rows:
        return html.Div("No rows match the current filters.",
                        style={"color": MUTED, "padding": "12px", "fontSize": "13px"})

    def right(key):
        if key in money_cols or key in pct_cols:
            return True
        return any(isinstance(r.get(key), (int, float)) for r in rows)

    head = html.Thead(html.Tr([
        html.Th(label, style={"textAlign": "right" if right(key) else "left",
                              "padding": "8px 10px", "borderBottom": f"2px solid {LINE}",
                              "fontSize": "11px", "color": MUTED, "textTransform": "uppercase"})
        for key, label in columns]))
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            raw = row.get(key)
            if key in money_cols:
                text = _money(raw)
            elif key in pct_cols:
                text = _pct(raw)
            elif isinstance(raw, (int, float)):
                text = f"{raw:,.3f}".rstrip("0").rstrip(".") if isinstance(raw, float) else f"{raw:,}"
            else:
                text = str(raw or "")
            color = RED if key == "PROFIT" and _num(raw) < 0 else INK
            cells.append(html.Td(text, style={"textAlign": "right" if right(key) else "left",
                                              "padding": "7px 10px",
                                              "borderBottom": f"1px solid {LINE}",
                                              "fontSize": "12.5px", "color": color}))
        body.append(html.Tr(cells))
    return html.Table([head, html.Tbody(body)],
                      style={"borderCollapse": "collapse", "width": "100%"})


def _dropdown(component_id, label):
    """Options are filled by the boot callback — the Exasol service is not
    registered on the Flask server until request handling has started, so the
    layout itself must not query."""
    return html.Div(
        [
            html.Label(label, style={"fontSize": "11px", "color": MUTED, "display": "block",
                                     "marginBottom": "4px", "textTransform": "uppercase"}),
            dcc.Dropdown(id=component_id, options=[], value=[], multi=True,
                         placeholder="all", style={"fontSize": "13px"}),
        ],
        style={"flex": "1", "minWidth": "220px"},
    )


