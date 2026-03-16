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


# ─────────────────────────────────────────────
# HTML Report Generator
# ─────────────────────────────────────────────

def _html_score_class(score: float) -> str:
    if score >= 70: return "score-strong"
    if score >= 50: return "score-fair"
    return "score-weak"


def _html_score_label(score: float) -> str:
    if score >= 75: return "Strong"
    if score >= 60: return "Good"
    if score >= 45: return "Fair"
    if score >= 30: return "Weak"
    return "Poor"


def _html_pct(val, prefix="") -> str:
    if val is None: return "—"
    try:
        f = float(val)
        sign = "+" if f >= 0 else ""
        return f"{prefix}{sign}{f:.1f}%"
    except Exception:
        return "—"


def _html_val(val, fmt=".1f", suffix="", prefix="") -> str:
    if val is None: return "—"
    try:
        return f"{prefix}{float(val):{fmt}}{suffix}"
    except Exception:
        return "—"


def _html_earnings_badge(s: "FundamentalScore") -> str:
    if not s.earnings or s.earnings.urgency == "unknown":
        return ""
    urgency = s.earnings.urgency
    cls = {"critical": "earn-critical", "warning": "earn-warning",
           "watch": "earn-watch", "clear": "earn-clear"}.get(urgency, "")
    label = xml.sax.saxutils.escape(s.earnings.label)
    flag  = xml.sax.saxutils.escape(s.earnings.flag or "")
    return f'<span class="earn-badge {cls}">{flag} {label}</span>'


def _html_freshness_badge(s: "FundamentalScore") -> str:
    if not s.freshness:
        return ""
    status = s.freshness.worst_status
    if status in ("fresh", None):
        return ""
    cls = "stale-very" if status == "very_stale" else "stale"
    text = xml.sax.saxutils.escape(s.freshness.summary_label or "Data may be stale")
    return f'<span class="stale-badge {cls}">⚠ {text}</span>'


def _html_score_row(s: "FundamentalScore", rank: int = 0) -> str:
    ticker_url = f"https://finance.yahoo.com/quote/{quote(s.symbol, safe='.')}"
    cls_comp   = _html_score_class(s.composite_score)
    cls_q      = _html_score_class(s.quality_score)
    cls_v      = _html_score_class(s.value_score)
    cls_m      = _html_score_class(s.momentum_score)
    cls_i      = _html_score_class(s.income_score)

    rank_cell  = f'<td class="rank">{rank}</td>' if rank else ""
    rev_g = _html_pct(s.revenue_growth_pct) if s.revenue_growth_pct is not None else "—"
    fpe   = _html_val(s.forward_pe, ".1f", "x") if s.forward_pe else "—"
    earn  = _html_earnings_badge(s)
    fresh = _html_freshness_badge(s)

    return f"""<tr>
      {rank_cell}
      <td class="ticker-cell">
        <a href="{ticker_url}" target="_blank" class="ticker-link">{xml.sax.saxutils.escape(s.symbol)}</a>
        {earn}{fresh}
      </td>
      <td class="name-cell">{xml.sax.saxutils.escape(s.name[:32])}</td>
      <td class="sector-cell">{xml.sax.saxutils.escape(s.sector)}</td>
      <td class="score-cell {cls_comp}"><strong>{s.composite_score:.0f}</strong><span class="score-word">{_html_score_label(s.composite_score)}</span></td>
      <td class="score-cell {cls_q}">{s.quality_score:.0f}</td>
      <td class="score-cell {cls_v}">{s.value_score:.0f}</td>
      <td class="score-cell {cls_m}">{s.momentum_score:.0f}</td>
      <td class="score-cell {cls_i}">{s.income_score:.0f}</td>
      <td class="metric-cell">{fpe}</td>
      <td class="metric-cell {'pos' if s.revenue_growth_pct and s.revenue_growth_pct > 0 else 'neg' if s.revenue_growth_pct and s.revenue_growth_pct < 0 else ''}">{rev_g}</td>
    </tr>"""


def _html_scores_table(scores: list, show_rank: bool = False) -> str:
    rank_th = "<th>Rank</th>" if show_rank else ""
    rows = ""
    for i, s in enumerate(scores, 1):
        rows += _html_score_row(s, rank=i if show_rank else 0)
    return f"""
    <div class="table-wrap">
      <table class="scores-table">
        <thead><tr>
          {rank_th}
          <th>Ticker</th><th>Company</th><th>Sector</th>
          <th>Composite</th><th>Quality</th><th>Value</th><th>Momentum</th><th>Income</th>
          <th>Fwd P/E</th><th>Rev Growth</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _html_holding_card(s: "FundamentalScore") -> str:
    ticker_url = f"https://finance.yahoo.com/quote/{quote(s.symbol, safe='.')}"
    earn_badge  = _html_earnings_badge(s)
    fresh_badge = _html_freshness_badge(s)

    # Module bars
    def bar(label, score):
        cls = _html_score_class(score)
        lbl = _html_score_label(score)
        return f"""<div class="module-row">
          <span class="module-name">{label}</span>
          <div class="module-bar"><div class="module-fill {cls}" style="width:{min(score,100):.0f}%"></div></div>
          <span class="module-score {cls}">{score:.0f} <em>{lbl}</em></span>
        </div>"""

    bars = bar("Quality",  s.quality_score)
    bars += bar("Value",    s.value_score)
    bars += bar("Momentum", s.momentum_score)
    bars += bar("Income",   s.income_score)

    # Key metrics
    def metric(label, val):
        return f'<div class="kv"><span class="kv-label">{label}</span><span class="kv-value">{val}</span></div>'

    metrics = ""
    if s.forward_pe:        metrics += metric("Fwd P/E",    _html_val(s.forward_pe, ".1f", "x"))
    if s.revenue_growth_pct is not None: metrics += metric("Rev Growth", _html_pct(s.revenue_growth_pct))
    if s.div_yield_pct:     metrics += metric("Div Yield",  _html_val(s.div_yield_pct, ".2f", "%"))
    if s.debt_to_equity and not s.is_financial_sector:
                            metrics += metric("D/E Ratio",  _html_val(s.debt_to_equity, ".0f", "%"))
    if s.pct_from_52w_high: metrics += metric("52w High",   _html_pct(s.pct_from_52w_high))
    if s.market_cap_b:      metrics += metric("Mkt Cap",    f"${s.market_cap_b:.0f}B")

    # Flags
    flags_html = ""
    if s.flags:
        flags_html = "<ul class='flags'>" + "".join(
            f"<li>{xml.sax.saxutils.escape(f)}</li>" for f in s.flags[:6]
        ) + "</ul>"

    cls_comp = _html_score_class(s.composite_score)

    return f"""
    <div class="holding-card">
      <div class="card-header">
        <div class="card-ticker-block">
          <a href="{ticker_url}" target="_blank" class="card-ticker">{xml.sax.saxutils.escape(s.symbol)}</a>
          <span class="card-name">{xml.sax.saxutils.escape(s.name[:40])}</span>
          <span class="card-sector">{xml.sax.saxutils.escape(s.sector)}</span>
          {earn_badge}{fresh_badge}
        </div>
        <div class="card-composite {cls_comp}">
          <span class="comp-score">{s.composite_score:.0f}</span>
          <span class="comp-label">{_html_score_label(s.composite_score)}</span>
        </div>
      </div>
      <div class="card-body">
        <div class="card-modules">{bars}</div>
        <div class="card-metrics">{metrics}</div>
      </div>
      {flags_html}
    </div>"""


_HTML_CSS = """
:root {
  --bg: #ffffff; --bg-1: #f8f9fa; --bg-2: #f0f2f5;
  --border: #dee2e6; --border-light: #e9ecef;
  --dark-blue: #0D2137; --mid-blue: #1A4A72; --light-blue: #EAF2FB;
  --green: #1A7A4A; --green-bg: #e8f5ee;
  --amber: #CC7700; --amber-bg: #fff8e8;
  --red: #B22222;   --red-bg: #fff0f0;
  --grey: #6c757d;  --light-grey: #f5f5f5;
  --text: #212529;  --text-muted: #6c757d;
  --mono: 'SF Mono', 'Fira Code', 'Courier New', monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       font-size: 14px; color: var(--text); background: var(--bg); line-height: 1.5; }
.page-wrap { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 3rem; }

/* Header */
.report-header { background: var(--dark-blue); color: white; padding: 2rem 1.5rem; margin-bottom: 2rem; }
.report-header h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.3rem; }
.report-header .meta { font-size: 0.8rem; color: #AABBCC; }

/* Nav */
.section-nav { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 2rem;
               padding: 1rem; background: var(--bg-1); border: 1px solid var(--border);
               border-radius: 6px; }
.nav-link { padding: 0.4rem 0.9rem; border-radius: 4px; text-decoration: none;
            font-size: 0.8rem; color: var(--mid-blue); border: 1px solid var(--border);
            transition: all 0.1s; }
.nav-link:hover { background: var(--light-blue); border-color: var(--mid-blue); }

/* Section headings */
.section { margin-bottom: 3rem; }
.section-title { font-size: 1.1rem; font-weight: 700; color: var(--dark-blue);
                 border-bottom: 3px solid var(--mid-blue); padding-bottom: 0.5rem;
                 margin-bottom: 1rem; display: flex; align-items: baseline; gap: 0.75rem; }
.section-title .count { font-size: 0.75rem; font-weight: 400; color: var(--text-muted); }
.subsection-title { font-size: 0.95rem; font-weight: 600; color: var(--mid-blue);
                    margin: 1.5rem 0 0.5rem; border-left: 3px solid var(--mid-blue);
                    padding-left: 0.6rem; }

/* Legend */
.legend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
               gap: 0.5rem; margin-bottom: 1rem; }
.legend-item { padding: 0.5rem 0.75rem; border-radius: 4px; font-size: 0.78rem; }
.legend-strong { background: var(--green-bg); color: var(--green); border: 1px solid #b7ddc8; }
.legend-good   { background: #eaf2fb;          color: var(--mid-blue); border: 1px solid #b8d4ec; }
.legend-fair   { background: var(--amber-bg);  color: var(--amber); border: 1px solid #f0d090; }
.legend-weak   { background: #fef9e7;          color: #996600; border: 1px solid #eed890; }
.legend-poor   { background: var(--red-bg);    color: var(--red); border: 1px solid #e8b4b4; }
.legend-label  { font-weight: 600; margin-bottom: 0.15rem; }
.legend-range  { font-family: var(--mono); font-size: 0.72rem; }

/* Scores table */
.table-wrap { overflow-x: auto; }
.scores-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.scores-table th { background: var(--dark-blue); color: white; padding: 0.5rem 0.6rem;
                   text-align: left; font-weight: 600; white-space: nowrap; }
.scores-table td { padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border-light); vertical-align: middle; }
.scores-table tr:nth-child(even) td { background: var(--bg-1); }
.scores-table tr:hover td { background: var(--light-blue); }
.rank { font-family: var(--mono); color: var(--text-muted); font-size: 0.75rem; width: 32px; }
.ticker-link { font-family: var(--mono); font-weight: 600; color: var(--mid-blue);
               text-decoration: none; font-size: 0.88rem; }
.ticker-link:hover { text-decoration: underline; }
.name-cell { color: var(--text); max-width: 200px; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
.sector-cell { color: var(--text-muted); font-size: 0.75rem; white-space: nowrap; }
.metric-cell { font-family: var(--mono); font-size: 0.8rem; text-align: right; }
.metric-cell.pos { color: var(--green); }
.metric-cell.neg { color: var(--red); }
.score-cell { font-family: var(--mono); text-align: center; font-size: 0.85rem; white-space: nowrap; }
.score-cell .score-word { display: block; font-size: 0.6rem; font-family: sans-serif;
                           text-transform: uppercase; letter-spacing: 0.05em; margin-top: 1px; }
.score-strong { color: var(--green); }
.score-fair   { color: var(--amber); }
.score-weak   { color: var(--red); }

/* Badges */
.earn-badge, .stale-badge { font-size: 0.65rem; padding: 0.1rem 0.4rem; border-radius: 3px;
                             margin-left: 0.3rem; white-space: nowrap; }
.earn-critical { background: var(--red-bg);    color: var(--red);   border: 1px solid #e8b4b4; }
.earn-warning  { background: var(--amber-bg);  color: var(--amber); border: 1px solid #f0d090; }
.earn-watch    { background: #eaf2fb;          color: var(--mid-blue); border: 1px solid #b8d4ec; }
.earn-clear    { background: var(--green-bg);  color: var(--green); border: 1px solid #b7ddc8; }
.stale, .stale-very { background: var(--amber-bg); color: var(--amber); border: 1px solid #f0d090; }
.stale-very { background: var(--red-bg); color: var(--red); }

/* Holding cards */
.cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(480px, 1fr)); gap: 1rem; }
.holding-card { border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
                background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.card-header { display: flex; justify-content: space-between; align-items: flex-start;
               padding: 0.85rem 1rem; background: var(--bg-1); border-bottom: 1px solid var(--border); }
.card-ticker { font-family: var(--mono); font-size: 1.1rem; font-weight: 700;
               color: var(--mid-blue); text-decoration: none; display: block; }
.card-ticker:hover { text-decoration: underline; }
.card-name   { font-size: 0.8rem; color: var(--text); display: block; margin: 0.1rem 0; }
.card-sector { font-size: 0.72rem; color: var(--text-muted); display: block; }
.card-composite { text-align: center; min-width: 64px; }
.comp-score { font-family: var(--mono); font-size: 1.8rem; font-weight: 700;
              line-height: 1; display: block; }
.comp-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em;
              display: block; margin-top: 2px; }
.card-body  { display: flex; gap: 1rem; padding: 0.85rem 1rem; }
.card-modules { flex: 1.5; display: flex; flex-direction: column; gap: 0.4rem; }
.card-metrics { flex: 1; display: flex; flex-direction: column; gap: 0.3rem; }
.module-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.75rem; }
.module-name { width: 68px; color: var(--text-muted); flex-shrink: 0; }
.module-bar  { flex: 1; height: 5px; background: var(--bg-2); border-radius: 3px; overflow: hidden; }
.module-fill { height: 100%; border-radius: 3px; transition: width 0.4s; }
.module-fill.score-strong { background: var(--green); }
.module-fill.score-fair   { background: var(--amber); }
.module-fill.score-weak   { background: var(--red);   }
.module-score { width: 80px; font-family: var(--mono); font-size: 0.75rem; text-align: right;
                flex-shrink: 0; }
.module-score em { font-style: normal; font-size: 0.62rem; color: var(--text-muted); margin-left: 2px; }
.kv { display: flex; justify-content: space-between; font-size: 0.75rem;
      border-bottom: 1px solid var(--border-light); padding: 0.15rem 0; }
.kv-label { color: var(--text-muted); }
.kv-value  { font-family: var(--mono); font-weight: 500; }
.flags { padding: 0.6rem 1rem; background: var(--bg-1); border-top: 1px solid var(--border);
         list-style: none; display: flex; flex-direction: column; gap: 0.2rem; }
.flags li { font-size: 0.75rem; color: var(--text); }

/* Skipped */
.skipped-list { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
.skipped-tag  { font-family: var(--mono); font-size: 0.75rem; padding: 0.2rem 0.5rem;
                background: var(--bg-2); border: 1px solid var(--border); border-radius: 3px;
                color: var(--text-muted); }

/* Disclaimer */
.disclaimer { margin-top: 3rem; padding: 1rem; background: var(--bg-1);
              border: 1px solid var(--border); border-radius: 6px;
              font-size: 0.72rem; color: var(--text-muted); line-height: 1.6; }

@media print {
  .section-nav { display: none; }
  .holding-card { break-inside: avoid; }
  .section { break-before: page; }
}
@media (max-width: 768px) {
  .cards-grid { grid-template-columns: 1fr; }
  .card-body  { flex-direction: column; }
}
"""


def generate_fundamentals_html(
    view_a_scores: List["FundamentalScore"],
    view_b_dict:   Dict[str, List["FundamentalScore"]],
    view_c_scores: List["FundamentalScore"],
    skipped_symbols: List[str],
    output_path: Optional[str] = None,
    reports_dir: str = "reports",
) -> str:
    """
    Generate a standalone Fundamentals Deep Dive HTML report.
    Returns the output path.
    """
    os.makedirs(reports_dir, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d_%H%M")
    if output_path is None:
        output_path = os.path.join(reports_dir, f"fundamentals_{report_date}.html")

    now_str = datetime.now().strftime("%A, %B %d %Y  %H:%M")

    # ── Navigation links ──────────────────────
    nav_links = '''
    <a href="#view-a" class="nav-link">View A — Top Composite</a>
    <a href="#view-b-quality"  class="nav-link">View B — Quality</a>
    <a href="#view-b-value"    class="nav-link">View B — Value</a>
    <a href="#view-b-momentum" class="nav-link">View B — Momentum</a>
    <a href="#view-b-income"   class="nav-link">View B — Income</a>
    '''
    if view_c_scores or skipped_symbols:
        nav_links += '<a href="#view-c" class="nav-link">View C — Watchlist</a>'

    # ── Legend ────────────────────────────────
    legend_html = """
    <div class="legend-grid">
      <div class="legend-item legend-strong"><div class="legend-label">Strong</div><div class="legend-range">75 – 100</div></div>
      <div class="legend-item legend-good">  <div class="legend-label">Good</div>  <div class="legend-range">60 – 74</div></div>
      <div class="legend-item legend-fair">  <div class="legend-label">Fair</div>  <div class="legend-range">45 – 59</div></div>
      <div class="legend-item legend-weak">  <div class="legend-label">Weak</div>  <div class="legend-range">30 – 44</div></div>
      <div class="legend-item legend-poor">  <div class="legend-label">Poor</div>  <div class="legend-range">0 – 29</div></div>
    </div>
    <p style="font-size:0.78rem;color:var(--text-muted);margin-top:0.5rem;">
      Scores are relative within the S&amp;P 500 universe using sector-calibrated thresholds.
      Composite = Quality 30% · Value 25% · Momentum 25% · Income 20%.
      Ticker symbols link to Yahoo Finance.
    </p>"""

    # ── View A ────────────────────────────────
    view_a_html = _html_scores_table(view_a_scores, show_rank=True)

    # ── View B ────────────────────────────────
    strategy_labels = {
        "quality":  ("Quality Growth Leaders",  "Highest Quality Growth scores — profitable, growing businesses with strong balance sheets"),
        "value":    ("Value Opportunities",      "Highest Value scores — trading at attractive multiples relative to fundamentals"),
        "momentum": ("Momentum Leaders",         "Highest Momentum scores — positive price trends confirmed by fundamentals"),
        "income":   ("Income Leaders",           "Highest Income scores — sustainable dividends with strong FCF coverage"),
    }
    view_b_html = ""
    for strategy, scores in view_b_dict.items():
        label, desc = strategy_labels.get(strategy, (strategy.title(), ""))
        anchor = f"view-b-{strategy}"
        view_b_html += f'''
        <div id="{anchor}">
          <h3 class="subsection-title">{xml.sax.saxutils.escape(label)}</h3>
          <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.75rem;">{xml.sax.saxutils.escape(desc)}</p>
          {_html_scores_table(scores, show_rank=True)}
        </div>'''

    # ── View C ────────────────────────────────
    view_c_html = ""
    if view_c_scores:
        cards = "".join(_html_holding_card(s) for s in view_c_scores)
        view_c_html += f'<div class="cards-grid">{cards}</div>'
    if skipped_symbols:
        tags = "".join(f'<span class="skipped-tag">{xml.sax.saxutils.escape(t)}</span>' for t in sorted(skipped_symbols))
        view_c_html += f'<p style="margin-top:1rem;font-size:0.78rem;color:var(--text-muted);">Skipped (quality gate or data unavailable):</p><div class="skipped-list">{tags}</div>'
    if not view_c_html:
        view_c_html = '<p style="color:var(--text-muted);font-size:0.85rem;">No watchlist tickers provided. Use --watchlist TICKER1,TICKER2 to populate this view.</p>'

    view_c_section = f'''
    <section class="section" id="view-c">
      <h2 class="section-title">
        View C — Watchlist Assessment
        <span class="count">{len(view_c_scores)} tickers</span>
      </h2>
      {view_c_html}
    </section>'''

    # ── Assemble HTML ─────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fundamental Scoring Report — {report_date}</title>
<style>{_HTML_CSS}</style>
</head>
<body>

<div class="report-header">
  <h1>Fundamental Scoring Report</h1>
  <div class="meta">S&amp;P 500 Universe · Generated {now_str} · {len(view_a_scores)} ideas in View A</div>
</div>

<div class="page-wrap">

  <nav class="section-nav">{nav_links}</nav>

  <section class="section" id="legend">
    <h2 class="section-title">Score Legend</h2>
    {legend_html}
  </section>

  <section class="section" id="view-a">
    <h2 class="section-title">
      View A — Top Composite Scores
      <span class="count">{len(view_a_scores)} ideas</span>
    </h2>
    {view_a_html}
  </section>

  <section class="section" id="view-b">
    <h2 class="section-title">View B — By Strategy</h2>
    {view_b_html}
  </section>

  {view_c_section}

  <div class="disclaimer">
    This report is generated by an automated system for personal research only.
    Scores reflect relative fundamental quality within the S&amp;P 500 universe and
    do not constitute financial advice. Past performance is not indicative of
    future results. Always conduct your own due diligence.
  </div>

</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


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
