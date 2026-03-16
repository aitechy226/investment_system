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
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from earnings import EarningsInfo, fetch_earnings_date, earnings_flag_text
from data_freshness import TickerFreshness, assess_freshness, freshness_flag_text

# Polygon fallback — optional, enriches Yahoo fields before scoring
# Lives in shared/polygon_client.py; no-op if not configured
try:
    import importlib.util as _ilu
    _shared = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared')
    _spec   = _ilu.spec_from_file_location('polygon_client',
                  os.path.join(_shared, 'polygon_client.py'))
    _poly   = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_poly)
    _enrich_with_polygon = _poly.enrich_with_polygon
    _polygon_available   = _poly.polygon_available
except Exception as _poly_err:
    # Polygon client unavailable — Yahoo Finance used exclusively
    import sys as _sys
    print(
        f"[fundamentals] Polygon client not loaded: {type(_poly_err).__name__}: {_poly_err}. "
        "Yahoo Finance will be used exclusively.",
        file=_sys.stderr
    )
    def _enrich_with_polygon(ticker, info): return info
    def _polygon_available(): return False

# Polygon price history — used for momentum scoring
try:
    _poly_fetch_price_history = _poly.fetch_price_history
except Exception as e:
    import sys as _sys
    print(
        f"[fundamentals] fetch_price_history not available on Polygon client: "
        f"{type(e).__name__}: {e}. Yahoo fallback will be used for momentum.",
        file=_sys.stderr
    )
    def _poly_fetch_price_history(ticker, days=400): return None  # stub

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
    """
    Full quality gate for S&P 500 universe scoring.
    Filters out thinly-covered, micro-cap, and extreme-leverage tickers.
    NOT used for watchlist tickers — see _passes_watchlist_gate().
    """
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


def _passes_watchlist_gate(info: dict, sector: str) -> Tuple[bool, str]:
    """
    Relaxed gate for watchlist tickers.
    You put these tickers there intentionally — only block if we
    genuinely cannot score them (no price data).
    Analyst coverage and market cap filters are not applied.
    """
    price = (_safe(info, "currentPrice") or _safe(info, "regularMarketPrice") or _safe(info, "navPrice"))
    if not price or price <= 0:
        return False, "No valid price — Yahoo Finance may not carry this ticker"
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

def score_momentum(
    info: dict,
    sector: str,
    price_history: Optional[Dict] = None,
) -> Tuple[float, Dict]:
    """
    Score momentum for 1yr+ investors.
    Signal priority:
      1. 12-month real return (double-weighted) — primary
      2. 6-month real return  — medium-term trend
      3. 200-day MA           (double-weighted) — trend confirmation
      4. 50-day MA            — short-term filter
      5. 52-week range pos    — context only
    Signals 1+2 require price_history (Task 0-A);
    falls back to signals 3-5 if unavailable.
    """
    detail, sub_scores = {}, []

    price = (_safe(info, "currentPrice") or _safe(info, "regularMarketPrice") or _safe(info, "navPrice"))
    if not price:
        return 0.0, {"error": "no price"}

    # ── Signal 1: 12-month real return (double-weighted) ──────────────
    if price_history:
        ret_12m = price_history.get("return_12m") or price_history.get("return_available")
        if ret_12m is not None:
            s = _score_linear(ret_12m, -30, 50)
            sub_scores.extend([s, s])   # double weight
            detail["return_12m_pct"]   = round(ret_12m, 1)
            detail["return_12m_score"] = round(s, 1)
            detail["return_source"]    = "12m" if "return_12m" in price_history else "available_history"

    # ── Signal 2: 6-month real return ─────────────────────────────────
    if price_history:
        ret_6m = price_history.get("return_6m")
        if ret_6m is not None:
            s = _score_linear(ret_6m, -20, 30)
            sub_scores.append(s)
            detail["return_6m_pct"]   = round(ret_6m, 1)
            detail["return_6m_score"] = round(s, 1)

    # ── Signal 3: 200-day MA (double-weighted) ─────────────────────────
    ma200 = _safe(info, "twoHundredDayAverage")
    if ma200 and ma200 > 0:
        pct = (price - ma200) / ma200 * 100
        s   = _score_linear(pct, -30, 30)
        sub_scores.extend([s, s])
        detail["pct_vs_200d_ma"] = round(pct, 1)
        detail["ma200_score"]    = round(s, 1)

    # ── Signal 4: 50-day MA ────────────────────────────────────────────
    ma50 = _safe(info, "fiftyDayAverage")
    if ma50 and ma50 > 0:
        pct = (price - ma50) / ma50 * 100
        s   = _score_linear(pct, -20, 20)
        sub_scores.append(s)
        detail["pct_vs_50d_ma"] = round(pct, 1)
        detail["ma50_score"]    = round(s, 1)

    # ── Signal 5: 52-week range position (context) ────────────────────
    low_52  = _safe(info, "fiftyTwoWeekLow")
    high_52 = _safe(info, "fiftyTwoWeekHigh")
    if low_52 and high_52 and low_52 > 0 and (high_52 - low_52) > 0:
        pos = (price - low_52) / (high_52 - low_52) * 100
        s   = max(0, min(100, 20 + pos * 0.6))
        sub_scores.append(s)
        detail["position_in_52w_range_pct"] = round(pos, 1)
        detail["range_position_score"]      = round(s, 1)

    score = sum(sub_scores) / len(sub_scores) if sub_scores else 0.0
    detail["signals_used"]     = len(sub_scores)
    detail["used_real_returns"] = bool(
        price_history and ("return_12m" in price_history or "return_6m" in price_history)
    )
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


# ─────────────────────────────────────────────
# Task 0-A: Real price history for momentum
# ─────────────────────────────────────────────

# Run-scoped cache: symbol → price history dict
_price_history_cache: Dict[str, Optional[Dict]] = {}


def _fetch_price_history(symbol: str) -> Optional[Dict]:
    """
    Fetch 13 months of daily closes for real momentum calculations.
    Returns dict with return_6m and/or return_12m, or None on failure.
    Cached per-run to avoid duplicate yfinance history() calls.
    """
    if symbol in _price_history_cache:
        return _price_history_cache[symbol]
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="13mo", interval="1d")
        if hist.empty or len(hist) < 20:
            _price_history_cache[symbol] = None
            return None
        closes  = hist["Close"].dropna()
        current = float(closes.iloc[-1])
        result  = {}
        if len(closes) >= 126:   # ~6 months trading days
            result["return_6m"]  = (current - float(closes.iloc[-126])) / float(closes.iloc[-126]) * 100
        if len(closes) >= 252:   # ~12 months trading days
            result["return_12m"] = (current - float(closes.iloc[-252])) / float(closes.iloc[-252]) * 100
        elif len(closes) > 20:
            result["return_available"] = (current - float(closes.iloc[0])) / float(closes.iloc[0]) * 100
        _price_history_cache[symbol] = result if result else None
        return _price_history_cache[symbol]
    except Exception as e:
        # Price history unavailable — momentum module will fall back to
        # 52-week range proxy. Log so the user knows real returns were not used.
        import sys as _sys
        print(
            f"[fundamentals] Price history fetch failed for {symbol}: "
            f"{type(e).__name__}: {e}. "
            "Momentum will use 52-week range proxy.",
            file=_sys.stderr
        )
        _price_history_cache[symbol] = None
        return None


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

    # Polygon fallback — enrich info for weak Yahoo fields before scoring
    if _polygon_available():
        info = _enrich_with_polygon(symbol, info)

    # Assess data freshness immediately — before scoring
    freshness = assess_freshness(symbol, info)

    # Fetch real price history for momentum (Task 0-A)
    price_history = _fetch_price_history(symbol)

    q_score, q_detail = score_quality_growth(info, sector)
    v_score, v_detail = score_value(info, sector)
    m_score, m_detail = score_momentum(info, sector, price_history)
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


def score_ticker_watchlist(symbol: str, asset_type: str, info: dict) -> FundamentalScore:
    """
    Score a watchlist ticker using the relaxed gate.
    Only requires a valid price — analyst coverage and market cap
    filters are not applied. Used by view_watchlist_flags() for
    tickers that did not make it through the full universe scoring.
    """
    name   = (info.get("longName") or info.get("shortName") or symbol)[:40]
    sector = info.get("sector") or info.get("quoteType") or "Unknown"

    passes, reason = _passes_watchlist_gate(info, sector)
    if not passes:
        return FundamentalScore(
            symbol=symbol, name=name, sector=sector, asset_type=asset_type,
            quality_score=0, value_score=0, momentum_score=0, income_score=0,
            composite_score=0, current_price=None, market_cap_b=None,
            forward_pe=None, div_yield_pct=None, revenue_growth_pct=None,
            debt_to_equity=None, pct_from_52w_high=None,
            skipped=True, skip_reason=reason,
        )

    # Same enrichment and scoring pipeline as score_ticker()
    if _polygon_available():
        info = _enrich_with_polygon(symbol, info)

    freshness     = assess_freshness(symbol, info)
    price_history = _fetch_price_history(symbol)

    q_score, q_detail = score_quality_growth(info, sector)
    v_score, v_detail = score_value(info, sector)
    m_score, m_detail = score_momentum(info, sector, price_history)
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
    Fetch earnings dates for all scored tickers in parallel and attach to each
    FundamentalScore. Also appends earnings flag to score.flags
    if earnings are within the watch window (60 days).

    Called after score_universe() — kept separate so the scoring
    step doesn't slow down if earnings fetch is skipped.
    """
    if not scores:
        return scores
    print(f"  Fetching earnings dates for {len(scores)} tickers (parallel)...")
    max_workers = min(12, len(scores))
    future_to_fs: Dict[Any, FundamentalScore] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for fs in scores:
            fut = executor.submit(_fetch_earnings_for_score, fs)
            future_to_fs[fut] = fs
        earnings_errors = []
        for fut in as_completed(future_to_fs):
            fs = future_to_fs[fut]
            try:
                ei, flag_text = fut.result()
                fs.earnings = ei
                if flag_text and flag_text not in fs.flags:
                    fs.flags.append(flag_text)
            except Exception as e:
                earnings_errors.append(
                    f"{fs.symbol}: {type(e).__name__}: {e}"
                )
    if earnings_errors:
        import sys as _sys
        print(
            f"[fundamentals] Earnings fetch failed for {len(earnings_errors)} ticker(s):\n"
            + "\n".join(f"  • {err}" for err in earnings_errors),
            file=_sys.stderr
        )
    return scores


def _fetch_earnings_for_score(fs: FundamentalScore) -> tuple:
    """Worker: fetch earnings for one score; return (EarningsInfo, flag_text or None)."""
    ei = fetch_earnings_date(fs.symbol)
    flag_text = earnings_flag_text(ei)
    return (ei, flag_text)


# ─────────────────────────────────────────────
# Universe scoring + three views
# ─────────────────────────────────────────────

def score_universe(cached_info: Dict[str, tuple]) -> List[FundamentalScore]:
    """Score all tickers in parallel (CPU-bound on cached info)."""
    if not cached_info:
        return []
    items = [(sym, atype, info) for sym, (atype, info) in cached_info.items()]
    max_workers = min(16, len(items), (os.cpu_count() or 8))
    results: List[FundamentalScore] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(score_ticker, sym, atype, info): sym
            for sym, atype, info in items
        }
        scoring_errors = []
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                fs = fut.result()
                if not fs.skipped:
                    results.append(fs)
            except Exception as e:
                scoring_errors.append(
                    f"{sym}: {type(e).__name__}: {e}"
                )
    if scoring_errors:
        import sys as _sys
        print(
            f"[fundamentals] Scoring failed for {len(scoring_errors)} ticker(s) "
            f"(skipped from results):\n"
            + "\n".join(f"  • {err}" for err in scoring_errors),
            file=_sys.stderr
        )
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
    cached_info: Optional[Dict] = None,
) -> Tuple[List[FundamentalScore], List[str]]:
    """
    Build View C for watchlist tickers.

    First tries to find each ticker in the already-scored universe.
    For tickers not in the universe (failed the full quality gate or
    not in S&P 500), uses cached_info if available (already fetched
    during the universe scan) or falls back to a fresh yfinance fetch.
    Scores them using the relaxed watchlist gate — price required only.

    Returns (scored_list, truly_skipped_list).
    truly_skipped means no valid price was available from Yahoo.
    """
    import yfinance as yf

    upper   = {t.strip().upper() for t in watchlist_tickers}
    matched = [s for s in scores if s.symbol in upper]
    matched_symbols = {s.symbol for s in matched}

    # Tickers not in the scored universe — score with relaxed gate
    missing = upper - matched_symbols
    truly_skipped = []

    for symbol in sorted(missing):
        try:
            # Prefer already-fetched cached data (avoids duplicate yfinance call)
            if cached_info and symbol in cached_info:
                asset_type, info = cached_info[symbol]
            else:
                # Not in cache — fetch fresh (ticker outside S&P 500 universe)
                info = yf.Ticker(symbol).info
                if not info:
                    truly_skipped.append(symbol)
                    continue
                asset_type = info.get("quoteType", "Stock")

            fs = score_ticker_watchlist(symbol, asset_type, info)
            if fs.skipped:
                truly_skipped.append(symbol)
            else:
                fs.flags.insert(0, "ℹ️  Scored with relaxed gate (not in S&P 500 universe or below coverage threshold)")
                matched.append(fs)
        except Exception as e:
            import sys as _sys
            print(
                f"[fundamentals] Watchlist scoring failed for {symbol}: "
                f"{type(e).__name__}: {e}. "
                "Ticker added to skipped list.",
                file=_sys.stderr
            )
            truly_skipped.append(symbol)

    matched.sort(key=lambda x: x.composite_score)
    return matched, truly_skipped


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
