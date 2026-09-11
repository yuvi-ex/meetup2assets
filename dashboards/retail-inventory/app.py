"""Retail Inventory

SCAFFOLDED by ~/exasol-recipes/new_recipe.py against RETAIL.ORDERS_ENRICHED
(2,500 rows). Chrome, Share snapshot and Ask panel come from ../board.py.

THIS FILE IS A STARTING POINT, NOT A FINISHED BOARD. The plumbing is real and the
numbers are real, but `build_insights` below only reports what is STRUCTURALLY
true: totals, the widest and narrowest cut, whether a cut is flat, whether the
trend moved. That is honest but generic.

The work worth doing is replacing build_insights with domain judgement — what a
Inventory Manager would actually do about each number. Two rules to keep while you do:

  1. GATE ON SPREAD, NOT ON AN ABSOLUTE RATE. Most cuts in most datasets are
     near-uniform. `if rate > 15: critical` lights up every card on a dataset
     whose baseline is 14; `if spread >= FLAT_PP` does not.
  2. REPORT A FLAT CUT AS RULED OUT, never as a ranking. Ranking a 0.3pp spread
     manufactures a laggard out of rounding, and the first person who checks will
     stop trusting the whole board.

CONTRACTS the dry run enforces (`python3 ~/exasol-recipes/dryrun.py <this dir>`):
  * finding tone is one of good / bad / warn / info — anything else is a KeyError
    inside a callback, which surfaces as a bare HTTP 500 with all probes green
  * figure keys are ONLY trend / composition / rates / concentration — share_html
    silently drops every other key, producing an export with no charts
  * every tile carries delta / label / value / note / good
"""
import importlib.util
import sys
from pathlib import Path

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html

sys.path.insert(0, str(Path(__file__).resolve().parent))
from board import (  # noqa: E402  (path must be set before this import)
    BAD, GOOD, JAKARTA, MUTED, SERIES, WARN,
    _f, ask_catalog, base_fig, configure, data_table, empty_fig, fmt, has_error, insight_card,
    kpi_tile, load_row, load_rows, pipe, render_error_panel, share_html,
    snapshot_route, standard_layout, store_snapshot, wire_ask,
)

_LSPEC = importlib.util.spec_from_file_location(
    "gen_llm_sql", Path(__file__).with_name("llm_sql.py"))
_LLM = importlib.util.module_from_spec(_LSPEC); _LSPEC.loader.exec_module(_LLM)

SCHEMA, TABLE = "RETAIL", "ORDERS_ENRICHED"
TITLE = "Retail Inventory"
FILTER_SPEC = [
    ('f0', 'PRODUCT_NAME', 'Product'),
    ('f1', 'CATEGORY', 'Category'),
    ('f2', 'STORE_NAME', 'Store'),
    ('f3', 'ORDER_STATUS', 'Order Status'),
]
KINDS = {'QUANTITY_SUM': 'number', 'QUANTITY_AVG': 'number', 'REVENUE_SUM': 'money', 'REVENUE_AVG': 'money', 'NET_REVENUE_SUM': 'money', 'NET_REVENUE_AVG': 'money', 'GROSS_MARGIN_SUM': 'money', 'GROSS_MARGIN_AVG': 'money', 'RETURN_PCT': 'number', 'MARGIN_PCT': 'number', 'NET_PCT': 'number', 'LOST_PCT': 'number', 'AVG_ORDER': 'money', 'DISCOUNT_AVG': 'number', 'RATING_AVG': 'number', 'DELIVERY_DAYS_AVG': 'number', 'BELOW_REORDER_PCT': 'number', 'STOCK_HEADROOM_AVG': 'number', 'CUSTOMERS_N': 'number', 'PRODUCTS_N': 'number'}
MEASURES = ['QUANTITY_SUM', 'REVENUE_SUM', 'NET_REVENUE_SUM', 'GROSS_MARGIN_SUM']
# The subset of MEASURES that may be summed. A measure absent from this list
# is a rate, an age or a tenure: its tile shows an AVERAGE, because a total
# would be a meaningless number presented with full confidence.
ADDITIVE = ['QUANTITY_SUM', 'REVENUE_SUM', 'NET_REVENUE_SUM', 'GROSS_MARGIN_SUM']
KEYS = []
FRAMES = ['trend.sql', 'cut_a.sql', 'cut_b.sql', 'detail.sql']
DETAIL_COLS = ['PRODUCT_NAME', 'STORE_NAME', 'LINES_N', 'QUANTITY_SUM', 'REVENUE_SUM', 'NET_REVENUE_SUM']
MAIN = "QUANTITY_SUM"
MAIN_ALT = "QUANTITY_AVG"
MAIN_AVG = "QUANTITY_AVG"
MAIN_LABEL = "Units"
CUT_A, CUT_B = "Product", "Store"
# False when the headline measure is a temperature, rate or score — summing those
# produces a number with no meaning, so the board reports the average instead.
MAIN_IS_SUM = True
# False when the table offers only one dimension, so there is no second cut to
# chart and the "rates" slot ranks the same cut by its other aggregate instead.
HAS_CUT_B = True
# True when the table has no date column, so a third cut fills the slot the trend
# chart would have occupied. An empty chart is not an option: the dry run refuses
# a figure with no traces, and rightly so.
HAS_CUT_C = False
CUT_C = "STORE_REGION"
AGG_WORD = "totalling" if MAIN_IS_SUM else "averaging"

FLAT_PCT = 10.0   # a cut whose spread is under this share of its own mean is flat

NEGATIVES = [
    'No stock ledger. On-hand and reorder level are stamped on each order row, with no receipts, transfers, adjustments or timestamps of their own.',
    'No supplier, lead time or purchase order, so nothing here supports a replenishment plan.',
    'No warehouse or bin location — STORE_NAME is where the order was placed.',
    'No stock-out record, so demand that could not be filled is not represented at all.',
]
REFUSED = [
    'Is revenue growing? Unanswerable. The order dates land in exactly four months (Jan, Apr, Jul, Oct) with 625 lines each, and each month carries a different 4-product set at a fixed quantity of 1, 2, 3 and 4 respectively. The 8x rise is the generator, not demand.',
    'What is current stock? Unanswerable. Without receipts or timestamps there is no stock position at any point in time, only a per-line snapshot.',
    'Which product will stock out next? Unanswerable — no lead time, no supplier and no historical stock trajectory.',
]

configure(schema=SCHEMA, table=TABLE, measures=MEASURES,
          rates=[MAIN_AVG], negatives=NEGATIVES, refused=REFUSED,
          has_time=True, kinds=KINDS, currency="₹")

# Built from the board's own specs, NOT from FILTER_SPEC's labels: the label is
# the dropdown caption ('Order Status'), the model needs the column
# (ORDER_STATUS), and a catalog with no measures in it makes the model answer a
# revenue question with COUNT(*).
ASK_EXTRA = [
    (TABLE, 'ORDER_DATE', 'temporal_event', 'not_applicable'),
    (TABLE, 'ORDER_MONTH', 'temporal_period', 'not_applicable'),
    (TABLE, 'ORDER_ID', 'entity_key', 'count_only'),
    (TABLE, 'CUSTOMER_ID', 'entity_key', 'count_only'),
    (TABLE, 'PRODUCT_ID', 'entity_key', 'count_only'),
    (TABLE, 'SELLER_ID', 'entity_key', 'count_only'),
    (TABLE, 'STORE_ID', 'entity_key', 'count_only'),
    (TABLE, 'PRODUCT_NAME', 'categorical_dim', 'count_only'),
    (TABLE, 'SUBCATEGORY', 'categorical_dim', 'count_only'),
    (TABLE, 'CATEGORY', 'categorical_dim', 'count_only'),
    (TABLE, 'CHANNEL', 'categorical_dim', 'count_only'),
    (TABLE, 'PAYMENT_METHOD', 'categorical_dim', 'count_only'),
    (TABLE, 'STORE_NAME', 'categorical_dim', 'count_only'),
    (TABLE, 'STORE_REGION', 'categorical_dim', 'count_only'),
    (TABLE, 'ORDER_STATUS', 'state_flag', 'count_only'),
    (TABLE, 'CUSTOMER_SEGMENT', 'categorical_dim', 'count_only'),
    (TABLE, 'AGE_BAND', 'categorical_dim', 'count_only'),
    (TABLE, 'LOYALTY_TIER', 'categorical_dim', 'count_only'),
    (TABLE, 'LOYALTY_MEMBER', 'categorical_dim', 'count_only'),
    (TABLE, 'MARKETING_OPT_IN', 'categorical_dim', 'count_only'),
    (TABLE, 'FAV_CATEGORY', 'categorical_dim', 'count_only'),
    (TABLE, 'PREF_CHANNEL', 'categorical_dim', 'count_only'),
    (TABLE, 'CUSTOMER_CITY', 'categorical_dim', 'count_only'),
    (TABLE, 'CUSTOMER_STATE', 'categorical_dim', 'count_only'),
    (TABLE, 'CUSTOMER_REGION', 'categorical_dim', 'count_only'),
    (TABLE, 'QUANTITY', 'quantity', 'additive'),
    (TABLE, 'REVENUE', 'monetary_amount', 'additive'),
    (TABLE, 'NET_REVENUE', 'monetary_amount', 'additive'),
    (TABLE, 'LOST_REVENUE', 'monetary_amount', 'additive'),
    (TABLE, 'COST', 'monetary_amount', 'additive'),
    (TABLE, 'GROSS_MARGIN', 'monetary_amount', 'additive'),
    (TABLE, 'UNIT_PRICE', 'unit_price', 'non_additive'),
    (TABLE, 'DISCOUNT_PCT', 'percentage', 'non_additive'),
    (TABLE, 'RATING', 'score', 'non_additive'),
    (TABLE, 'DELIVERY_DAYS', 'duration_days', 'non_additive'),
    (TABLE, 'INVENTORY_ON_HAND', 'level_snapshot', 'non_additive'),
    (TABLE, 'REORDER_LEVEL', 'level_snapshot', 'non_additive'),
    (TABLE, 'STOCK_HEADROOM', 'level_snapshot', 'non_additive'),
    (TABLE, 'STATED_LTV', 'monetary_amount', 'non_additive'),
    (TABLE, 'SATISFACTION', 'score', 'non_additive'),
    (TABLE, 'SUPPORT_TICKETS', 'quantity', 'non_additive'),
    (TABLE, 'LOYALTY_POINTS', 'quantity', 'non_additive'),
    (TABLE, 'RETURN_FLAG', 'state_flag', 'count_only'),
    (TABLE, 'BELOW_REORDER', 'state_flag', 'count_only'),
]

ASK_CATALOG = ask_catalog(TABLE, FILTER_SPEC, MEASURES, ADDITIVE,
                          keys=KEYS, extra=ASK_EXTRA)
ASK_JOINS = [
    f'none — "{SCHEMA}"."{TABLE}" is a single table. Never join.',
    'GRAIN: one row per order line, and ORDER_ID is unique — 2,500 lines and '
    '2,500 orders, so COUNT(*) is both. There are exactly 250 customers with '
    'exactly 10 lines each, so COUNT(DISTINCT CUSTOMER_ID) is the only count of '
    'PEOPLE and any per-customer figure must divide by that, not by COUNT(*).',
    'THREE revenue columns, do not substitute one for another. REVENUE is BOOKED '
    'on every line whatever its outcome (17,108,805 total). NET_REVENUE is '
    'REALISED and is non-zero only on Delivered and Shipped lines (9,808,944). '
    'LOST_REVENUE is non-zero only on Cancelled and Returned lines (4,880,883). '
    'The 357 Processing lines are in neither, so NET + LOST does NOT equal '
    'REVENUE. Both are CASE columns holding 0 on every non-matching row: SUM '
    'them, never AVG them across all lines.',
    "ORDER_STATUS holds exactly five values — Delivered (1,072 lines), Shipped "
    "(357), Returned (357), Cancelled (357), Processing (357). There is no "
    "'Booked', 'Complete', 'Open', 'Fulfilled' or 'Pending' value. Booked "
    "revenue is SUM(REVENUE) across every status, NOT a status to filter on.",
    'DELIVERY_DAYS is NULL on all 357 Cancelled and all 357 Processing lines by '
    'construction — those orders never shipped. A plain AVG is already correct '
    '(it covers the 1,786 lines that have a value); never COALESCE it to 0 and '
    'never describe the NULLs as missing data.',
    'GROSS_MARGIN is 42-48% of REVENUE line by line and 45.0% for every one of '
    'the seven categories, a 0.04pp spread. No category, store, channel or '
    'product is more profitable than another. A margin-comparison question has '
    'one honest answer: they are identical by construction.',
    'RATING IS NOT FEEDBACK. It restates DISCOUNT_PCT one-to-one — rating 1 = 0% '
    'discount, 2 = 5%, 3 = 10%, 4 = 15%, 5 = 20%, exactly 500 lines each. Never '
    'present it as satisfaction or review score, and never correlate the two.',
    'Every customer attribute — CUSTOMER_SEGMENT, AGE_BAND, STATED_LTV, '
    'SATISFACTION, SUPPORT_TICKETS, LOYALTY_TIER, LOYALTY_POINTS, LOYALTY_MEMBER, '
    'FAV_CATEGORY, PREF_CHANNEL, MARKETING_OPT_IN, CUSTOMER_CITY, CUSTOMER_STATE, '
    'CUSTOMER_REGION — is read LIVE out of MongoDB through a virtual schema. '
    'Query them exactly like any other column.',
    'STATED_LTV is the CRM document own lifetime-value claim and it CONTRADICTS '
    'the orders: it says 68,685 / 34,763 / 11,323 for Premium / Growth / Standard '
    'while actual revenue per customer is 68,501 / 68,446 / 68,300 — a claimed 6x '
    'spread against an actual 0.3%. Never report STATED_LTV as revenue or as '
    'customer value; compute value from REVENUE instead.',
    'TIME: the only months present are 2025-01, 2025-04, 2025-07 and 2025-10, '
    'each with exactly 625 lines, and each carries a DIFFERENT 4-product set at a '
    'fixed quantity of 1, 2, 3 and 4 respectively. Growth, trend, seasonality and '
    'month-over-month questions are therefore unanswerable — the 8x rise is the '
    'generator, not demand. Say so rather than reporting it. ORDER_MONTH is a '
    "VARCHAR 'YYYY-MM'; ORDER_DATE is a DATE spanning 2025-01-01 to 2025-10-27.",
    'TWO DIFFERENT REGIONS. STORE_REGION (North, South, West) is where the STORE '
    'is. CUSTOMER_REGION (East, North, South, West) comes from the customer '
    'document. They are different columns answering different questions — choose '
    'deliberately and say which one you used.',
    'DERIVED columns, already computed in the view: NET_REVENUE, LOST_REVENUE, '
    'ORDER_MONTH, BELOW_REORDER (1 when INVENTORY_ON_HAND <= REORDER_LEVEL) and '
    'STOCK_HEADROOM (INVENTORY_ON_HAND - REORDER_LEVEL). LOYALTY_MEMBER holds the '
    "STRINGS 'member' / 'non-member' and MARKETING_OPT_IN holds 'opted in' / "
    "'opted out' — neither is a boolean or a 0/1 flag.",
    'NEVER SUM these, average them: UNIT_PRICE, DISCOUNT_PCT, RATING, '
    'DELIVERY_DAYS, INVENTORY_ON_HAND, REORDER_LEVEL, STOCK_HEADROOM, STATED_LTV, '
    'SATISFACTION, SUPPORT_TICKETS, LOYALTY_POINTS. RETURN_FLAG and BELOW_REORDER '
    'are 0/1 flags: AVG gives a rate, SUM gives a line count, neither is money.',
    'If a question needs a column that is not listed above, return no SQL and say '
    'what is missing. Never invent a column, and never invent a literal to filter '
    'on — a plausible-looking value that does not exist returns zero rows and '
    'reads as a real answer of none.',
    'INVENTORY_ON_HAND and REORDER_LEVEL are STAMPED ON EACH ORDER LINE, not a '
    'stock ledger. There are no receipts, transfers, adjustments or timestamps of '
    'their own, so there is NO stock position at any point in time. Current '
    'stock, stock-out prediction and replenishment planning are all unanswerable '
    '— there is no supplier, lead time or purchase order either.',
    '443 of the 2,500 lines sit at or below reorder level, spread evenly across '
    'the six stores (69-83 each), so reorder pressure does not differentiate '
    'them. STORE_NAME is where the order was PLACED, not a warehouse or bin.',
]


def _val(value):
    return fmt(value, MAIN)


def _spread(rows, key="LINES_N", name_key="NAME"):
    vals = [(_f(r.get(key)), r.get(name_key)) for r in rows if r.get(key) is not None]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    mean = sum(v for v, _n in vals) / len(vals)
    return {"lo": lo[0], "lo_name": lo[1], "hi": hi[0], "hi_name": hi[1],
            "spread": hi[0] - lo[0], "groups": len(vals), "mean": mean,
            "relative": (hi[0] - lo[0]) / mean * 100 if mean else 0.0}


def _frame(frames, name):
    """Frames arrive in FRAMES order; fetch by filename so reordering a query in
    sql_smoke.json cannot silently swap two charts."""
    return frames[FRAMES.index(name)] if name in FRAMES else []


def build_insights(kpi, *frames):
    out = []
    lines = _f(kpi.get("LINES_N"))
    if not lines:
        return [{"text": "Nothing matches these filters", "tone": "info",
                 "meaning": "No rows in the current scope.",
                 "action": "Widen the selection."}]
    cut_a = _frame(frames, "cut_a.sql")
    cut_b = _frame(frames, "cut_b.sql")
    trend = _frame(frames, "trend.sql")
    pct = lambda k: _f(kpi.get(k))

    units = _f(kpi.get("QUANTITY_SUM"))
    below = pct("BELOW_REORDER_PCT")
    headroom = pct("STOCK_HEADROOM_AVG")
    out.append({
        "tone": "info",
        "text": (f"{int(units):,} units moved across "
                 f"{int(_f(kpi.get('PRODUCTS_N')))} products"),
        "meaning": (f"{int(lines):,} order lines, average {_f(kpi.get(MAIN_AVG)):.2f} "
                    f"units per line. Stock headroom averages {headroom:.0f} units "
                    f"above reorder level."),
        "action": "Units, not revenue, is the headline on this board.",
    })
    out.append({
        "tone": "bad" if below >= 40 else "warn" if below >= 20 else "good",
        "text": f"{below:.1f}% of order lines were filled at or below reorder level",
        "meaning": ("Reorder level is breached on these lines. Because on-hand and "
                    "reorder level are stamped on each ORDER ROW rather than held as a "
                    "stock ledger, this is a rate across lines, not a count of stockouts."),
        "action": "Confirm against the real stock system before raising a purchase order.",
    })
    sp = _spread(cut_a, "BELOW_REORDER_PCT")
    if sp and sp["spread"] > 10:
        out.append({
            "tone": "warn",
            "text": (f"{sp['hi_name']} breaches reorder level on {sp['hi']:.0f}% of lines, "
                     f"{sp['lo_name']} on {sp['lo']:.0f}%"),
            "meaning": (f"Across {sp['groups']} products. The high end is where "
                        f"replenishment cadence, not demand, is the constraint."),
            "action": f"Review the reorder point for {sp['hi_name']} first.",
        })
    spu = _spread(cut_a, MAIN)
    if spu and spu["lo"]:
        out.append({
            "tone": "info",
            "text": (f"{spu['hi_name']} moves {spu['hi'] / spu['lo']:.1f}x the units of "
                     f"{spu['lo_name']}"),
            "meaning": (f"{int(spu['hi']):,} against {int(spu['lo']):,} units across "
                        f"{spu['groups']} products — the demand ranking that "
                        f"replenishment priority should follow."),
            "action": f"Safety stock should be widest on {spu['hi_name']}.",
        })
    out.append({
        "tone": "bad",
        "text": "This board cannot tell you what is in stock right now",
        "meaning": ("INVENTORY_ON_HAND is a per-order snapshot with no timestamp of its "
                    "own and no receipts, transfers or adjustments anywhere in the feed. "
                    "There is no stock position to reconstruct and no coverage in days "
                    "to compute."),
        "action": "Use this for reorder-pressure ranking only, never as a stock report.",
    })

    sp_margin = _spread(cut_a, "MARGIN_PCT")
    if sp_margin is not None and sp_margin["spread"] < 1.0:
        out.append({
            "tone": "good",
            "text": f"Gross margin is {pct('MARGIN_PCT'):.1f}% in every {CUT_A.lower()}",
            "meaning": (f"The spread across {sp_margin['groups']} groups is "
                        f"{sp_margin['spread']:.2f} percentage points. Cost is a fixed "
                        f"fraction of revenue in this data, so mix cannot move "
                        f"profitability."),
            "action": "Do not build a margin-mix case; there is no variation to exploit.",
        })
    sp_ret = _spread(cut_a, "RETURN_PCT")
    if sp_ret is not None and sp_ret["spread"] < 5.0:
        out.append({
            "tone": "good",
            "text": f"Return rate is flat at {pct('RETURN_PCT'):.1f}% across {CUT_A.lower()}",
            "meaning": (f"{sp_ret['lo']:.1f}% to {sp_ret['hi']:.1f}% across "
                        f"{sp_ret['groups']} groups — inside the noise band for these "
                        f"group sizes, so no group is a returns problem."),
            "action": "Returns are ruled out as a differentiator here.",
        })
    # The four periods are not a time series. Each holds exactly 4 of the 16
    # products at a fixed quantity (Jan=1, Apr=2, Jul=3, Oct=4), so the rise in
    # the trend chart is the generator walking basket size, not demand growing.
    if len(trend) >= 2:
        vals = [(_f(r.get(MAIN)), str(r.get("PERIOD"))) for r in trend]
        lo, hi = min(vals), max(vals)
        if lo[0] and hi[0] / lo[0] >= 3:
            out.append({
                "tone": "bad",
                "text": (f"The {len(trend)}-period rise in the trend chart is an "
                         f"artifact — do not read it as growth"),
                "meaning": (f"{hi[1]} shows {hi[0] / lo[0]:.1f}x {lo[1]}, on an identical "
                            f"line count in every period. Each period carries only 4 of "
                            f"the 16 products at a single fixed quantity, so basket size "
                            f"was assigned by period rather than chosen by customers."),
                "action": "Ignore the trend panel; compare products and stores instead.",
            })

    return out


def make_figures(kpi, *frames):
    trend = _frame(frames, "trend.sql")
    tfig = base_fig(f"{MAIN_LABEL} by period", MAIN_LABEL)
    if not trend and HAS_CUT_C:
        # No time column on this table. A third dimension is a real chart; an empty
        # "by period" panel is dead space that makes the board look broken.
        tfig = None
    elif trend:
        tfig.add_bar(x=[str(r.get("PERIOD")) for r in trend],
                     y=[_f(r.get(MAIN)) for r in trend],
                     marker_color=SERIES[0], name=MAIN_LABEL)
        tfig.add_scatter(x=[str(r.get("PERIOD")) for r in trend],
                         y=[_f(r.get("LINES_N")) for r in trend], yaxis="y2",
                         name="Rows", mode="lines",
                         line={"color": SERIES[1], "width": 2})
        tfig.update_layout(yaxis2={"overlaying": "y", "side": "right",
                                   "title": "Rows", "showgrid": False,
                                   "rangemode": "tozero"})
    else:
        tfig = empty_fig("No time column on this table")
        if HAS_CUT_C:
            tfig = None

    def cut_fig(rows, heading, dim_label, key=MAIN):
        figure = base_fig(heading, MAIN_LABEL)
        if not rows:
            return empty_fig(f"No {dim_label} rows in scope")
        top = sorted(rows, key=lambda r: -_f(r.get(key)))[:18]
        figure.add_bar(x=[str(r.get("NAME")) for r in top],
                       y=[_f(r.get(key)) for r in top],
                       marker_color=SERIES[0], name=MAIN_LABEL,
                       customdata=[[_f(r.get("LINES_N"))] for r in top],
                       hovertemplate=("%{x}<br>%{y:,.2f}<br>"
                                      "%{customdata[0]:,.0f} rows<extra></extra>"))
        figure.update_layout(xaxis={"tickangle": -35}, showlegend=False)
        return figure

    cfig = cut_fig(_frame(frames, "cut_a.sql"), f"{MAIN_LABEL} by {CUT_A}", CUT_A)
    if HAS_CUT_B:
        rfig = cut_fig(_frame(frames, "cut_b.sql"), f"{MAIN_LABEL} by {CUT_B}", CUT_B)
    else:
        # Only one dimension on this table. Ranking the same cut by its other
        # aggregate is a genuinely different question — total versus per-row — and
        # beats shipping an empty chart, which the dry run refuses anyway.
        other = "average" if MAIN_IS_SUM else "total"
        rfig = cut_fig(_frame(frames, "cut_a.sql"),
                       f"{MAIN_LABEL} by {CUT_A} — {other} per group", CUT_A,
                       key=MAIN_ALT)

    # Rows against value: spots a group that is busy but low-value, which a pair
    # of separate rankings hides.
    gfig = base_fig(f"Rows against {MAIN_LABEL.lower()}", MAIN_LABEL)
    rows = _frame(frames, "cut_a.sql")
    if rows:
        top = rows[:30]
        gfig.add_scatter(x=[_f(r.get("LINES_N")) for r in top],
                         y=[_f(r.get(MAIN)) for r in top],
                         text=[str(r.get("NAME")) for r in top],
                         mode="markers+text", textposition="top center",
                         textfont={"size": 9, "color": MUTED},
                         marker={"size": 11, "color": SERIES[0], "opacity": 0.75,
                                 "line": {"color": "#fff", "width": 1.3}},
                         hovertemplate=("%{text}<br>%{x:,.0f} rows<br>%{y:,.2f}"
                                        "<extra></extra>"),
                         name=CUT_A)
        gfig.update_layout(xaxis={"title": "Rows"}, showlegend=False)
    else:
        gfig = empty_fig("No rows in scope")

    if tfig is None:
        tfig = cut_fig(_frame(frames, "cut_c.sql"),
                       f"{MAIN_LABEL} by {CUT_C}", CUT_C)

    # Keys are fixed by share_html: trend / composition / rates / concentration.
    return {"trend": tfig, "composition": cfig, "rates": rfig,
            "concentration": gfig}


def build_tiles(kpi):
    tiles = [{"delta": "", "label": "Rows",
              "value": f"{int(_f(kpi.get('LINES_N'))):,}", "note": "in scope",
              "good": True},
             {"delta": "", "label": MAIN_LABEL, "value": _val(kpi.get(MAIN)),
              "note": f"avg {_val(kpi.get(MAIN_AVG))}", "good": True}]
    for key in KEYS:
        tiles.append({"delta": "", "label": key.replace("_N", "").title(),
                      "value": f"{int(_f(kpi.get(key))):,}", "note": "distinct",
                      "good": True})
    # Skip whichever measure is already the headline: since the headline is now
    # chosen by additivity/money rather than column order, MEASURES[0] is not
    # necessarily it, and slicing from 1 duplicated the tile.
    for m in [x for x in MEASURES if x != MAIN][:3]:
        if m in ADDITIVE:
            key, note = m, "total"
        else:
            # Show the average and SAY so, rather than a total nobody can use.
            key, note = m.replace("_SUM", "_AVG"), "average"
        tiles.append({"delta": "",
                      "label": m.replace("_SUM", "").replace("_", " ").title(),
                      "value": fmt(kpi.get(key), key), "note": note, "good": True})
    return tiles[:6]


def create_dash_app(server, url_base_pathname, metadata):
    app = Dash(__name__, server=server, routes_pathname_prefix="/",
               requests_pathname_prefix=url_base_pathname.rstrip("/") + "/",
               external_stylesheets=[JAKARTA], title=metadata.get("title", TITLE),
               suppress_callback_exceptions=True)
    snapshot_path, mount = snapshot_route(server, url_base_pathname)
    app.layout = standard_layout(
        title=TITLE, filter_spec=FILTER_SPEC,
        charts=["fig-a", "fig-b", "fig-c", "fig-d"],
        table_title="Detail",
        table_note="Bounded by LIMIT so Exasol never streams the whole table.",
        ask_placeholder=f"e.g. {MAIN_LABEL.lower()} by {CUT_A}",
        negatives=NEGATIVES + REFUSED)

    @app.callback(*[Output(f"filter-{k}", "options") for k, _d, _l in FILTER_SPEC],
                  Input("boot", "n_intervals"))
    def _filters(_n):
        rows = load_rows(server, metadata, __file__, "queries/business/filters.sql")
        if has_error(rows):
            return [[] for _ in FILTER_SPEC]
        return [[{"label": str(r["VAL"]), "value": str(r["VAL"])}
                 for r in rows if r.get("DIM") == dim] for _k, dim, _l in FILTER_SPEC]

    def _load(values):
        params = {k: pipe(values[i]) for i, (k, _d, _l) in enumerate(FILTER_SPEC)}

        def rows(name):
            out = load_rows(server, metadata, __file__,
                            f"queries/business/{name}", params=params)
            return [] if has_error(out) else out
        kpi = load_row(server, metadata, __file__, "queries/business/kpi.sql",
                       params=params)
        return kpi, [rows(f) for f in FRAMES]

    def _caption(kpi, values):
        scope = " · ".join((", ".join(values[i]) if values[i] else "All " + lbl.lower())
                           for i, (_k, _d, lbl) in enumerate(FILTER_SPEC))
        asof = str(kpi.get("ASOF"))[:10] if kpi.get("ASOF") else "no date column"
        return (f"{int(_f(kpi.get('LINES_N'))):,} rows · {asof} · "
                f"{_val(kpi.get(MAIN))} · {scope}")

    @app.callback(
        Output("caption", "children"), Output("kpis", "children"),
        Output("insights", "children"), Output("fig-a", "figure"),
        Output("fig-b", "figure"), Output("fig-c", "figure"),
        Output("fig-d", "figure"), Output("detail", "children"),
        *[Input(f"filter-{k}", "value") for k, _d, _l in FILTER_SPEC])
    def _refresh(*values):
        kpi, frames = _load(values)
        if kpi and has_error(kpi):
            panel = render_error_panel(kpi["_error"])
            blank = empty_fig("Query failed")
            return "", [panel], [panel], blank, blank, blank, blank, panel
        kpi = kpi or {}
        tiles = [kpi_tile(t["label"], t["value"], i, note=t["note"],
                          good_when_up=t["good"])
                 for i, t in enumerate(build_tiles(kpi))]
        cards = [insight_card(f) for f in build_insights(kpi, *frames)]
        figs = make_figures(kpi, *frames)
        detail = _frame(frames, "detail.sql")
        table = (data_table(detail, DETAIL_COLS) if detail else
                 html.Div("No rows match.", style={"color": MUTED, "fontSize": "13px"}))
        return (_caption(kpi, values), tiles, cards, figs["trend"],
                figs["composition"], figs["rates"], figs["concentration"], table)

    @app.callback(Output("dl", "data"), Output("share-link", "children"),
                  Input("btn-share", "n_clicks"),
                  *[State(f"filter-{k}", "value") for k, _d, _l in FILTER_SPEC],
                  prevent_initial_call=True)
    def _share(_clicks, *values):
        kpi, frames = _load(values)
        if not kpi or has_error(kpi):
            return dict(content="Export failed: the data layer returned an error.",
                        filename="share-error.txt"), ""
        try:
            page = share_html(TITLE, _caption(kpi, values), build_tiles(kpi),
                              build_insights(kpi, *frames),
                              make_figures(kpi, *frames),
                              [("Detail", _frame(frames, "detail.sql")[:40])])
        except Exception as exc:
            return (dict(content=f"Report generation failed: {exc}",
                         filename="share-error.txt"), "")
        store_snapshot(mount, page)
        return (dict(content=page, filename=f"{TABLE.lower()}-report.html"),
                html.A("Open shareable link ↗", href=snapshot_path, target="_blank",
                       style={"color": SERIES[0], "fontWeight": 700,
                              "textDecoration": "none", "fontSize": "11.5px"}))

    wire_ask(app, server, metadata, _LLM, ASK_CATALOG, ASK_JOINS, SCHEMA, TABLE)
    return app
