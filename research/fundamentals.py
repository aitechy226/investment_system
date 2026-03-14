# research/fundamentals.py  —  VERSION 2
# ─────────────────────────────────────────────
# Multi-factor fundamental scoring engine.
#
# FIXES APPLIED IN THIS VERSION:
#
#   FIX 1: Sector-relative scoring
#          Thresholds adapt per GICS sector so
#          a grocery margin isn't judged by
#          software standards.
#
#   FIX 2: Financial sector D/E exemption
#          Banks, insurers, REITs bypass D/E
#          gate and D/E scoring entirely.
#          ROE is double-weighted instead.
#
#   FIX 3: Negative PEG / null earnings handled
#          Negative PEG (loss→profit) rewarded
#          modestly. Extreme earnings distortions
#          (< -95%) excluded from average.
#          Null earnings growth skipped cleanly.
#
#   FIX 4: Momentum retuned for 1yr+ investors
#          200-day MA double-weighted (primary).
#          52-week range position replaces
#          "distance from high" penalty logic.
#
#   FIX 5: Income zero penalty removed
#          Non-dividend payers score 50 (neutral)
#          not 0 — growth stocks no longer
#          structurally penalised on composite.
#
# ─────────────────────────────────────────────

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from earnings import EarningsInfo, fetch_earnings_date, earnings_flag_text
from data_freshness import TickerFreshness, assess_freshness, freshness_flag_text

# ── Module weights (must sum to 1.0) ─────────
MODULE_WEIGHTS = {
    "quality":  0.30,
    "value":    0.25,
    "momentum": 0.25,
    "income":   0.20,
}

# ── Quality gate ──────────────────────────────
MIN_ANALYST_OPINIONS           = 3
MIN_MARKET_CAP                 = 2e9
MAX_DEBT_TO_EQUITY_NONFINANCIAL = 300.0

# ── Financial sectors — D/E exempted ─────────
FINANCIAL_SECTORS = {
    "Financial Services", "Financials", "Banking",
    "Insurance", "Real Estate", "Mortgage Finance",
}


# ─────────────────────────────────────────────
# Sector profiles
# ─────────────────────────────────────────────

_DEFAULT_PROFILE = {
    "profit_margin": (0.0,  25.0),
    "gross_margin":  (0.0,  60.0),
    "roe":           (0.0,  25.0),
    "rev_growth":    (-10.0, 20.0),
    "earn_growth":   (-20.0, 25.0),
    "forward_pe":    (8.0,  35.0),
    "ev_ebitda":     (5.0,  20.0),
    "fcf_yield":     (0.0,   8.0),
    "price_to_book": (1.0,   6.0),
}

SECTOR_PROFILES: Dict[str, Dict] = {
    "Technology": {
        "profit_margin": (0.0,  35.0),
        "gross_margin":  (20.0, 80.0),
        "roe":           (0.0,  40.0),
        "rev_growth":    (-5.0, 25.0),
        "earn_growth":   (-10.0, 35.0),
        "forward_pe":    (15.0, 50.0),
        "ev_ebitda":     (10.0, 35.0),
        "fcf_yield":     (0.0,   6.0),
    },
    "Healthcare": {
        "profit_margin": (-5.0, 25.0),
        "gross_margin":  (20.0, 75.0),
        "roe":           (0.0,  25.0),
        "rev_growth":    (-5.0, 20.0),
        "earn_growth":   (-30.0, 30.0),
        "forward_pe":    (10.0, 40.0),
        "ev_ebitda":     (8.0,  25.0),
        "fcf_yield":     (0.0,   7.0),
    },
    "Consumer Staples": {
        "profit_margin": (0.0,  15.0),
        "gross_margin":  (20.0, 50.0),
        "roe":           (0.0,  30.0),
        "rev_growth":    (-5.0, 10.0),
        "earn_growth":   (-10.0, 15.0),
        "forward_pe":    (10.0, 25.0),
        "ev_ebitda":     (8.0,  18.0),
        "fcf_yield":     (2.0,   8.0),
    },
    "Consumer Discretionary": {
        "profit_margin": (0.0,  15.0),
        "gross_margin":  (20.0, 50.0),
        "roe":           (0.0,  30.0),
        "rev_growth":    (-5.0, 20.0),
        "earn_growth":   (-20.0, 30.0),
        "forward_pe":    (10.0, 35.0),
        "ev_ebitda":     (8.0,  22.0),
        "fcf_yield":     (0.0,   7.0),
    },
    "Industrials": {
        "profit_margin": (0.0,  15.0),
        "gross_margin":  (15.0, 40.0),
        "roe":           (0.0,  20.0),
        "rev_growth":    (-5.0, 15.0),
        "earn_growth":   (-15.0, 20.0),
        "forward_pe":    (10.0, 25.0),
        "ev_ebitda":     (8.0,  18.0),
        "fcf_yield":     (2.0,   8.0),
    },
    "Energy": {
        "profit_margin": (-5.0, 20.0),
        "gross_margin":  (10.0, 50.0),
        "roe":           (-5.0, 25.0),
        "rev_growth":    (-20.0, 20.0),
        "earn_growth":   (-50.0, 50.0),
        "forward_pe":    (5.0,  20.0),
        "ev_ebitda":     (3.0,  12.0),
        "fcf_yield":     (3.0,  12.0),
    },
    "Materials": {
        "profit_margin": (0.0,  20.0),
        "gross_margin":  (15.0, 45.0),
        "roe":           (0.0,  20.0),
        "rev_growth":    (-10.0, 15.0),
        "earn_growth":   (-30.0, 30.0),
        "forward_pe":    (8.0,  22.0),
        "ev_ebitda":     (5.0,  15.0),
        "fcf_yield":     (2.0,   9.0),
    },
    "Communication Services": {
        "profit_margin": (0.0,  25.0),
        "gross_margin":  (30.0, 70.0),
        "roe":           (0.0,  30.0),
        "rev_growth":    (-5.0, 20.0),
        "earn_growth":   (-20.0, 30.0),
        "forward_pe":    (10.0, 35.0),
        "ev_ebitda":     (8.0,  25.0),
        "fcf_yield":     (0.0,   7.0),
    },
    "Utilities": {
        "profit_margin": (5.0,  20.0),
        "gross_margin":  (20.0, 50.0),
        "roe":           (5.0,  15.0),
        "rev_growth":    (-5.0,  8.0),
        "earn_growth":   (-10.0, 12.0),
        "forward_pe":    (10.0, 22.0),
        "ev_ebitda":     (8.0,  18.0),
        "fcf_yield":     (2.0,   7.0),
    },
    "Financial Services": {
        "profit_margin": (5.0,  30.0),
        "roe":           (5.0,  20.0),
        "rev_growth":    (-5.0, 15.0),
        "earn_growth":   (-15.0, 20.0),
        "forward_pe":    (6.0,  18.0),
        "price_to_book": (0.5,   2.5),
        "fcf_yield":     (2.0,   8.0),
    },
    "Real Estate": {
        "profit_margin": (10.0, 40.0),
        "roe":           (3.0,  15.0),
        "rev_growth":    (-5.0, 12.0),
        "earn_growth":   (-20.0, 20.0),
        "forward_pe":    (10.0, 30.0),
        "price_to_book": (0.5,   3.0),
        "fcf_yield":     (2.0,   7.0),
    },
}

_SECTOR_ALIASES = {
    "Financial Services": "Financial Services",
    "Financials":         "Financial Services",
    "Banking":            "Financial Services",
    "Insurance":          "Financial Services",
    "Real Estate":        "Real Estate",
    "Mortgage Finance":   "Real Estate",
    "Technology":         "Technology",
    "Information Technology": "Technology",
    "Healthcare":         "Healthcare",
    "Health Care":        "Healthcare",
    "Consumer Staples":   "Consumer Staples",
    "Consumer Defensive": "Consumer Staples",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Cyclical":  "Consumer Discretionary",
    "Industrials":        "Industrials",
    "Energy":             "Energy",
    "Materials":          "Materials",
    "Basic Materials":    "Materials",
    "Communication Services": "Communication Services",
    "Communication":      "Communication Services",
    "Utilities":          "Utilities",
}


def _resolve_sector(raw: str) -> str:
    return _SECTOR_ALIASES.get(raw, raw)


def _get_profile(sector: str) -> Dict:
    resolved = _resolve_sector(sector)
    profile  = dict(_DEFAULT_PROFILE)
    profile.update(SECTOR_PROFILES.get(resolved, {}))
    return profile


def _is_financial(sector: str) -> bool:
    return _resolve_sector(sector) in {"Financial Services", "Real Estate"}


# ─────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────

def _score_linear(value: float, low: float, high: float, invert: bool = False) -> float:
    if high == low:
        return 50.0
    raw = (value - low) / (high - low) * 100.0
    raw = max(0.0, min(100.0, raw))
    return 100.0 - raw if invert else raw


def _safe(info: dict, key: str) -> Optional[float]:
    val = info.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _passes_quality_gate(info: dict, sector: str) -> Tuple[bool, str]:
    opinions = _safe(info, "numberOfAnalystOpinions")
    if opinions is not None and opinions < MIN_ANALYST_OPINIONS:
        return False, f"Only {int(opinions)} analyst opinions (min {MIN_ANALYST_OPINIONS})"

    mktcap = _safe(info, "marketCap")
    if mktcap is not None and mktcap < MIN_MARKET_CAP:
        return False, f"Market cap ${mktcap/1e9:.1f}B below ${MIN_MARKET_CAP/1e9:.0f}B minimum"

    if not _is_financial(sector):
        debt_eq = _safe(info, "debtToEquity")
        if debt_eq is not None and debt_eq > MAX_DEBT_TO_EQUITY_NONFINANCIAL:
            return False, f"D/E {debt_eq:.0f}% exceeds {MAX_DEBT_TO_EQUITY_NONFINANCIAL:.0f}% ceiling"

    price = (_safe(info, "currentPrice") or _safe(info, "regularMarketPrice") or _safe(info, "navPrice"))
    if not price or price <= 0:
        return False, "No valid price"

    return True, ""


# ─────────────────────────────────────────────
# Module 1 — Quality Growth
# ─────────────────────────────────────────────

def score_quality_growth(info: dict, sector: str) -> Tuple[float, Dict]:
    detail, sub_scores = {}, []
    profile  = _get_profile(sector)
    is_fin   = _is_financial(sector)

    # ROE — double-weighted for financial sectors
    roe = _safe(info, "returnOnEquity")
    if roe is not None:
        lo, hi = profile["roe"]
        s = _score_linear(roe * 100, lo, hi)
        reps = 2 if is_fin else 1
        sub_scores.extend([s] * reps)
        detail["roe_pct"] = round(roe * 100, 1)
        detail["roe_score"] = round(s, 1)

    # Revenue growth
    rg = _safe(info, "revenueGrowth")
    if rg is not None:
        lo, hi = profile["rev_growth"]
        s = _score_linear(rg * 100, lo, hi)
        sub_scores.append(s)
        detail["revenue_growth_pct"] = round(rg * 100, 1)
        detail["revenue_growth_score"] = round(s, 1)

    # Earnings growth — skip extreme distortions (FIX 3)
    eg = _safe(info, "earningsGrowth")
    if eg is not None:
        if eg < -0.95:
            detail["earnings_growth_pct"]  = round(eg * 100, 1)
            detail["earnings_growth_note"] = "Excluded: likely one-time distortion"
        else:
            lo, hi = profile["earn_growth"]
            s = _score_linear(eg * 100, lo, hi)
            sub_scores.append(s)
            detail["earnings_growth_pct"]   = round(eg * 100, 1)
            detail["earnings_growth_score"] = round(s, 1)

    # Net profit margin
    pm = _safe(info, "profitMargins")
    if pm is not None:
        lo, hi = profile["profit_margin"]
        s = _score_linear(pm * 100, lo, hi)
        sub_scores.append(s)
        detail["profit_margin_pct"]   = round(pm * 100, 1)
        detail["profit_margin_score"] = round(s, 1)

    # D/E — non-financial only (FIX 2)
    if not is_fin:
        de = _safe(info, "debtToEquity")
        if de is not None:
            s = _score_linear(de, 0, 200, invert=True)
            sub_scores.append(s)
            detail["debt_to_equity"] = round(de, 1)
            detail["debt_score"]     = round(s, 1)

    # Gross margin
    gm = _safe(info, "grossMargins")
    if gm is not None:
        lo, hi = profile["gross_margin"]
        s = _score_linear(gm * 100, lo, hi)
        sub_scores.append(s)
        detail["gross_margin_pct"]   = round(gm * 100, 1)
        detail["gross_margin_score"] = round(s, 1)

    score = sum(sub_scores) / len(sub_scores) if sub_scores else 0.0
    detail["signals_used"]       = len(sub_scores)
    detail["sector_profile"]     = _resolve_sector(sector)
    detail["financial_adjusted"] = is_fin
    return round(score, 1), detail


# ─────────────────────────────────────────────
# Module 2 — Value
# ─────────────────────────────────────────────

def score_value(info: dict, sector: str) -> Tuple[float, Dict]:
    detail, sub_scores = {}, []
    profile = _get_profile(sector)
    is_fin  = _is_financial(sector)

    # Forward P/E
    fpe = _safe(info, "forwardPE")
    if fpe is not None and fpe > 0:
        lo, hi = profile["forward_pe"]
        s = _score_linear(fpe, lo, hi, invert=True)
        sub_scores.append(s)
        detail["forward_pe"]       = round(fpe, 1)
        detail["forward_pe_score"] = round(s, 1)

    # PEG — negative PEG gets modest reward (FIX 3)
    peg = _safe(info, "pegRatio")
    if peg is not None:
        if peg < 0:
            sub_scores.append(65.0)
            detail["peg_ratio"] = round(peg, 2)
            detail["peg_note"]  = "Negative: loss→profit transition (rewarded modestly)"
        elif 0 < peg < 10:
            s = _score_linear(peg, 0.5, 3.0, invert=True)
            sub_scores.append(s)
            detail["peg_ratio"] = round(peg, 2)
            detail["peg_score"] = round(s, 1)

    # FCF yield
    fcf    = _safe(info, "freeCashflow")
    mktcap = _safe(info, "marketCap")
    if fcf and mktcap and mktcap > 0 and fcf > 0:
        fcfy = fcf / mktcap * 100
        lo, hi = profile["fcf_yield"]
        s = _score_linear(fcfy, lo, hi)
        sub_scores.append(s)
        detail["fcf_yield_pct"]   = round(fcfy, 2)
        detail["fcf_yield_score"] = round(s, 1)

    # Price/Book
    pb = _safe(info, "priceToBook")
    if pb is not None and pb > 0:
        lo, hi = profile["price_to_book"]
        s = _score_linear(pb, lo, hi, invert=True)
        sub_scores.append(s)
        detail["price_to_book"] = round(pb, 2)
        detail["pb_score"]      = round(s, 1)

    # EV/EBITDA — non-financial only (FIX 2)
    if not is_fin:
        ev = _safe(info, "enterpriseToEbitda")
        if ev is not None and 0 < ev < 200:
            lo, hi = profile["ev_ebitda"]
            s = _score_linear(ev, lo, hi, invert=True)
            sub_scores.append(s)
            detail["ev_to_ebitda"]    = round(ev, 1)
            detail["ev_ebitda_score"] = round(s, 1)

    score = sum(sub_scores) / len(sub_scores) if sub_scores else 0.0
    detail["signals_used"] = len(sub_scores)
    return round(score, 1), detail


# ─────────────────────────────────────────────
# Module 3 — Momentum (retuned for 1yr+)
# ─────────────────────────────────────────────

def score_momentum(info: dict, sector: str) -> Tuple[float, Dict]:
    detail, sub_scores = {}, []

    price = (_safe(info, "currentPrice") or _safe(info, "regularMarketPrice") or _safe(info, "navPrice"))
    if not price:
        return 0.0, {"error": "no price"}

    # 200-day MA — primary trend, double-weighted (FIX 4)
    ma200 = _safe(info, "twoHundredDayAverage")
    if ma200 and ma200 > 0:
        pct = (price - ma200) / ma200 * 100
        s   = _score_linear(pct, -30, 30)
        sub_scores.extend([s, s])   # double weight
        detail["pct_vs_200d_ma"] = round(pct, 1)
        detail["ma200_score"]    = round(s, 1)

    # 50-day MA — medium trend confirmation
    ma50 = _safe(info, "fiftyDayAverage")
    if ma50 and ma50 > 0:
        pct = (price - ma50) / ma50 * 100
        s   = _score_linear(pct, -20, 20)
        sub_scores.append(s)
        detail["pct_vs_50d_ma"] = round(pct, 1)
        detail["ma50_score"]    = round(s, 1)

    # 52-week range position (FIX 4)
    # 0% = at 52w low, 100% = at 52w high
    # Score range: 20 (at low) to 80 (at high) — avoids penalising highs
    low_52  = _safe(info, "fiftyTwoWeekLow")
    high_52 = _safe(info, "fiftyTwoWeekHigh")
    if low_52 and high_52 and low_52 > 0 and (high_52 - low_52) > 0:
        pos = (price - low_52) / (high_52 - low_52) * 100
        s   = max(0, min(100, 20 + pos * 0.6))
        sub_scores.append(s)
        detail["position_in_52w_range_pct"] = round(pos, 1)
        detail["range_position_score"]      = round(s, 1)

    # Absolute momentum proxy: % above 52w low (FIX 4)
    if low_52 and low_52 > 0:
        pct_from_low = (price - low_52) / low_52 * 100
        s = 30 + _score_linear(pct_from_low, 0, 80) * 0.7
        sub_scores.append(s)
        detail["pct_from_52w_low"]   = round(pct_from_low, 1)
        detail["momentum_52w_score"] = round(s, 1)

    score = sum(sub_scores) / len(sub_scores) if sub_scores else 0.0
    detail["signals_used"] = len(sub_scores)
    return round(score, 1), detail


# ─────────────────────────────────────────────
# Module 4 — Income (neutral for non-payers)
# ─────────────────────────────────────────────

def score_income(info: dict, sector: str) -> Tuple[float, Dict]:
    detail, sub_scores = {}, []

    div_yield = _safe(info, "dividendYield")

    # FIX 5: No dividend → neutral 50, not zero
    if div_yield is None or div_yield <= 0:
        detail["dividend_yield_pct"] = 0.0
        detail["note"] = "No dividend. Neutral score (50) applied."
        return 50.0, detail

    # Yield — cap reward at 7%, slight penalty >6%
    effective = min(div_yield, 0.07)
    s = _score_linear(effective * 100, 0, 4)
    if div_yield > 0.06:
        s *= 0.85
    sub_scores.append(s)
    detail["dividend_yield_pct"] = round(div_yield * 100, 2)
    detail["yield_score"]        = round(s, 1)

    # Payout ratio
    payout = _safe(info, "payoutRatio")
    if payout is not None and 0 < payout <= 1.5:
        pp = payout * 100
        s  = _score_linear(pp, 10, 65) if pp <= 65 else _score_linear(pp, 65, 95, invert=True)
        sub_scores.append(s)
        detail["payout_ratio_pct"] = round(pp, 1)
        detail["payout_score"]     = round(s, 1)

    # FCF coverage
    fcf    = _safe(info, "freeCashflow")
    mktcap = _safe(info, "marketCap")
    if fcf and mktcap and mktcap > 0 and fcf > 0:
        cov = (fcf / mktcap) / div_yield
        s   = _score_linear(cov, 0.5, 2.5)
        sub_scores.append(s)
        detail["fcf_dividend_coverage"] = round(cov, 2)
        detail["fcf_coverage_score"]    = round(s, 1)

    # 5-year average yield
    avg5 = _safe(info, "fiveYearAvgDividendYield")
    if avg5 and avg5 > 0:
        s = _score_linear(avg5, 0, 4)
        sub_scores.append(s)
        detail["five_yr_avg_yield_pct"] = round(avg5, 2)
        detail["five_yr_yield_score"]   = round(s, 1)

    score = sum(sub_scores) / len(sub_scores) if sub_scores else 50.0
    detail["signals_used"] = len(sub_scores)
    return round(score, 1), detail


# ─────────────────────────────────────────────
# Composite scorer
# ─────────────────────────────────────────────

@dataclass
class FundamentalScore:
    symbol:          str
    name:            str
    sector:          str
    asset_type:      str

    quality_score:   float
    value_score:     float
    momentum_score:  float
    income_score:    float
    composite_score: float

    current_price:      Optional[float]
    market_cap_b:       Optional[float]
    forward_pe:         Optional[float]
    div_yield_pct:      Optional[float]
    revenue_growth_pct: Optional[float]
    debt_to_equity:     Optional[float]
    pct_from_52w_high:  Optional[float]

    quality_detail:  Dict = field(default_factory=dict)
    value_detail:    Dict = field(default_factory=dict)
    momentum_detail: Dict = field(default_factory=dict)
    income_detail:   Dict = field(default_factory=dict)

    skipped:     bool      = False
    skip_reason: str       = ""
    flags:       List[str] = field(default_factory=list)

    is_financial_sector: bool = False
    sector_profile_used: str  = ""

    # Earnings awareness — populated by enrich_with_earnings()
    earnings: Optional[EarningsInfo] = None

    # Data freshness — populated by score_ticker()
    freshness: Optional[TickerFreshness] = None


def score_ticker(symbol: str, asset_type: str, info: dict) -> FundamentalScore:
    name   = (info.get("longName") or info.get("shortName") or symbol)[:40]
    sector = info.get("sector") or info.get("quoteType") or "Unknown"

    passes, reason = _passes_quality_gate(info, sector)
    if not passes:
        return FundamentalScore(
            symbol=symbol, name=name, sector=sector, asset_type=asset_type,
            quality_score=0, value_score=0, momentum_score=0, income_score=0,
            composite_score=0, current_price=None, market_cap_b=None,
            forward_pe=None, div_yield_pct=None, revenue_growth_pct=None,
            debt_to_equity=None, pct_from_52w_high=None,
            skipped=True, skip_reason=reason,
        )

    # Assess data freshness immediately — before scoring
    freshness = assess_freshness(symbol, info)

    q_score, q_detail = score_quality_growth(info, sector)
    v_score, v_detail = score_value(info, sector)
    m_score, m_detail = score_momentum(info, sector)
    i_score, i_detail = score_income(info, sector)

    composite = (
        q_score * MODULE_WEIGHTS["quality"]  +
        v_score * MODULE_WEIGHTS["value"]    +
        m_score * MODULE_WEIGHTS["momentum"] +
        i_score * MODULE_WEIGHTS["income"]
    )

    price   = _safe(info, "currentPrice") or _safe(info, "regularMarketPrice") or _safe(info, "navPrice")
    mktcap  = _safe(info, "marketCap")
    high_52 = _safe(info, "fiftyTwoWeekHigh")
    pct_fh  = round((price - high_52) / high_52 * 100, 1) if price and high_52 and high_52 > 0 else None

    fs = FundamentalScore(
        symbol=symbol, name=name, sector=sector, asset_type=asset_type,
        quality_score=round(q_score, 1),
        value_score=round(v_score, 1),
        momentum_score=round(m_score, 1),
        income_score=round(i_score, 1),
        composite_score=round(composite, 1),
        current_price=price,
        market_cap_b=round(mktcap / 1e9, 1) if mktcap else None,
        forward_pe=_safe(info, "forwardPE"),
        div_yield_pct=round(_safe(info, "dividendYield") * 100, 2) if _safe(info, "dividendYield") else None,
        revenue_growth_pct=round(_safe(info, "revenueGrowth") * 100, 1) if _safe(info, "revenueGrowth") else None,
        debt_to_equity=_safe(info, "debtToEquity"),
        pct_from_52w_high=pct_fh,
        quality_detail=q_detail,
        value_detail=v_detail,
        momentum_detail=m_detail,
        income_detail=i_detail,
        is_financial_sector=_is_financial(sector),
        sector_profile_used=_resolve_sector(sector),
        freshness=freshness,
    )
    fs.flags = _generate_flags(fs, info)
    return fs


def _generate_flags(fs: FundamentalScore, info: dict) -> List[str]:
    flags = []

    if not fs.is_financial_sector:
        if fs.debt_to_equity is not None and fs.debt_to_equity > 150:
            flags.append(f"⚠️  High leverage: D/E {fs.debt_to_equity:.0f}%")

    if fs.div_yield_pct is not None and fs.div_yield_pct > 6.0:
        flags.append(f"⚠️  Yield {fs.div_yield_pct:.1f}% — verify dividend sustainability")

    payout = _safe(info, "payoutRatio")
    if payout is not None and payout > 0.80:
        flags.append(f"⚠️  Payout ratio {payout*100:.0f}% — sustainability risk")

    if fs.revenue_growth_pct is not None and fs.revenue_growth_pct < 0:
        flags.append(f"⚠️  Revenue declining: {fs.revenue_growth_pct:.1f}% YoY")

    ma200 = _safe(info, "twoHundredDayAverage")
    if ma200 and fs.current_price and fs.current_price < ma200 * 0.85:
        flags.append(f"⚠️  {((fs.current_price-ma200)/ma200*100):.1f}% below 200-day MA — downtrend")

    eg = _safe(info, "earningsGrowth")
    if eg is not None and -0.95 < eg < -0.30:
        flags.append(f"⚠️  Earnings down {abs(eg)*100:.0f}% YoY — verify not structural")

    if fs.quality_score >= 70 and fs.value_score >= 65:
        flags.append("✅  High quality at reasonable price")

    if fs.pct_from_52w_high is not None and -30 <= fs.pct_from_52w_high <= -8:
        flags.append(f"📉  {abs(fs.pct_from_52w_high):.0f}% off 52w high — potential entry in uptrend")

    fcf    = _safe(info, "freeCashflow")
    mktcap = _safe(info, "marketCap")
    if fcf and mktcap and mktcap > 0 and fcf / mktcap * 100 > 5:
        flags.append(f"💰  FCF yield {fcf/mktcap*100:.1f}% — strong cash generation")

    if fs.momentum_score >= 70 and fs.quality_score >= 60:
        flags.append("📈  Uptrend confirmed by solid fundamentals")

    if fs.is_financial_sector:
        flags.append("🏦  Financial sector — D/E excluded; ROE is primary quality metric")

    # Data freshness flags — warn if scoring on stale financials
    if fs.freshness:
        flag_text = freshness_flag_text(fs.freshness)
        if flag_text:
            for line in flag_text.split('\n'):
                if line.strip():
                    flags.append(line.strip())

    return flags


# ─────────────────────────────────────────────
# Earnings enrichment
# ─────────────────────────────────────────────

def enrich_with_earnings(scores: List[FundamentalScore]) -> List[FundamentalScore]:
    """
    Fetch earnings dates for all scored tickers and attach to each
    FundamentalScore. Also appends earnings flag to score.flags
    if earnings are within the watch window (60 days).

    Called after score_universe() — kept separate so the scoring
    step doesn't slow down if earnings fetch is skipped.
    """
    print(f"  Fetching earnings dates for {len(scores)} tickers...")
    for fs in scores:
        try:
            ei = fetch_earnings_date(fs.symbol)
            fs.earnings = ei
            flag_text = earnings_flag_text(ei)
            if flag_text and flag_text not in fs.flags:
                fs.flags.append(flag_text)
        except Exception:
            pass
    return scores


# ─────────────────────────────────────────────
# Universe scoring + three views
# ─────────────────────────────────────────────

def score_universe(cached_info: Dict[str, tuple]) -> List[FundamentalScore]:
    results = []
    for symbol, (asset_type, info) in cached_info.items():
        fs = score_ticker(symbol, asset_type, info)
        if not fs.skipped:
            results.append(fs)
    return results


def view_composite_ranked(
    scores: List[FundamentalScore],
    top_n: int = 25,
    min_composite: float = 45.0,
) -> List[FundamentalScore]:
    filtered = [s for s in scores if s.composite_score >= min_composite]
    filtered.sort(key=lambda x: -x.composite_score)
    return filtered[:top_n]


def view_by_strategy(
    scores: List[FundamentalScore],
    top_n: int = 15,
    min_score: float = 50.0,
) -> Dict[str, List[FundamentalScore]]:
    def _top(key: str) -> List[FundamentalScore]:
        f = [s for s in scores if getattr(s, f"{key}_score") >= min_score]
        f.sort(key=lambda x: -getattr(x, f"{key}_score"))
        return f[:top_n]
    return {
        "quality":  _top("quality"),
        "value":    _top("value"),
        "momentum": _top("momentum"),
        "income":   _top("income"),
    }


def view_watchlist_flags(
    scores: List[FundamentalScore],
    watchlist_tickers: List[str],
) -> Tuple[List[FundamentalScore], List[str]]:
    upper   = {t.strip().upper() for t in watchlist_tickers}
    matched = [s for s in scores if s.symbol in upper]
    skipped = list(upper - {s.symbol for s in matched})
    matched.sort(key=lambda x: x.composite_score)
    return matched, skipped


# ─────────────────────────────────────────────
# Public score label helper
# (used by fundamental_bridge and report renderer)
# ─────────────────────────────────────────────

def score_label(score: float) -> str:
    """Convert a 0-100 score to a human-readable band label."""
    if score >= 75: return "Strong"
    if score >= 60: return "Good"
    if score >= 45: return "Fair"
    if score >= 30: return "Weak"
    return "Poor"


# Keep private alias for internal use and backwards compatibility
_score_label = score_label
