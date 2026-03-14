# portfolio/macro.py
# ─────────────────────────────────────────────
# Fetches macro market context from LIVE data only.
# Ticker lists are read from CSV (macro_indices.csv, sector_etfs.csv);
# no hardcoded symbols. All price/performance data fetched at runtime.
# ─────────────────────────────────────────────

from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Tuple

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import MACRO_INDICES_CSV, SECTOR_ETFS_CSV, LiveDataUnavailableError


def _load_ticker_list(csv_path: str, required_for: str) -> List[Tuple[str, str]]:
    """Load symbol,label pairs from CSV. Fails if file missing or empty — no default lists."""
    if not os.path.isfile(csv_path):
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved: {required_for} config file missing. "
            f"Expected path: {csv_path}. "
            "Do not use hardcoded tickers or default lists."
        )
    out = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = (row.get("symbol") or "").strip()
            label = (row.get("label") or sym).strip()
            if sym:
                out.append((sym, label))
    if not out:
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved: {required_for} config file is empty (no symbol,label rows). "
            f"File: {csv_path}. "
            "Do not use hardcoded tickers or default lists."
        )
    return out


def get_macro_indices() -> List[Tuple[str, str]]:
    """Return [(symbol, label), ...] for macro indices (from CSV). Fails if missing/empty."""
    return _load_ticker_list(MACRO_INDICES_CSV, "macro indices")


def get_sector_etfs() -> List[Tuple[str, str]]:
    """Return [(symbol, label), ...] for sector ETFs (from CSV). Fails if missing/empty."""
    return _load_ticker_list(SECTOR_ETFS_CSV, "sector ETFs")


@dataclass
class MacroTicker:
    symbol:           str
    label:            str
    current_price:    Optional[float]
    week_change_pct:  Optional[float]
    month_change_pct: Optional[float]
    year_change_pct:  Optional[float]
    fifty_two_wk_high: Optional[float]
    fifty_two_wk_low:  Optional[float]


@dataclass
class MacroSnapshot:
    indices:             List[MacroTicker]
    sectors:             List[MacroTicker]
    vix_level:           Optional[float]
    vix_interpretation:  str
    yield_10yr:          Optional[float]
    as_of:               str


def _fetch_ticker_data(symbol: str, label: str) -> MacroTicker:
    """Fetch live data for one macro/sector ticker. Fails if data could not be retrieved."""
    try:
        tk   = yf.Ticker(symbol)
        info = tk.info
        hist = tk.history(period="1y", interval="1d")

        current_price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
        )
        if not current_price and not hist.empty:
            current_price = float(hist["Close"].iloc[-1])

        week_chg = month_chg = year_chg = None
        if not hist.empty and current_price:
            closes = hist["Close"].dropna()
            if len(closes) >= 5:
                week_chg  = (current_price - float(closes.iloc[-5]))  / float(closes.iloc[-5])  * 100
            if len(closes) >= 21:
                month_chg = (current_price - float(closes.iloc[-21])) / float(closes.iloc[-21]) * 100
            if len(closes) >= 252:
                year_chg  = (current_price - float(closes.iloc[-252]))/ float(closes.iloc[-252])* 100
            elif len(closes) > 1:
                year_chg  = (current_price - float(closes.iloc[0]))   / float(closes.iloc[0])   * 100

        return MacroTicker(
            symbol=symbol, label=label,
            current_price=current_price,
            week_change_pct=week_chg,
            month_change_pct=month_chg,
            year_change_pct=year_chg,
            fifty_two_wk_high=info.get("fiftyTwoWeekHigh"),
            fifty_two_wk_low=info.get("fiftyTwoWeekLow"),
        )
    except Exception as e:
        err_type = type(e).__name__
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved for {symbol}. "
            f"Backend error: {err_type}: {e}. "
            "Do not use hardcoded tickers or default lists."
        ) from e


def _interpret_vix(vix: Optional[float]) -> str:
    if vix is None:           return "VIX data unavailable."
    if vix < 15:              return f"VIX at {vix:.1f} — market is calm, low fear. Complacency risk."
    if vix < 20:              return f"VIX at {vix:.1f} — normal volatility. No alarm signals."
    if vix < 30:              return f"VIX at {vix:.1f} — elevated anxiety. Expect choppy sessions."
    if vix < 40:              return f"VIX at {vix:.1f} — high fear. Possible buying opportunity for disciplined investors."
    return                           f"VIX at {vix:.1f} — extreme fear. Proceed with caution. Capital preservation priority."


def fetch_macro_snapshot() -> MacroSnapshot:
    from datetime import datetime
    macro_list = list(get_macro_indices())
    sector_list = list(get_sector_etfs())
    all_tasks = [(sym, label, "macro") for sym, label in macro_list] + [
        (sym, label, "sector") for sym, label in sector_list
    ]
    results = {}
    max_workers = min(12, max(len(all_tasks), 2))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_ticker_data, sym, label): (sym, kind)
            for sym, label, kind in all_tasks
        }
        for fut in as_completed(futures):
            sym, kind = futures[fut]
            results[(sym, kind)] = fut.result()

    indices = []
    vix_level = None
    for symbol, label in macro_list:
        mt = results[(symbol, "macro")]
        if symbol == "VIX":
            vix_level = mt.current_price
        else:
            indices.append(mt)

    sectors = [results[(sym, "sector")] for sym, label in sector_list]
    sectors.sort(
        key=lambda x: x.week_change_pct if x.week_change_pct is not None else -999,
        reverse=True,
    )

    return MacroSnapshot(
        indices=indices,
        sectors=sectors,
        vix_level=vix_level,
        vix_interpretation=_interpret_vix(vix_level),
        yield_10yr=None,
        as_of=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
