# portfolio.py
# ─────────────────────────────────────────────
# Live data only: loads positions from CSV (no hardcoded tickers) and
# enriches every run with live price/fundamental data from Yahoo Finance.
# ─────────────────────────────────────────────

from __future__ import annotations

import csv
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LiveDataUnavailableError
from earnings import EarningsInfo, fetch_earnings_date
from data_freshness import TickerFreshness, assess_freshness, freshness_flag_text


@dataclass
class Position:
    ticker:        str
    shares:        float
    avg_cost:      float
    purchase_date: str
    sector:        str
    asset_class:   str
    notes:         str

    # enriched by fetch_live_data()
    current_price:    Optional[float] = None
    week_change_pct:  Optional[float] = None
    market_value:     Optional[float] = None
    gain_loss_pct:    Optional[float] = None
    trailing_pe:      Optional[float] = None
    forward_pe:       Optional[float] = None
    dividend_yield:   Optional[float] = None
    week_high:        Optional[float] = None
    week_low:         Optional[float] = None
    fifty_two_wk_high: Optional[float] = None
    fifty_two_wk_low:  Optional[float] = None
    analyst_target:   Optional[float] = None
    company_name:     Optional[str]   = None
    fetch_error:      Optional[str]   = None

    # Earnings awareness
    earnings:         Optional[object] = None

    # Data freshness
    freshness:        Optional[object] = None


@dataclass
class Portfolio:
    positions:      List[Position]
    total_cost:     float = 0.0
    total_value:    float = 0.0
    total_gain_pct: float = 0.0
    as_of:          str   = ""

    # sector → % of portfolio
    sector_weights: Dict[str, float] = field(default_factory=dict)
    # asset_class → % of portfolio
    class_weights:  Dict[str, float] = field(default_factory=dict)


def _parse_broker_number(s: str) -> Optional[float]:
    """Parse broker CSV number e.g. '$139.26' or '$6,963.20' or '50'."""
    if not s or s.strip() in ("--", ""):
        return None
    s = s.replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def load_portfolio(csv_path: str) -> List[Position]:
    """
    Read the CSV file and return a list of Position objects.
    Supports:
    - Standard format: ticker, shares, avg_cost, purchase_date, sector, asset_class, notes
    - Broker format (e.g. Individual-Positions-*.csv): Symbol, Qty (Quantity), Cost/Share, Asset Type, etc.
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        first_line = f.readline()
        rest = f.read()

    # Broker export often has a comment line first; header contains "Symbol" and "Qty"
    if "ticker" in first_line:
        return _load_portfolio_standard(io.StringIO(first_line + rest))
    # Broker format: skip comment line if present so header is first line of content
    content = rest if "Symbol" not in first_line else first_line + rest
    return _load_portfolio_broker(io.StringIO(content))


def _load_portfolio_standard(f: io.StringIO) -> List[Position]:
    """Parse standard portfolio CSV (ticker, shares, avg_cost, ...)."""
    positions = []
    reader = csv.DictReader(f)
    for row in reader:
        positions.append(Position(
            ticker=row["ticker"].strip().upper(),
            shares=float(row["shares"]),
            avg_cost=float(row["avg_cost"]),
            purchase_date=row["purchase_date"].strip(),
            sector=row["sector"].strip(),
            asset_class=row["asset_class"].strip(),
            notes=row.get("notes", "").strip(),
        ))
    return positions


def _load_portfolio_broker(f: io.StringIO) -> List[Position]:
    """Parse broker export CSV (Symbol, Qty (Quantity), Cost/Share, Asset Type, ...)."""
    positions = []
    reader = csv.DictReader(f)
    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        asset_type = (row.get("Asset Type") or "").strip()
        if not symbol or symbol in ("Account Total", "Cash & Cash Investments"):
            continue
        if asset_type not in ("Equity", "ETF"):
            continue
        qty = _parse_broker_number(row.get("Qty (Quantity)", ""))
        cost_share = _parse_broker_number(row.get("Cost/Share", ""))
        if qty is None or cost_share is None or qty <= 0:
            continue
        positions.append(Position(
            ticker=symbol.upper(),
            shares=float(int(qty)) if qty == int(qty) else float(qty),
            avg_cost=cost_share,
            purchase_date="",  # not in broker export
            sector="Unknown",
            asset_class=asset_type,
            notes="",
        ))
    return positions


def _fetch_info_for_position(args: Tuple[int, Position]) -> Tuple[int, Optional[dict], Optional[str]]:
    """Worker: fetch yfinance info for one position. Returns (index, info, error)."""
    i, pos = args
    try:
        info = yf.Ticker(pos.ticker).info
        return (i, info, None)
    except Exception as e:
        return (i, None, str(e))


def fetch_live_data(positions: List[Position]) -> List[Position]:
    """
    Enrich each Position with live market data.
    Batch download + parallel per-ticker info fetch for speed.
    """
    tickers = [p.ticker for p in positions]

    # ── Batch price download (fast) ───────────
    try:
        raw = yf.download(
            tickers,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        err_type = type(e).__name__
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved: batch price download failed. "
            f"Backend error: {err_type}: {e}. "
            "Do not use hardcoded tickers or default lists."
        ) from e

    # ── Per-ticker enrichment in parallel ─────
    max_workers = min(12, max(len(positions), 2))
    results_by_index: Dict[int, Tuple[Optional[dict], Optional[str]]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_info_for_position, (i, p)): i for i, p in enumerate(positions)}
        for fut in as_completed(futures):
            i, info, err = fut.result()
            results_by_index[i] = (info, err)

    for i, pos in enumerate(positions):
        info, err = results_by_index.get(i, (None, "missing"))
        if err or not info:
            pos.fetch_error = err or "no data"
            continue
        pos.company_name   = info.get("longName") or info.get("shortName", pos.ticker)
        # Enrich sector from live data when available (broker CSV has no sector column)
        if info.get("sector"):
            pos.sector = (info.get("sector") or "").strip() or pos.sector
        pos.current_price  = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
        )
        pos.trailing_pe    = info.get("trailingPE")
        pos.forward_pe     = info.get("forwardPE")
        pos.dividend_yield = info.get("dividendYield")
        pos.analyst_target = info.get("targetMeanPrice")
        pos.fifty_two_wk_high = info.get("fiftyTwoWeekHigh")
        pos.fifty_two_wk_low  = info.get("fiftyTwoWeekLow")
        pos.freshness = assess_freshness(pos.ticker, info)

        if raw is not None and pos.current_price:
            try:
                hist = raw["Close"] if len(tickers) == 1 else raw[pos.ticker]["Close"]
                hist = hist.dropna()
                if len(hist) >= 2:
                    start_price = float(hist.iloc[0])
                    end_price   = float(hist.iloc[-1])
                    pos.week_change_pct = (end_price - start_price) / start_price * 100
                    pos.week_high = float(hist.max())
                    pos.week_low  = float(hist.min())
            except Exception:
                pass
        if pos.current_price:
            pos.market_value  = pos.shares * pos.current_price
            pos.gain_loss_pct = (pos.current_price - pos.avg_cost) / pos.avg_cost * 100

    failed = [(p.ticker, p.fetch_error or "no price data") for p in positions if p.fetch_error or p.current_price is None]
    if failed:
        details = "; ".join(f"{t}: {err}" for t, err in failed)
        raise LiveDataUnavailableError(
            f"Live data could not be retrieved. Per-ticker backend errors: {details}. "
            "Do not use hardcoded tickers or default lists."
        )

    # Sector is required for a useful report; Unknown means something went wrong
    unknown_sector = [p.ticker for p in positions if not (p.sector or "").strip() or (p.sector or "").strip().lower() == "unknown"]
    if unknown_sector:
        raise LiveDataUnavailableError(
            f"Sector is Unknown or missing for ticker(s): {', '.join(unknown_sector)}. "
            "The report cannot be generated with valid sector data. "
            "Diagnosis: (1) Broker export CSV has no sector column — use a portfolio CSV that includes 'sector', or ensure the data source returns sector; "
            "(2) The data source (e.g. yfinance) did not return sector for these symbols — check symbol validity, rate limits, or try again later. "
            "Do not use hardcoded tickers or default lists."
        )
    return positions


def fetch_earnings_info(positions: List[Position]) -> List[Position]:
    """Fetch earnings dates for all equity positions in parallel (skip ETFs)."""
    print("  Fetching earnings dates...")
    equity = [(i, p) for i, p in enumerate(positions) if p.asset_class.lower() != "etf"]
    if not equity:
        return positions
    results: Dict[int, object] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(equity))) as executor:
        futures = {executor.submit(fetch_earnings_date, p.ticker): (i, p) for i, p in equity}
        for fut in as_completed(futures):
            i, p = futures[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = None
    for i, p in equity:
        p.earnings = results.get(i)
    return positions


def build_portfolio(csv_path: str) -> Portfolio:
    """Full pipeline: load CSV → fetch live data → compute aggregates."""
    positions = load_portfolio(csv_path)
    positions = fetch_live_data(positions)
    positions = fetch_earnings_info(positions)

    total_cost  = sum(p.shares * p.avg_cost for p in positions)
    total_value = sum(p.market_value for p in positions if p.market_value)

    # Sector and asset class weights
    sector_values: Dict[str, float] = {}
    class_values:  Dict[str, float] = {}
    for p in positions:
        if p.market_value:
            sector_values[p.sector]      = sector_values.get(p.sector, 0)      + p.market_value
            class_values[p.asset_class]  = class_values.get(p.asset_class, 0)  + p.market_value

    sector_weights = {k: v / total_value * 100 for k, v in sector_values.items()} if total_value else {}
    class_weights  = {k: v / total_value * 100 for k, v in class_values.items()}  if total_value else {}

    total_gain_pct = (
        (total_value - total_cost) / total_cost * 100 if total_cost else 0.0
    )

    return Portfolio(
        positions=positions,
        total_cost=total_cost,
        total_value=total_value,
        total_gain_pct=total_gain_pct,
        as_of=datetime.now().strftime("%Y-%m-%d %H:%M"),
        sector_weights=sector_weights,
        class_weights=class_weights,
    )
