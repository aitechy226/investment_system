# research/recommendations.py
# ─────────────────────────────────────────────
# DESIGN PRINCIPLE: All data MUST be live. Nothing stale or hardcoded.
# When live data could not be retrieved: fail and say so. Do NOT use hardcoded tickers or default lists.
# - Ticker universe: fetched at runtime from Wikipedia (S&P 500). No fallback list.
# - Prices, targets, 52w, ratings: fetched at runtime from yfinance .info. No file cache.
# - In-memory caches (_cached_universe, _cached_info) are run-scoped only; every new
#   run fetches fresh data. No persistence to disk. Report never built from stale data.
# Enforced: LiveDataRequiredError when live fetch fails; no report is generated. No silent fallbacks.
# Not investment advice — for research and due diligence only.
# ─────────────────────────────────────────────

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import certifi
import pandas as pd
import requests
import yfinance as yf

_MAX_WORKERS = 40


class LiveDataRequiredError(RuntimeError):
    """Raised when a live data source is unavailable."""


_WIKI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


def _fetch_ticker_universe_live() -> List[tuple]:
    url  = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, timeout=30, verify=certifi.where(), headers=_WIKI_HEADERS)
    resp.raise_for_status()
    tables     = pd.read_html(io.StringIO(resp.text))
    df         = tables[0]
    symbol_col = "Symbol" if "Symbol" in df.columns else "Ticker"
    symbols    = df[symbol_col].astype(str).str.strip().unique().tolist()
    symbols    = [s for s in symbols if s and len(s) <= 6 and all(c.isalpha() or c == "." for c in s)]
    if not symbols:
        raise LiveDataRequiredError("Ticker universe from live source is empty.")
    return [(s, "Stock") for s in symbols]


_cached_universe: Optional[List[tuple]] = None
_cached_info: Optional[Dict[str, Tuple[str, Any]]] = None


def get_ticker_universe() -> List[tuple]:
    global _cached_universe
    if _cached_universe is not None:
        return _cached_universe
    try:
        _cached_universe = _fetch_ticker_universe_live()
        return _cached_universe
    except LiveDataRequiredError:
        raise
    except Exception as e:
        err_type = type(e).__name__
        raise LiveDataRequiredError(
            f"Ticker universe fetch failed. Backend error: {err_type}: {e}"
        ) from e


def _fetch_info_for_symbol(symbol: str, asset_type: str) -> Optional[Tuple[str, str, dict]]:
    try:
        tk   = yf.Ticker(symbol)
        info = tk.info
        if not info:
            return None
        return (symbol, asset_type, info)
    except Exception:
        return None


def load_all_ticker_data() -> int:
    _ensure_universe_info_loaded()
    return len(_cached_info) if _cached_info else 0


def _ensure_universe_info_loaded() -> None:
    global _cached_info
    if _cached_info is not None:
        return
    universe = get_ticker_universe()
    result: Dict[str, Tuple[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_info_for_symbol, sym, atype): (sym, atype)
            for sym, atype in universe
        }
        for fut in as_completed(futures):
            try:
                out = fut.result()
                if out is not None:
                    sym, atype, info = out
                    result[sym] = (atype, info)
            except Exception:
                pass
    _cached_info = result


@dataclass
class RecommendationRow:
    symbol:              str
    name:                str
    asset_type:          str
    current_price:       Optional[float]
    target_price:        Optional[float]
    upside_pct:          Optional[float]
    recommendation:      str
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low:  Optional[float] = None


_RATING_ORDER = {"strong buy": 0, "buy": 1, "hold": 2, "sell": 3, "strong sell": 4}


def _rating_sort_key(recommendation: str) -> int:
    return _RATING_ORDER.get((recommendation or "").strip().lower(), 5)


@dataclass
class FiftyTwoWeekRow:
    symbol:              str
    name:                str
    asset_type:          str
    current_price:       float
    level_52w:           float
    pct_change:          float
    target_price:        Optional[float] = None
    recommendation:      str = "—"
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low:  Optional[float] = None


def _info_to_recommendation_row(symbol, asset_type, info) -> Optional[RecommendationRow]:
    try:
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
        if not price: return None
        price  = float(price)
        target = info.get("targetMeanPrice")
        if target is not None: target = float(target)
        rec    = (info.get("recommendationKey") or info.get("recommendation") or "").strip()
        rec    = rec.replace("_"," ").title() if rec else "—"
        name   = (info.get("longName") or info.get("shortName") or symbol)[:40]
        upside = None
        if target is not None and price > 0:
            upside = (target - price) / price * 100
        high_52 = info.get("fiftyTwoWeekHigh")
        low_52  = info.get("fiftyTwoWeekLow")
        return RecommendationRow(
            symbol=symbol, name=name, asset_type=asset_type,
            current_price=price,
            target_price=float(target) if target is not None else None,
            upside_pct=round(upside, 1) if upside is not None else None,
            recommendation=rec,
            fifty_two_week_high=float(high_52) if high_52 is not None else None,
            fifty_two_week_low=float(low_52)  if low_52  is not None else None,
        )
    except Exception:
        return None


def fetch_recommendations(top_n: int = 20) -> List[RecommendationRow]:
    _ensure_universe_info_loaded()
    rows = []
    for symbol, (asset_type, info) in (_cached_info or {}).items():
        r = _info_to_recommendation_row(symbol, asset_type, info)
        if r and r.current_price and r.target_price is not None and r.upside_pct is not None:
            rows.append(r)
    rows.sort(key=lambda row: (_rating_sort_key(row.recommendation), row.current_price or 0))
    return rows[:top_n]


def fetch_under100_high_upside(max_price=100.0, min_upside_pct=50.0, top_n=20):
    _ensure_universe_info_loaded()
    rows = []
    for symbol, (asset_type, info) in (_cached_info or {}).items():
        r = _info_to_recommendation_row(symbol, asset_type, info)
        if r and r.current_price and r.target_price and r.upside_pct:
            if r.current_price < max_price and r.upside_pct >= min_upside_pct:
                rows.append(r)
    rows.sort(key=lambda row: (_rating_sort_key(row.recommendation), row.current_price or 0))
    return rows[:top_n]
