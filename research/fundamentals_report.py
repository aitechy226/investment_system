# fundamentals_report.py
# ─────────────────────────────────────────────
# Renders the three fundamental scoring views
# into ReportLab story elements for inclusion
# in the Weekly Pulse PDF — or as a standalone
# Fundamentals Deep Dive PDF.
# ─────────────────────────────────────────────

from __future__ import annotations

import os
import xml.sax.saxutils
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from fundamentals import FundamentalScore

YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote"

# ── Page geometry (letter 8.5" wide, margins 0.65" each side) ─
_PAGE_WIDTH = 8.5 * inch
_CONTENT_WIDTH = _PAGE_WIDTH - (0.65 * inch * 2)  # ~7.2 inch

# ── Colours (consistent with report.py) ──────
DARK_BLUE  = colors.HexColor("#0D2137")
MID_BLUE   = colors.HexColor("#1A4A72")
LIGHT_BLUE = colors.HexColor("#EAF2FB")
GREEN      = colors.HexColor("#1A7A4A")
RED        = colors.HexColor("#B22222")
AMBER      = colors.HexColor("#CC7700")
LIGHT_GREY = colors.HexColor("#F5F5F5")
MID_GREY   = colors.HexColor("#AAAAAA")
GOLD       = colors.HexColor("#B8860B")
URGENT_RED = colors.HexColor("#CC0000")
WARN_AMBER = colors.HexColor("#E08000")
INFO_BLUE  = colors.HexColor("#1A5FAF")
WHITE      = colors.white
BLACK      = colors.black

# Score band colours
def _score_colour(score: float):
    if score >= 70:  return GREEN
    if score >= 50:  return AMBER
    return RED

def _freshness_colour(status: str):
    if status == "very_stale": return URGENT_RED
    if status == "stale":      return WARN_AMBER
    if status == "unknown":    return MID_GREY
    return GREEN


def _earnings_colour(urgency: str):
    if urgency == "critical": return URGENT_RED
    if urgency == "warning":  return WARN_AMBER
    if urgency == "watch":    return INFO_BLUE
    return MID_GREY


def _score_label(score: float) -> str:
    if score >= 75:  return "Strong"
    if score >= 60:  return "Good"
    if score >= 45:  return "Fair"
    if score >= 30:  return "Weak"
    return "Poor"


def _build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("FRTitle", parent=base["Title"],
            fontSize=20, textColor=WHITE, fontName="Helvetica-Bold", spaceAfter=4),
        "subtitle": ParagraphStyle("FRSubtitle", parent=base["Normal"],
            fontSize=9, textColor=colors.HexColor("#CCDDEE"), fontName="Helvetica"),
        "section": ParagraphStyle("FRSection", parent=base["Heading1"],
            fontSize=13, textColor=DARK_BLUE, spaceBefore=14, spaceAfter=4,
            fontName="Helvetica-Bold"),
        "sub": ParagraphStyle("FRSub", parent=base["Heading2"],
            fontSize=10, textColor=MID_BLUE, spaceBefore=8, spaceAfter=2,
            fontName="Helvetica-Bold"),
        "body": ParagraphStyle("FRBody", parent=base["Normal"],
            fontSize=9, leading=14, fontName="Helvetica", spaceAfter=4),
        "flag": ParagraphStyle("FRFlag", parent=base["Normal"],
            fontSize=8, leading=12, fontName="Helvetica", spaceAfter=2),
        "small": ParagraphStyle("FRSmall", parent=base["Normal"],
            fontSize=7, textColor=MID_GREY, fontName="Helvetica"),
        "disclaimer": ParagraphStyle("FRDisclaimer", parent=base["Normal"],
            fontSize=6.5, textColor=MID_GREY, fontName="Helvetica-Oblique", spaceBefore=4),
        "table_cell": ParagraphStyle("FRTableCell", parent=base["Normal"],
            fontSize=6, leading=8, fontName="Helvetica", wordWrap="CJK"),
    }


def _hr():
    return HRFlowable(width="100%", thickness=1, color=MID_BLUE, spaceAfter=6, spaceBefore=2)


def _na(val, fmt=".1f", prefix="") -> str:
    if val is None: return "n/a"
    try:    return f"{prefix}{val:{fmt}}"
    except: return str(val)


def _pct(val, fmt="+.1f") -> str:
    if val is None: return "n/a"
    try:    return f"{val:{fmt}}%"
    except: return str(val)


def _wrap_cell(text, style_name: str = "table_cell") -> Paragraph:
    """Wrap text in a Paragraph so it wraps inside table cells; escape XML."""
    if text is None:
        text = ""
    s = str(text).strip()
    escaped = xml.sax.saxutils.escape(s)
    styles = _build_styles()
    return Paragraph(escaped, styles[style_name])


def _ticker_link(symbol: str, style_name: str = "table_cell") -> Paragraph:
    """Return a Paragraph with the ticker as a clickable link to its Yahoo Finance quote page."""
    if not symbol:
        return _wrap_cell("", style_name)
    s = str(symbol).strip()
    url = f"{YAHOO_QUOTE_URL}/{quote(s, safe='.')}"
    escaped = xml.sax.saxutils.escape(s)
    html = f'<a href="{url}" color="#1A5FAF">{escaped}</a>'
    styles = _build_styles()
    return Paragraph(html, styles[style_name])


def _score_cell(score: float) -> Paragraph:
    """A coloured score pill for table cells."""
    styles = _build_styles()
    colour = _score_colour(score)
    label  = _score_label(score)
    style  = ParagraphStyle("ScoreCell", parent=styles["body"],
        fontSize=6, textColor=colour, fontName="Helvetica-Bold", alignment=1)
    return Paragraph(f"{score:.0f}<br/><font size='5'>{label}</font>", style)


# ─────────────────────────────────────────────
# Cover block (reused as section header)
# ─────────────────────────────────────────────

def _cover(styles, report_date: str) -> list:
    t = Table([[
        Paragraph("FUNDAMENTAL SCORING REPORT", styles["title"]),
        Paragraph(f"Generated: {report_date}", styles["subtitle"]),
    ]], colWidths=[4.5 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), DARK_BLUE),
        ("TOPPADDING",    (0,0),(-1,-1), 18),
        ("BOTTOMPADDING", (0,0),(-1,-1), 18),
        ("LEFTPADDING",   (0,0),(-1,-1), 16),
        ("RIGHTPADDING",  (0,0),(-1,-1), 16),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    return [t, Spacer(1, 0.2 * inch)]


# ─────────────────────────────────────────────
# Scoring legend
# ─────────────────────────────────────────────

def _legend_section(styles) -> list:
    elements = [
        Paragraph("HOW TO READ THIS REPORT", styles["section"]),
        _hr(),
        Paragraph(
            "Each stock is scored across four independent modules (0–100). "
            "The composite score is an equally-weighted average. "
            "Scores reflect fundamental quality relative to the S&P 500 universe — "
            "not a recommendation to buy or sell.",
            styles["body"]
        ),
        Spacer(1, 0.08 * inch),
    ]

    legend_data = [
        ["Module", "What it measures", "Key signals"],
        ["Quality Growth",   "Is the business healthy and growing?",
         "ROE, revenue growth, earnings growth, profit margins, debt/equity"],
        ["Value",            "Is the price fair vs fundamentals?",
         "Forward P/E, PEG ratio, FCF yield, Price/Book, EV/EBITDA"],
        ["Momentum + Quality","Is price action confirming fundamentals?",
         "vs 50d MA, vs 200d MA, distance from 52w high/low"],
        ["Income",           "Is the dividend sustainable and growing?",
         "Yield, payout ratio, FCF coverage, 5yr avg yield"],
    ]
    # Wrap long text so it fits in columns
    lt_rows = [[r[0], r[1], _wrap_cell(r[2])] for r in legend_data]
    score_bands = [
        ["Score Band", "Label", "Interpretation"],
        ["75 – 100", "Strong", "Top quartile — significant strength in this factor"],
        ["60 – 74",  "Good",   "Above average — solid but not exceptional"],
        ["45 – 59",  "Fair",   "Average — neither strong nor weak signal"],
        ["30 – 44",  "Weak",   "Below average — some concern in this factor"],
        ["0 – 29",   "Poor",   "Bottom quartile — meaningful weakness"],
    ]
    st_rows = [[r[0], r[1], _wrap_cell(r[2])] for r in score_bands]

    lt = Table(lt_rows, colWidths=[1.4*inch, 1.8*inch, 3.8*inch])
    lt.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,0), MID_BLUE),
        ("TEXTCOLOR",   (0,0),(-1,0), WHITE),
        ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTNAME",    (0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",    (0,0),(-1,-1), 7),
        ("TOPPADDING",  (0,0),(-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING", (0,0),(-1,-1), 5),
        ("GRID",        (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE, LIGHT_BLUE]),
        ("BACKGROUND",  (0,1),(0,-1), LIGHT_BLUE),
        ("FONTNAME",    (0,1),(0,-1), "Helvetica-Bold"),
    ]))

    st = Table(st_rows, colWidths=[0.9*inch, 0.7*inch, 5.4*inch])
    st.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,0), DARK_BLUE),
        ("TEXTCOLOR",   (0,0),(-1,0), WHITE),
        ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTNAME",    (0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",    (0,0),(-1,-1), 7),
        ("TOPPADDING",  (0,0),(-1,-1), 2),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING", (0,0),(-1,-1), 5),
        ("GRID",        (0,0),(-1,-1), 0.25, MID_GREY),
    ]))

    # Colour score band column
    band_colours = [(GREEN, 1), (GREEN, 2), (AMBER, 3), (RED, 4), (RED, 5)]
    for colour, row in band_colours:
        st.setStyle(TableStyle([
            ("TEXTCOLOR", (0,row),(1,row), colour),
            ("FONTNAME",  (0,row),(1,row), "Helvetica-Bold"),
        ]))

    elements += [lt, Spacer(1, 0.12*inch), st, Spacer(1, 0.15*inch)]
    return elements


# ─────────────────────────────────────────────
# Shared: main scored table (used by Views A & B)
# ─────────────────────────────────────────────

def _scored_table(
    scores: List[FundamentalScore],
    rank_by: str = "composite",  # composite | quality | value | momentum | income
) -> Table:
    """Build the main multi-column scored table."""
    header = [
        "#", "Ticker", "Company", "Sector",
        "Price", "Mkt Cap", "Fwd P/E", "Div%", "Rev Gr%",
        "Quality", "Value", "Momentum", "Income", "COMPOSITE", "Data",
    ]
    rows = [header]

    for i, s in enumerate(scores, 1):
        rank_score = getattr(s, f"{rank_by}_score") if rank_by != "composite" else s.composite_score
        rows.append([
            str(i),
            _ticker_link(s.symbol),
            _wrap_cell(s.name),
            _wrap_cell(s.sector),
            _na(s.current_price, ".2f", "$"),
            f"${s.market_cap_b:.0f}B" if s.market_cap_b else "n/a",
            _na(s.forward_pe, ".1f"),
            _pct(s.div_yield_pct, ".2f").replace("+", ""),
            _pct(s.revenue_growth_pct),
            _score_cell(s.quality_score),
            _score_cell(s.value_score),
            _score_cell(s.momentum_score),
            _score_cell(s.income_score),
            _score_cell(s.composite_score),
            Paragraph(
                s.freshness.summary_flag if s.freshness else "❓",
                ParagraphStyle("FreshCell", parent=_build_styles()["body"],
                    fontSize=6, alignment=1,
                    textColor=_freshness_colour(s.freshness.worst_status) if s.freshness else MID_GREY)
            ),
        ])

    col_w_inch = [0.25, 0.55, 1.45, 1.0, 0.6, 0.6, 0.52, 0.42, 0.52, 0.56, 0.48, 0.60, 0.46, 0.62, 0.35]
    total_w = sum(col_w_inch)
    col_w = [w * (_CONTENT_WIDTH / total_w) for w in col_w_inch]

    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 6),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("LEFTPADDING",   (0,0),(-1,-1), 2),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
        ("ALIGN",         (4,0),(-1,-1), "CENTER"),
        # Highlight composite column
        ("BACKGROUND",    (-1,0),(-1,0),  MID_BLUE),
        ("FONTNAME",      (-1,1),(-1,-1), "Helvetica-Bold"),
    ]))
    return t


# ─────────────────────────────────────────────
# View A — Composite Ranked List
# ─────────────────────────────────────────────

def render_view_a(
    styles,
    scores: List[FundamentalScore],
) -> list:
    elements = [
        PageBreak(),
        Paragraph("VIEW A — COMPOSITE RANKED LIST", styles["section"]),
        _hr(),
        Paragraph(
            "All four modules scored equally (25% each). "
            "These are the strongest overall ideas in the S&P 500 universe right now, "
            "ranked by composite fundamental quality. "
            "A high score means the stock passes well on multiple dimensions — "
            "it does not mean buy.",
            styles["body"]
        ),
        Spacer(1, 0.08 * inch),
        _scored_table(scores, rank_by="composite"),
        Spacer(1, 0.12 * inch),
    ]

    # Flags for top 10
    flag_items = [(s.symbol, s.flags) for s in scores[:10] if s.flags]
    if flag_items:
        elements.append(Paragraph("Flags — Top 10", styles["sub"]))
        for symbol, flags in flag_items:
            elements.append(_ticker_link(symbol, "flag"))
            for f in flags:
                elements.append(Paragraph(f"  {f}", styles["flag"]))
            elements.append(Spacer(1, 0.04 * inch))

    return elements


# ─────────────────────────────────────────────
# View B — Per-Strategy Lists
# ─────────────────────────────────────────────

def render_view_b(
    styles,
    strategy_dict: Dict[str, List[FundamentalScore]],
) -> list:
    strategy_meta = {
        "quality":  ("QUALITY GROWTH",   "Profitable, growing businesses with manageable debt. "
                     "Best suited when you want durable compounders for the long term."),
        "value":    ("VALUE",             "Stocks priced below their fundamental worth on multiple metrics. "
                     "Not just cheap — cheap AND solvent."),
        "momentum": ("MOMENTUM + QUALITY","Strong price trends backed by real fundamentals. "
                     "These have both technical and fundamental confirmation."),
        "income":   ("INCOME",            "Sustainable dividend payers with healthy coverage. "
                     "Yield is real, payout is affordable, cash flow backs it up."),
    }

    elements = [
        PageBreak(),
        Paragraph("VIEW B — PER-STRATEGY RANKED LISTS", styles["section"]),
        _hr(),
        Paragraph(
            "Each list is independently ranked by its module score. "
            "A stock can appear in multiple lists. "
            "Use this when you want to add a specific type of exposure.",
            styles["body"]
        ),
        Spacer(1, 0.1 * inch),
    ]

    for key, (label, description) in strategy_meta.items():
        strategy_scores = strategy_dict.get(key, [])
        if not strategy_scores:
            continue
        elements.append(Paragraph(label, styles["sub"]))
        elements.append(Paragraph(description, styles["body"]))
        elements.append(_scored_table(strategy_scores, rank_by=key))
        elements.append(Spacer(1, 0.15 * inch))

    return elements


# ─────────────────────────────────────────────
# View C — Watchlist / Holdings Flags
# ─────────────────────────────────────────────

def render_view_c(
    styles,
    watchlist_scores: List[FundamentalScore],
    skipped_symbols: List[str],
) -> list:
    elements = [
        PageBreak(),
        Paragraph("VIEW C — YOUR HOLDINGS ASSESSMENT", styles["section"]),
        _hr(),
        Paragraph(
            "Your current holdings scored against the same fundamental framework. "
            "Sorted worst-first — the ones at the top need the most attention. "
            "A low score on a holding you own isn't necessarily a sell signal — "
            "it's a prompt to review your original thesis.",
            styles["body"]
        ),
        Spacer(1, 0.08 * inch),
    ]

    if watchlist_scores:
        elements.append(_scored_table(watchlist_scores, rank_by="composite"))
        elements.append(Spacer(1, 0.12 * inch))

        # Earnings calendar for all holdings
        earnings_rows = [s for s in watchlist_scores if s.earnings and s.earnings.urgency != "unknown"]
        if earnings_rows:
            elements.append(Paragraph("Earnings Calendar", styles["sub"]))
            cal_data = [["Ticker", "Company", "Next Earnings", "Days Away", "Urgency"]]
            for s in sorted(
                earnings_rows,
                key=lambda x: x.earnings.days_until if x.earnings.days_until is not None else 9999
            ):
                ei = s.earnings
                days_str = str(ei.days_until) if ei.days_until is not None else "—"
                cal_data.append([
                    _ticker_link(s.symbol),
                    _wrap_cell(s.name),
                    ei.next_earnings_date.strftime("%b %d, %Y") if ei.next_earnings_date else "Unknown",
                    days_str,
                    ei.urgency.capitalize(),
                ])
            ct = Table(cal_data, colWidths=[0.65*inch, 2.2*inch, 1.4*inch, 0.9*inch, 0.9*inch])
            ct.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
                ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
                ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
                ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
                ("FONTSIZE",      (0,0),(-1,-1), 6),
                ("TOPPADDING",    (0,0),(-1,-1), 2),
                ("BOTTOMPADDING", (0,0),(-1,-1), 2),
                ("LEFTPADDING",   (0,0),(-1,-1), 4),
                ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
                ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
            ]))
            # Colour the urgency column
            for row_idx, s in enumerate(sorted(
                earnings_rows,
                key=lambda x: x.earnings.days_until if x.earnings.days_until is not None else 9999
            ), start=1):
                colour = _earnings_colour(s.earnings.urgency)
                ct.setStyle(TableStyle([
                    ("TEXTCOLOR", (4, row_idx), (4, row_idx), colour),
                    ("FONTNAME",  (4, row_idx), (4, row_idx), "Helvetica-Bold"),
                ]))
            elements.append(ct)
            elements.append(Spacer(1, 0.12 * inch))

        # Detailed flag cards for each holding
        elements.append(Paragraph("Holding Detail Cards", styles["sub"]))
        for s in watchlist_scores:
            card = _holding_card(styles, s)
            elements.extend(card)
    else:
        elements.append(Paragraph("No matching holdings found in the scored universe.", styles["body"]))

    if skipped_symbols:
        elements.append(Paragraph("Holdings Not in Scored Universe", styles["sub"]))
        links = []
        for sym in sorted(skipped_symbols):
            url = f"{YAHOO_QUOTE_URL}/{quote(sym.strip(), safe='.')}"
            esc = xml.sax.saxutils.escape(sym)
            links.append(f'<a href="{url}" color="#1A5FAF">{esc}</a>')
        elements.append(Paragraph(
            "These tickers from your portfolio were not scored (failed quality gate or "
            "not in S&P 500 universe). Review manually: " + ", ".join(links),
            styles["body"]
        ))

    return elements


def _holding_card(styles, s: FundamentalScore) -> list:
    """Detailed card for a single holding in View C."""
    elements = []

    # Header bar (wrap long company names; symbol is link to Yahoo Finance)
    header_colour = _score_colour(s.composite_score)
    name_escaped = xml.sax.saxutils.escape(s.name)
    symbol_url = f"{YAHOO_QUOTE_URL}/{quote(s.symbol.strip(), safe='.')}"
    symbol_escaped = xml.sax.saxutils.escape(s.symbol)
    header_data = [[
        Paragraph(f'<b><a href="{symbol_url}" color="white">{symbol_escaped}</a></b> — {name_escaped}', ParagraphStyle("CH",
            parent=styles["body"], fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=WHITE, wordWrap="CJK")),
        Paragraph(
            f"Composite: <b>{s.composite_score:.0f}</b> ({_score_label(s.composite_score)})",
            ParagraphStyle("CS", parent=styles["body"], fontSize=8,
                           fontName="Helvetica-Bold", textColor=WHITE, alignment=2)
        ),
    ]]
    ht = Table(header_data, colWidths=[4.5*inch, 2.5*inch])
    ht.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), header_colour),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
    ]))
    elements.append(ht)

    # Score bar row
    score_data = [[
        Paragraph(f"Quality<br/><b>{s.quality_score:.0f}</b>",
            ParagraphStyle("SB", parent=styles["small"], alignment=1, textColor=_score_colour(s.quality_score))),
        Paragraph(f"Value<br/><b>{s.value_score:.0f}</b>",
            ParagraphStyle("SB", parent=styles["small"], alignment=1, textColor=_score_colour(s.value_score))),
        Paragraph(f"Momentum<br/><b>{s.momentum_score:.0f}</b>",
            ParagraphStyle("SB", parent=styles["small"], alignment=1, textColor=_score_colour(s.momentum_score))),
        Paragraph(f"Income<br/><b>{s.income_score:.0f}</b>",
            ParagraphStyle("SB", parent=styles["small"], alignment=1, textColor=_score_colour(s.income_score))),
    ]]
    sbt = Table(score_data, colWidths=[1.75*inch]*4)
    sbt.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), LIGHT_BLUE),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
    ]))
    elements.append(sbt)

    # Key metrics row (wrap so long values fit)
    metrics_cells = [
        _wrap_cell(f"Price: {_na(s.current_price, '.2f', '$')}"),
        _wrap_cell(f"Mkt Cap: {'${:.0f}B'.format(s.market_cap_b) if s.market_cap_b else 'n/a'}"),
        _wrap_cell(f"Fwd P/E: {_na(s.forward_pe, '.1f')}"),
        _wrap_cell(f"Div Yield: {_pct(s.div_yield_pct, '.2f').replace('+','')}"),
        _wrap_cell(f"Rev Growth: {_pct(s.revenue_growth_pct)}"),
        _wrap_cell(f"D/E: {_na(s.debt_to_equity, '.0f')}%"),
        _wrap_cell(f"vs 52w High: {_pct(s.pct_from_52w_high)}"),
    ]
    mt = Table([metrics_cells], colWidths=[1.0*inch, 0.85*inch, 0.75*inch, 0.85*inch, 0.85*inch, 0.7*inch, 1.0*inch])
    mt.setStyle(TableStyle([
        ("FONTNAME",      (0,0),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 6),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("BACKGROUND",    (0,0),(-1,-1), LIGHT_GREY),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
    ]))
    elements.append(mt)

    # Earnings banner — shown prominently if within watch window
    if s.earnings and s.earnings.urgency in ("critical", "warning", "watch"):
        ei      = s.earnings
        colour  = _earnings_colour(ei.urgency)
        banner_style = ParagraphStyle("EarningsBanner",
            parent=styles["flag"],
            fontSize=8.5,
            textColor=WHITE,
            fontName="Helvetica-Bold",
            leftPadding=8,
        )
        bt = Table(
            [[Paragraph(f"{ei.flag}  EARNINGS ALERT: {ei.label.upper()}", banner_style)]],
            colWidths=[7.0 * inch],
        )
        bt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colour),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ]))
        elements.append(bt)

    # Freshness detail row
    if s.freshness and s.freshness.worst_status != "fresh":
        tf = s.freshness
        fresh_style = ParagraphStyle("FreshRow",
            parent=styles["small"],
            textColor=_freshness_colour(tf.worst_status),
            fontName="Helvetica-Bold",
        )
        fdata = [[
            Paragraph(f"Price: {tf.price.flag} {tf.price.label}", fresh_style),
            Paragraph(f"Financials: {tf.fundamentals.flag} {tf.fundamentals.label}", fresh_style),
        ]]
        ft = Table(fdata, colWidths=[3.5*inch, 3.5*inch])
        ft.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#FFF8E8")),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
            ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ]))
        elements.append(ft)

    # Flags (non-earnings, non-freshness flags)
    non_earnings_flags = [
        f for f in s.flags
        if not any(marker in f for marker in ["🔴", "🟡", "🔵", "Earnings", "stale", "Stale", "current", "Current", "Financials"])
    ]
    if non_earnings_flags:
        for flag in non_earnings_flags:
            elements.append(Paragraph(flag, styles["flag"]))
    elif not s.flags:
        pass  # no flags at all

    # Show earnings info even if clear (>60d) — good to know
    if s.earnings and s.earnings.urgency in ("clear", "unknown"):
        elements.append(Paragraph(
            f"  {s.earnings.flag}  {s.earnings.label}",
            styles["small"]
        ))

    elements.append(Spacer(1, 0.15 * inch))
    return elements


# ─────────────────────────────────────────────
# Standalone PDF generator
# ─────────────────────────────────────────────

def generate_fundamentals_pdf(
    view_a_scores: List[FundamentalScore],
    view_b_dict:   Dict[str, List[FundamentalScore]],
    view_c_scores: List[FundamentalScore],
    skipped_symbols: List[str],
    output_path: Optional[str] = None,
    reports_dir: str = "reports",
) -> str:
    """
    Generate a standalone Fundamentals Deep Dive PDF.
    Returns the output path.
    """
    os.makedirs(reports_dir, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d_%H%M")
    if output_path is None:
        output_path = os.path.join(reports_dir, f"fundamentals_{report_date}.pdf")

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=0.65*inch, rightMargin=0.65*inch,
        topMargin=0.6*inch,   bottomMargin=0.6*inch,
        title=f"Fundamental Scoring Report — {report_date}",
    )

    styles = _build_styles()
    story  = []

    story += _cover(styles, report_date.replace("_", " "))
    story += _legend_section(styles)
    story += render_view_a(styles, view_a_scores)
    story += render_view_b(styles, view_b_dict)
    story += render_view_c(styles, view_c_scores, skipped_symbols)

    story += [
        Spacer(1, 0.3*inch),
        HRFlowable(width="100%", thickness=0.5, color=MID_GREY),
        Paragraph(
            "This report is generated by an automated system for personal research only. "
            "Scores reflect relative fundamental quality within the S&P 500 universe and "
            "do not constitute financial advice. Past performance is not indicative of "
            "future results. Always conduct your own due diligence.",
            styles["disclaimer"]
        ),
    ]

    doc.build(story)
    return output_path
