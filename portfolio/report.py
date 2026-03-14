# portfolio/report.py
# ─────────────────────────────────────────────
# Generates the Weekly Pulse PDF report.
# ─────────────────────────────────────────────

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import REPORTS_DIR

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

from portfolio import Portfolio, Position
from macro import MacroSnapshot

DARK_BLUE  = colors.HexColor("#0D2137")
MID_BLUE   = colors.HexColor("#1A4A72")
LIGHT_BLUE = colors.HexColor("#EAF2FB")
GREEN      = colors.HexColor("#1A7A4A")
RED        = colors.HexColor("#B22222")
AMBER      = colors.HexColor("#CC7700")
LIGHT_GREY = colors.HexColor("#F5F5F5")
MID_GREY   = colors.HexColor("#AAAAAA")
WHITE      = colors.white
BLACK      = colors.black
URGENT_RED  = colors.HexColor("#CC0000")
WARN_AMBER  = colors.HexColor("#E08000")
INFO_BLUE   = colors.HexColor("#1A5FAF")
VERIFY_GREEN = colors.HexColor("#1A7A4A")
VERIFY_BLUE  = colors.HexColor("#1A5FAF")


def _build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"],
            fontSize=22, textColor=WHITE, spaceAfter=4, fontName="Helvetica-Bold"),
        "subtitle": ParagraphStyle("Subtitle", parent=base["Normal"],
            fontSize=10, textColor=colors.HexColor("#CCDDEE"), fontName="Helvetica"),
        "section_heading": ParagraphStyle("SectionHeading", parent=base["Heading1"],
            fontSize=13, textColor=DARK_BLUE, spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold"),
        "sub_heading": ParagraphStyle("SubHeading", parent=base["Heading2"],
            fontSize=10, textColor=MID_BLUE, spaceBefore=8, spaceAfter=2, fontName="Helvetica-Bold"),
        "body": ParagraphStyle("BodyText", parent=base["Normal"],
            fontSize=9, textColor=BLACK, spaceAfter=6, leading=14, fontName="Helvetica"),
        "small_label": ParagraphStyle("SmallLabel", parent=base["Normal"],
            fontSize=7, textColor=MID_GREY, fontName="Helvetica"),
        "disclaimer": ParagraphStyle("Disclaimer", parent=base["Normal"],
            fontSize=6.5, textColor=MID_GREY, fontName="Helvetica-Oblique", spaceBefore=4),
        "table_cell": ParagraphStyle("TableCell", parent=base["Normal"],
            fontSize=7.5, leading=9, fontName="Helvetica", wordWrap="normal"),
    }


def _section_rule():
    return HRFlowable(width="100%", thickness=1, color=MID_BLUE, spaceAfter=6, spaceBefore=2)


def _wrap_cell(text, styles):
    """Wrap text in a Paragraph so it word-wraps within table column. Escapes XML entities."""
    if text is None:
        text = ""
    s = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(s, styles["table_cell"])


def _na(val, fmt=".2f", prefix="$"):
    if val is None: return "n/a"
    try:    return f"{prefix}{val:{fmt}}" if prefix else f"{val:{fmt}}"
    except: return str(val)


def _pct(val, fmt="+.1f"):
    if val is None: return "n/a"
    try:    return f"{val:{fmt}}%"
    except: return str(val)


def _freshness_colour(status: str):
    if status == "very_stale": return RED
    if status == "stale":      return AMBER
    if status == "unknown":    return MID_GREY
    return GREEN


def _earnings_colour(urgency: str):
    if urgency == "critical": return URGENT_RED
    if urgency == "warning":  return WARN_AMBER
    if urgency == "watch":    return INFO_BLUE
    return MID_GREY


def _cover_section(styles, report_date):
    t = Table([[
        Paragraph("WEEKLY PULSE REPORT", styles["title"]),
        Paragraph(f"Generated: {report_date}", styles["subtitle"]),
    ]], colWidths=[4.5*inch, 2.5*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), DARK_BLUE),
        ("TOPPADDING",    (0,0),(-1,-1), 18),
        ("BOTTOMPADDING", (0,0),(-1,-1), 18),
        ("LEFTPADDING",   (0,0),(-1,-1), 16),
        ("RIGHTPADDING",  (0,0),(-1,-1), 16),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    return [t, Spacer(1, 0.2*inch)]


def _summary_section(styles, portfolio):
    data = [
        ["Market Value", f"${portfolio.total_value:,.0f}"],
        ["Cost Basis",   f"${portfolio.total_cost:,.0f}"],
        ["Total Return", _pct(portfolio.total_gain_pct)],
        ["Positions",    str(len(portfolio.positions))],
        ["As of",        portfolio.as_of],
    ]
    t = Table(data, colWidths=[1.8*inch, 2.0*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,-1), LIGHT_BLUE),
        ("FONTNAME",      (0,0),(0,-1), "Helvetica-Bold"),
        ("FONTNAME",      (1,0),(1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 9),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("GRID",          (0,0),(-1,-1), 0.3, MID_GREY),
    ]))
    return [Paragraph("PORTFOLIO SNAPSHOT", styles["section_heading"]), _section_rule(), t, Spacer(1, 0.15*inch)]


def _holdings_table_section(styles, positions):
    header = ["Ticker","Company","Shares","Avg Cost","Price","Value","G/L%","Wk%","Earnings","Data","Sector"]
    rows   = [header]
    for p in positions:
        # Earnings cell
        if p.earnings and p.earnings.urgency in ("critical", "warning", "watch"):
            ei = p.earnings
            days_str = f"{ei.flag} {ei.days_until}d" if ei.days_until is not None else ei.flag
        elif p.asset_class.lower() == "etf":
            days_str = "—"
        else:
            days_str = "✔"
        # Freshness cell
        if p.freshness:
            fresh_str = p.freshness.summary_flag
        else:
            fresh_str = "❓"
        rows.append([
            p.ticker,
            _wrap_cell(p.company_name or p.ticker, styles),
            f"{p.shares:.0f}",
            _na(p.avg_cost, ".2f"), _na(p.current_price, ".2f"),
            _na(p.market_value, ",.0f"), _pct(p.gain_loss_pct), _pct(p.week_change_pct),
            days_str, fresh_str,
            _wrap_cell(p.sector, styles),
        ])
    col_widths = [w*inch for w in [0.52,1.45,0.45,0.60,0.60,0.70,0.46,0.46,0.60,0.38,1.00]]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    cell_styles = [
        ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 7.5),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
        ("ALIGN",         (2,0),(-1,-1), "RIGHT"),
    ]
    for row_idx, p in enumerate(positions, start=1):
        # Colour earnings cell (col 8)
        if p.earnings and p.earnings.urgency in ("critical","warning","watch"):
            colour = _earnings_colour(p.earnings.urgency)
            cell_styles += [
                ("TEXTCOLOR", (8, row_idx),(8, row_idx), colour),
                ("FONTNAME",  (8, row_idx),(8, row_idx), "Helvetica-Bold"),
            ]
        # Colour freshness cell (col 9)
        if p.freshness and p.freshness.worst_status != "fresh":
            colour = _freshness_colour(p.freshness.worst_status)
            cell_styles += [
                ("TEXTCOLOR", (9, row_idx),(9, row_idx), colour),
                ("FONTNAME",  (9, row_idx),(9, row_idx), "Helvetica-Bold"),
            ]
        for col_idx, val in [(6, p.gain_loss_pct), (7, p.week_change_pct)]:
            if val is not None:
                colour = GREEN if val >= 0 else RED
                cell_styles += [
                    ("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), colour),
                    ("FONTNAME",  (col_idx, row_idx), (col_idx, row_idx), "Helvetica-Bold"),
                ]
    t.setStyle(TableStyle(cell_styles))
    return [Paragraph("HOLDINGS", styles["section_heading"]), _section_rule(), t, Spacer(1, 0.15*inch)]


def _sector_weights_section(styles, portfolio):
    elements = [Paragraph("ALLOCATION BREAKDOWN", styles["section_heading"]), _section_rule(),
                Paragraph("Sector Weights", styles["sub_heading"])]
    data = [["Sector", "Weight"]]
    for sector, pct in sorted(portfolio.sector_weights.items(), key=lambda x: -x[1]):
        data.append([_wrap_cell(sector, styles), f"{pct:.1f}%"])
    t = Table(data, colWidths=[4.0*inch, 1.0*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  MID_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 8),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
    ]))
    elements += [t, Spacer(1, 0.12*inch)]
    return elements


def _macro_section(styles, macro):
    elements = [
        Paragraph("MACRO MARKET SNAPSHOT", styles["section_heading"]), _section_rule(),
        Paragraph(macro.vix_interpretation, styles["body"]),
        Spacer(1, 0.08*inch),
        Paragraph("Market Indices", styles["sub_heading"]),
    ]
    idx_data = [["Symbol","Description","Price","1-Wk","1-Mo","1-Yr"]]
    for m in macro.indices:
        idx_data.append([m.symbol, _wrap_cell(m.label, styles), _na(m.current_price,".2f"),
                         _pct(m.week_change_pct), _pct(m.month_change_pct), _pct(m.year_change_pct)])
    it = Table(idx_data, colWidths=[w*inch for w in [0.6,1.7,0.8,0.7,0.7,0.7]])
    it.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 8),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
        ("ALIGN",         (2,0),(-1,-1), "RIGHT"),
    ]))
    for row_idx, m in enumerate(macro.indices, start=1):
        if m.week_change_pct is not None:
            colour = GREEN if m.week_change_pct >= 0 else RED
            it.setStyle(TableStyle([
                ("TEXTCOLOR", (3,row_idx),(3,row_idx), colour),
                ("FONTNAME",  (3,row_idx),(3,row_idx), "Helvetica-Bold"),
            ]))
    elements += [it, Spacer(1, 0.12*inch), Paragraph("Sector Rotation (best → worst this week)", styles["sub_heading"])]
    sec_data = [["ETF","Sector","1-Wk","1-Mo"]]
    for s in macro.sectors:
        sec_data.append([s.symbol, _wrap_cell(s.label, styles), _pct(s.week_change_pct), _pct(s.month_change_pct)])
    st = Table(sec_data, colWidths=[w*inch for w in [0.6,2.2,0.8,0.8]])
    st.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  MID_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 8),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
        ("ALIGN",         (2,0),(-1,-1), "RIGHT"),
    ]))
    for row_idx, s in enumerate(macro.sectors, start=1):
        if s.week_change_pct is not None:
            colour = GREEN if s.week_change_pct >= 0 else RED
            st.setStyle(TableStyle([("TEXTCOLOR",(2,row_idx),(2,row_idx),colour),
                                    ("FONTNAME",(2,row_idx),(2,row_idx),"Helvetica-Bold")]))
    elements += [st, Spacer(1, 0.12*inch)]
    return elements


def _ai_analysis_section(styles, messages):
    elements = [PageBreak(), Paragraph("AI ANALYSIS", styles["section_heading"]), _section_rule()]
    agent_map = {
        "HealthAgent": "Portfolio Health Assessment",
        "MacroAgent":  "Macro Context",
        "RiskAgent":   "Risk & Alerts",
        "Synthesis":   "Executive Summary & Actions",
    }
    for name, label in agent_map.items():
        content = next((m.content for m in messages if getattr(m, "name", None) == name), None)
        if not content: continue
        elements.append(Paragraph(label, styles["sub_heading"]))
        text = content
        for prefix in ["PORTFOLIO HEALTH:\n","MACRO CONTEXT:\n","RISK & ALERTS:\n","EXECUTIVE SUMMARY:\n"]:
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        for para in text.strip().split("\n\n"):
            para = para.strip()
            if not para: continue
            if para.startswith("- ") or para.startswith("• "):
                for line in para.split("\n"):
                    line = line.strip().lstrip("-•").strip()
                    if line: elements.append(Paragraph(f"• {line}", styles["body"]))
            elif para[0].isdigit() and ". " in para[:4]:
                for line in para.split("\n"):
                    if line.strip(): elements.append(Paragraph(line.strip(), styles["body"]))
            else:
                elements.append(Paragraph(para, styles["body"]))
        elements.append(Spacer(1, 0.1*inch))
    return elements


def _freshness_section(styles, positions: list) -> list:
    """
    Data freshness summary. Only shown if any position has
    stale or unknown data — keeps the report clean otherwise.
    """
    problem_positions = [
        p for p in positions
        if p.freshness and p.freshness.worst_status in ("stale", "very_stale", "unknown")
    ]
    if not problem_positions:
        return []   # All data current — no section needed

    elements = [
        Paragraph("DATA FRESHNESS WARNINGS", styles["section_heading"]),
        _section_rule(),
        Paragraph(
            "The following positions have data quality concerns. "
            "Scores and values for these holdings should be verified before acting.",
            styles["body"]
        ),
        Spacer(1, 0.08 * inch),
    ]

    rows = [["Ticker", "Company", "Price Status", "Fundamentals Status", "Action"]]
    for p in problem_positions:
        tf = p.freshness
        rows.append([
            p.ticker,
            _wrap_cell(p.company_name or p.ticker, styles),
            _wrap_cell(f"{tf.price.flag} {tf.price.label}", styles),
            _wrap_cell(f"{tf.fundamentals.flag} {tf.fundamentals.label}", styles),
            "Verify manually" if tf.worst_status == "very_stale" else "Monitor",
        ])

    t = Table(rows, colWidths=[0.6*inch, 1.6*inch, 2.0*inch, 2.2*inch, 0.9*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 7.5),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
    ]))

    for row_idx, p in enumerate(problem_positions, start=1):
        colour = _freshness_colour(p.freshness.worst_status)
        t.setStyle(TableStyle([
            ("TEXTCOLOR", (4, row_idx),(4, row_idx), colour),
            ("FONTNAME",  (4, row_idx),(4, row_idx), "Helvetica-Bold"),
        ]))

    elements += [t, Spacer(1, 0.15 * inch)]
    return elements


def _earnings_section(styles, positions: list) -> list:
    """
    Earnings calendar for all equity positions.
    Shows upcoming earnings sorted nearest-first,
    with colour-coded urgency.
    """
    equity_positions = [p for p in positions if p.asset_class.lower() != "etf"]
    if not equity_positions:
        return []

    elements = [
        Paragraph("EARNINGS CALENDAR", styles["section_heading"]),
        _section_rule(),
        Paragraph(
            "Upcoming earnings dates for your equity holdings. "
            "🔴 within 7 days  🟡 within 30 days  🔵 within 60 days  ✔ clear",
            styles["body"]
        ),
        Spacer(1, 0.08 * inch),
    ]

    # Sort: nearest first, unknowns last
    def _sort_key(p):
        if p.earnings and p.earnings.days_until is not None:
            return p.earnings.days_until
        return 9999

    sorted_positions = sorted(equity_positions, key=_sort_key)

    cal_data = [["Ticker", "Company", "Next Earnings", "Days Away", "Urgency"]]
    for p in sorted_positions:
        if not p.earnings:
            date_str, days_str, urgency_str = "Unknown", "—", "Unknown"
        else:
            ei = p.earnings
            date_str   = ei.next_earnings_date.strftime("%b %d, %Y") if ei.next_earnings_date else "Unknown"
            days_str   = str(ei.days_until) if ei.days_until is not None else "—"
            urgency_str = f"{ei.flag} {ei.urgency.capitalize()}"
        cal_data.append([
            p.ticker,
            _wrap_cell(p.company_name or p.ticker, styles),
            date_str, days_str, urgency_str,
        ])

    ct = Table(cal_data, colWidths=[0.65*inch, 2.4*inch, 1.4*inch, 0.9*inch, 1.65*inch])
    ct.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 8),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
    ]))

    for row_idx, p in enumerate(sorted_positions, start=1):
        if p.earnings:
            colour = _earnings_colour(p.earnings.urgency)
            ct.setStyle(TableStyle([
                ("TEXTCOLOR", (4, row_idx),(4, row_idx), colour),
                ("FONTNAME",  (4, row_idx),(4, row_idx), "Helvetica-Bold"),
                # Highlight entire row red if critical
                *([("BACKGROUND", (0,row_idx),(-1,row_idx), colors.HexColor("#FFF0F0"))]
                  if p.earnings.urgency == "critical" else []),
            ]))

    elements += [ct, Spacer(1, 0.15 * inch)]
    return elements


def _verification_section(styles, messages: list, verification_report) -> list:
    """
    Renders the verification report as a structured checklist.
    Only included when a verification_report object is available.
    """
    if verification_report is None:
        return []

    from verifier import VerificationReport

    rpt = verification_report
    verdict_colours = {
        "PASS":    VERIFY_GREEN,
        "CAUTION": WARN_AMBER,
        "FAIL":    URGENT_RED,
    }
    verdict_icons = {"PASS": "✅", "CAUTION": "🟡", "FAIL": "🔴"}
    verdict_colour = verdict_colours.get(rpt.overall_verdict, MID_GREY)
    verdict_icon   = verdict_icons.get(rpt.overall_verdict, "❓")

    elements = [
        PageBreak(),
        Paragraph("AI OUTPUT VERIFICATION", styles["section_heading"]),
        _section_rule(),
        Paragraph(
            "An independent verification agent checked the Executive Summary "
            "against the raw data. Each claim is marked SUPPORTED, UNSUPPORTED, "
            "CONTRADICTED, or CAVEAT. This section is a transparency layer — "
            "it does not rewrite the summary above.",
            styles["body"]
        ),
        Spacer(1, 0.08 * inch),
    ]

    # Overall verdict banner
    banner_data = [[
        Paragraph(
            f"{verdict_icon}  OVERALL VERDICT: {rpt.overall_verdict}",
            ParagraphStyle("VBanner", parent=styles["body"],
                fontSize=11, fontName="Helvetica-Bold", textColor=WHITE)
        ),
        Paragraph(
            f"✅ {rpt.supported_count} Supported   "
            f"🟡 {rpt.unsupported_count} Unsupported   "
            f"🔵 {rpt.caveat_count} Caveat   "
            f"🔴 {rpt.contradicted_count} Contradicted",
            ParagraphStyle("VCounts", parent=styles["body"],
                fontSize=8, fontName="Helvetica", textColor=WHITE, alignment=2)
        ),
    ]]
    bt = Table(banner_data, colWidths=[3.5*inch, 3.5*inch])
    bt.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), verdict_colour),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    elements += [bt, Spacer(1, 0.06*inch)]

    # Summary sentence
    elements.append(Paragraph(rpt.summary, styles["body"]))
    elements.append(Spacer(1, 0.1*inch))

    if not rpt.items:
        elements.append(Paragraph("No individual claims were parsed.", styles["body"]))
        return elements

    # Claim-by-claim checklist
    verdict_meta = {
        "SUPPORTED":    (VERIFY_GREEN, "✅"),
        "UNSUPPORTED":  (WARN_AMBER,   "🟡"),
        "CONTRADICTED": (URGENT_RED,   "🔴"),
        "CAVEAT":       (VERIFY_BLUE,  "🔵"),
    }

    rows = [["Verdict", "Claim", "Evidence / Reason"]]
    for item in rpt.items:
        colour, icon = verdict_meta.get(item.verdict, (MID_GREY, "❓"))
        verdict_cell = Paragraph(
            f"{icon} {item.verdict}",
            ParagraphStyle("VC", parent=styles["body"],
                fontSize=7.5, fontName="Helvetica-Bold",
                textColor=colour, alignment=1)
        )
        rows.append([
            verdict_cell,
            _wrap_cell(item.claim, styles),
            _wrap_cell(item.evidence if item.evidence else "—", styles),
        ])

    t = Table(rows, colWidths=[1.0*inch, 3.5*inch, 2.5*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  DARK_BLUE),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),(-1,-1), 7.5),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("GRID",          (0,0),(-1,-1), 0.25, MID_GREY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, LIGHT_GREY]),
    ]))

    # Highlight CONTRADICTED rows in light red
    for row_idx, item in enumerate(rpt.items, start=1):
        if item.verdict == "CONTRADICTED":
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,row_idx),(-1,row_idx), colors.HexColor("#FFF0F0")),
            ]))

    elements += [t, Spacer(1, 0.15*inch)]
    return elements


def generate_pdf(portfolio, macro, messages, output_path=None, verification_report=None):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_date = datetime.now().strftime("%Y-%m-%d_%H%M")
    if output_path is None:
        output_path = os.path.join(REPORTS_DIR, f"pulse_{report_date}.pdf")
    doc = SimpleDocTemplate(output_path, pagesize=letter,
        leftMargin=0.65*inch, rightMargin=0.65*inch,
        topMargin=0.6*inch,   bottomMargin=0.6*inch,
        title=f"Weekly Pulse Report — {report_date}")
    styles = _build_styles()
    story  = []
    story += _cover_section(styles, report_date.replace("_"," "))
    story += _summary_section(styles, portfolio)
    story += _holdings_table_section(styles, portfolio.positions)
    story += _sector_weights_section(styles, portfolio)
    story += _earnings_section(styles, portfolio.positions)
    story += _freshness_section(styles, portfolio.positions)
    story += _macro_section(styles, macro)
    story += _ai_analysis_section(styles, messages)
    story += _verification_section(styles, messages, verification_report)
    story += [
        Spacer(1, 0.3*inch),
        HRFlowable(width="100%", thickness=0.5, color=MID_GREY),
        Paragraph("This report is generated by an automated AI system for personal research purposes only. "
                  "It does not constitute financial advice. Always consult a qualified financial advisor "
                  "before making investment decisions.", styles["disclaimer"]),
    ]
    doc.build(story)
    return output_path
