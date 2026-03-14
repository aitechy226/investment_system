# portfolio/fundamental_bridge.py
# ─────────────────────────────────────────────
# Bridges the research/fundamentals scoring
# engine into the portfolio pulse pipeline.
#
# Scores your holdings on-demand using the
# same four-module engine (Quality, Value,
# Momentum, Income) without scanning the full
# S&P 500 universe — just your positions.
#
# Returns a compact text summary suitable for
# injection into LLM agent prompts.
# ─────────────────────────────────────────────

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LiveDataUnavailableError

# Import scoring engine from research/ folder
# We resolve the path relative to this file so
# portfolio/ can reach research/ without installing
# it as a package.
_RESEARCH_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "research"
)
sys.path.insert(0, _RESEARCH_DIR)

from fundamentals import (
    FundamentalScore,
    score_ticker,
    score_label,
)


def _score_one_ticker(args: Tuple[int, str]) -> Tuple[int, FundamentalScore]:
    """Worker: fetch info and score one ticker. Raises LiveDataUnavailableError on failure."""
    i, ticker = args
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        err_type = type(e).__name__
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved for {ticker}. "
            f"Backend error (yfinance): {err_type}: {e}. "
            "Do not use hardcoded tickers or default lists."
        ) from e
    if not info:
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved for {ticker} (yfinance returned empty .info). "
            "Do not use hardcoded tickers or default lists."
        )
    asset_type = "ETF" if info.get("quoteType") == "ETF" else "Stock"
    try:
        fs = score_ticker(ticker, asset_type, info)
    except Exception as e:
        err_type = type(e).__name__
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved for {ticker} (scoring failed). "
            f"Backend error: {err_type}: {e}. "
            "Do not use hardcoded tickers or default lists."
        ) from e
    return (i, fs)


def score_holdings(tickers: List[str]) -> List[FundamentalScore]:
    """
    Fetch live yfinance data and score each ticker in parallel. Fails if live data
    could not be retrieved for any ticker — no hardcoded tickers or default lists.
    """
    if not tickers:
        raise LiveDataUnavailableError(
            "Live data could not be retrieved: no tickers to score. "
            "Do not use hardcoded tickers or default lists."
        )
    max_workers = min(12, max(len(tickers), 2))
    results: Dict[int, FundamentalScore] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(_score_one_ticker, (i, t)): (i, t) for i, t in enumerate(tickers)}
        for fut in as_completed(future_to_ticker):
            i, ticker = future_to_ticker[fut]
            try:
                i, fs = fut.result()
                results[i] = fs
            except LiveDataUnavailableError:
                raise
            except Exception as e:
                err_type = type(e).__name__
                raise LiveDataUnavailableError(
                    f"Live data could not be retrieved for {ticker}. "
                    f"Backend error: {err_type}: {e}. "
                    "Do not use hardcoded tickers or default lists."
                ) from e
    scores = [results[i] for i in range(len(tickers))]
    if len(scores) != len(tickers):
        raise LiveDataUnavailableError(
            "Live data could not be retrieved: not all tickers scored. "
            "Do not use hardcoded tickers or default lists."
        )
    return scores


def fmt_fundamental_scores(scores: List[FundamentalScore]) -> str:
    """
    Format fundamental scores as a compact text table
    for injection into LLM agent prompts.

    Includes:
    - Per-module scores (0-100) with labels
    - Composite score
    - Key flags (stale data, deteriorating fundamentals,
      high leverage, revenue decline)
    - Sector context note for financial names
    """
    if not scores:
        return "No fundamental scores available."

    lines = [
        "FUNDAMENTAL SCORES (your holdings — scored 0-100 per module):",
        f"{'Ticker':<8} {'Quality':>8} {'Value':>7} {'Momentum':>9} {'Income':>7} "
        f"{'Composite':>10} {'Profile':<20} {'Key Flags'}",
        "-" * 120,
    ]

    for fs in sorted(scores, key=lambda x: -x.composite_score):
        q_lbl  = score_label(fs.quality_score)
        v_lbl  = score_label(fs.value_score)
        m_lbl  = score_label(fs.momentum_score)
        i_lbl  = score_label(fs.income_score)
        c_lbl  = score_label(fs.composite_score)
        profile = fs.sector_profile_used[:18] if fs.sector_profile_used else fs.sector[:18]

        # Distil flags to the most important 1-2 for the prompt
        # (full flags appear in PDF; here we want signal density)
        key_flags = _distil_flags(fs)

        if fs.skipped:
            lines.append(
                f"{fs.symbol:<8} {'—':>8} {'—':>7} {'—':>9} {'—':>7} "
                f"{'SKIPPED':>10} {profile:<20} {fs.skip_reason}"
            )
        else:
            lines.append(
                f"{fs.symbol:<8} "
                f"{fs.quality_score:>5.0f} {q_lbl:<4} "
                f"{fs.value_score:>4.0f} {v_lbl:<3} "
                f"{fs.momentum_score:>6.0f} {m_lbl:<4} "
                f"{fs.income_score:>4.0f} {i_lbl:<3} "
                f"{fs.composite_score:>7.0f} {c_lbl:<4} "
                f"{profile:<20} {key_flags}"
            )

    lines += [
        "",
        "Score bands: 75-100 Strong | 60-74 Good | 45-59 Fair | 30-44 Weak | 0-29 Poor",
        "Note: ETF scores reflect index-level data — individual company metrics not available.",
    ]
    return "\n".join(lines)


def _distil_flags(fs: FundamentalScore) -> str:
    """
    Pick the 1-3 most actionable flags for prompt injection.
    Priority: data quality > risk > opportunity.
    """
    priority = []

    # Data quality first — if data is stale, scores are suspect
    for f in fs.flags:
        if any(k in f for k in ["stale", "Stale", "very stale", "unknown"]):
            priority.append("⚠️ STALE DATA")
            break

    # Risk flags
    for f in fs.flags:
        if "Revenue declining" in f:
            priority.append("⚠️ Rev declining")
            break
    for f in fs.flags:
        if "High leverage" in f:
            priority.append("⚠️ High D/E")
            break
    for f in fs.flags:
        if "below 200-day" in f:
            priority.append("⚠️ Below 200MA")
            break
    for f in fs.flags:
        if "Earnings" in f and any(k in f for k in ["🔴", "🟡"]):
            priority.append("📅 Earnings soon")
            break

    # Opportunity flags (only if no major risk flags)
    if len(priority) == 0:
        for f in fs.flags:
            if "High quality at reasonable price" in f:
                priority.append("✅ Quality+Value")
                break
        for f in fs.flags:
            if "FCF yield" in f:
                priority.append("💰 Strong FCF")
                break

    return "  ".join(priority[:3]) if priority else "—"


def fmt_fundamental_context_for_health(scores: List[FundamentalScore]) -> str:
    """
    A richer context block specifically for the health agent.
    Includes module-level breakdown and notable flags.
    """
    table = fmt_fundamental_scores(scores)

    # Add narrative summary of outliers
    skipped     = [fs for fs in scores if fs.skipped]
    weak_quality = [fs for fs in scores if not fs.skipped and fs.quality_score < 40]
    weak_value   = [fs for fs in scores if not fs.skipped and fs.value_score   < 40]
    strong       = [fs for fs in scores if not fs.skipped and fs.composite_score >= 70]
    stale_data   = [fs for fs in scores if not fs.skipped and fs.freshness
                    and fs.freshness.worst_status in ("stale", "very_stale")]

    notes = []
    if strong:
        notes.append(f"Fundamentally strongest: {', '.join(fs.symbol for fs in strong)}")
    if weak_quality:
        notes.append(
            f"Weak quality scores (< 40) — review thesis: "
            f"{', '.join(fs.symbol for fs in weak_quality)}"
        )
    if weak_value:
        notes.append(
            f"Potentially overvalued (value score < 40): "
            f"{', '.join(fs.symbol for fs in weak_value)}"
        )
    if stale_data:
        notes.append(
            f"Stale fundamental data — scores less reliable: "
            f"{', '.join(fs.symbol for fs in stale_data)}"
        )
    if skipped:
        notes.append(
            f"Could not score (insufficient data): "
            f"{', '.join(fs.symbol for fs in skipped)}"
        )

    if notes:
        return table + "\n\nKEY OBSERVATIONS:\n" + "\n".join(f"  • {n}" for n in notes)
    return table


def fmt_fundamental_context_for_risk(scores: List[FundamentalScore]) -> str:
    """
    Risk-focused context block for the risk agent.
    Highlights only positions with warning flags.
    """
    risk_items = []
    for fs in scores:
        if fs.skipped:
            continue
        item_flags = []
        if fs.quality_score < 40:
            item_flags.append(f"quality {fs.quality_score:.0f}/100")
        if fs.momentum_score < 35:
            item_flags.append(f"momentum {fs.momentum_score:.0f}/100 — possible downtrend")
        if fs.freshness and fs.freshness.worst_status == "very_stale":
            item_flags.append("fundamentals data very stale — scores unreliable")
        for f in fs.flags:
            if "Revenue declining" in f:
                item_flags.append("revenue declining YoY")
            if "High leverage" in f:
                item_flags.append(f"high D/E ratio")
            if "Earnings" in f and "🔴" in f:
                item_flags.append("earnings CRITICAL — within 7 days")
            elif "Earnings" in f and "🟡" in f:
                item_flags.append("earnings within 30 days")
        if item_flags:
            risk_items.append(
                f"  {fs.symbol} ({fs.sector_profile_used}): "
                + ", ".join(item_flags)
            )

    if not risk_items:
        return "No fundamental risk flags on current holdings."

    return "FUNDAMENTAL RISK FLAGS:\n" + "\n".join(risk_items)
