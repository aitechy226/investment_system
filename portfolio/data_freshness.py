# data_freshness.py
# ─────────────────────────────────────────────
# Data freshness assessment for yfinance data.
#
# Two layers tracked independently:
#
#   1. PRICE FRESHNESS
#      Uses regularMarketTime (Unix timestamp).
#      Flags if price data is more than 1 trading
#      day old — suggests a fetch issue or halt.
#
#   2. FUNDAMENTALS FRESHNESS
#      Uses mostRecentQuarter and lastFiscalYearEnd.
#      Flags if the underlying financials are more
#      than 6 months old — scores may be stale.
#
# Both layers produce a FreshnessResult with:
#   - age_days: how old the data is
#   - status: "fresh" | "stale" | "very_stale" | "unknown"
#   - label: human-readable string for display
#   - flag: emoji for report
#
# Copy this file into BOTH folders:
#   portfolio/data_freshness.py
#   research/data_freshness.py
# ─────────────────────────────────────────────

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional


# ── Staleness thresholds ──────────────────────

# Price: warn if last market time > this many days ago
PRICE_STALE_DAYS      = 2    # covers weekends
PRICE_VERY_STALE_DAYS = 5    # a full week — serious problem

# Fundamentals: warn if last quarterly report > this many days ago
FUND_STALE_DAYS       = 180  # ~6 months — one missed quarter
FUND_VERY_STALE_DAYS  = 365  # a full year — very unreliable


@dataclass
class FreshnessResult:
    layer:     str             # "price" or "fundamentals"
    ticker:    str
    age_days:  Optional[int]   # None if unknown
    as_of:     Optional[date]  # the date the data is from
    status:    str             # "fresh" | "stale" | "very_stale" | "unknown"
    label:     str             # human-readable
    flag:      str             # emoji


@dataclass
class TickerFreshness:
    ticker:         str
    price:          FreshnessResult
    fundamentals:   FreshnessResult
    worst_status:   str    # "fresh" | "stale" | "very_stale" | "unknown"
    summary_label:  str    # one-line summary for display
    summary_flag:   str    # worst flag for compact display


# ── Internal helpers ──────────────────────────

def _days_since(ts_unix: Optional[float]) -> Optional[int]:
    """Convert Unix timestamp to days since today."""
    if ts_unix is None:
        return None
    try:
        dt  = datetime.fromtimestamp(float(ts_unix), tz=timezone.utc).date()
        return (date.today() - dt).days
    except Exception:
        return None


def _days_since_date(d: Optional[date]) -> Optional[int]:
    if d is None:
        return None
    try:
        return (date.today() - d).days
    except Exception:
        return None


def _date_from_unix(ts_unix: Optional[float]) -> Optional[date]:
    if ts_unix is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts_unix), tz=timezone.utc).date()
    except Exception:
        return None


def _classify_price(ticker: str, age_days: Optional[int], as_of: Optional[date]) -> FreshnessResult:
    if age_days is None:
        return FreshnessResult(
            layer="price", ticker=ticker, age_days=None, as_of=None,
            status="unknown", label="Price timestamp unavailable", flag="❓"
        )
    date_str = as_of.strftime("%b %d") if as_of else "unknown date"
    if age_days <= PRICE_STALE_DAYS:
        return FreshnessResult(
            layer="price", ticker=ticker, age_days=age_days, as_of=as_of,
            status="fresh",
            label=f"Price current as of {date_str}",
            flag="✅"
        )
    if age_days <= PRICE_VERY_STALE_DAYS:
        return FreshnessResult(
            layer="price", ticker=ticker, age_days=age_days, as_of=as_of,
            status="stale",
            label=f"Price is {age_days} days old ({date_str}) — may be delayed",
            flag="🟡"
        )
    return FreshnessResult(
        layer="price", ticker=ticker, age_days=age_days, as_of=as_of,
        status="very_stale",
        label=f"Price is {age_days} days old ({date_str}) — verify manually",
        flag="🔴"
    )


def _classify_fundamentals(ticker: str, age_days: Optional[int], as_of: Optional[date]) -> FreshnessResult:
    if age_days is None:
        return FreshnessResult(
            layer="fundamentals", ticker=ticker, age_days=None, as_of=None,
            status="unknown",
            label="Fundamentals date unavailable — treat scores with caution",
            flag="❓"
        )
    date_str = as_of.strftime("%b %Y") if as_of else "unknown date"
    if age_days <= FUND_STALE_DAYS:
        return FreshnessResult(
            layer="fundamentals", ticker=ticker, age_days=age_days, as_of=as_of,
            status="fresh",
            label=f"Financials from {date_str} ({age_days}d ago)",
            flag="✅"
        )
    if age_days <= FUND_VERY_STALE_DAYS:
        return FreshnessResult(
            layer="fundamentals", ticker=ticker, age_days=age_days, as_of=as_of,
            status="stale",
            label=f"Financials from {date_str} ({age_days}d ago) — one quarter behind",
            flag="🟡"
        )
    return FreshnessResult(
        layer="fundamentals", ticker=ticker, age_days=age_days, as_of=as_of,
        status="very_stale",
        label=f"Financials from {date_str} ({age_days}d ago) — scores unreliable",
        flag="🔴"
    )


_STATUS_RANK = {"fresh": 0, "unknown": 1, "stale": 2, "very_stale": 3}


def _worst(a: str, b: str) -> str:
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


# ── Public API ────────────────────────────────

def assess_freshness(ticker: str, info: dict) -> TickerFreshness:
    """
    Assess data freshness for a ticker from its yfinance .info dict.
    Returns a TickerFreshness with both price and fundamentals layers.
    """

    # ── Price freshness ───────────────────────
    price_ts  = info.get("regularMarketTime")
    price_age = _days_since(price_ts)
    price_as_of = _date_from_unix(price_ts)
    price_result = _classify_price(ticker, price_age, price_as_of)

    # ── Fundamentals freshness ────────────────
    # Prefer mostRecentQuarter (more frequent), fall back to lastFiscalYearEnd
    fund_ts   = info.get("mostRecentQuarter") or info.get("lastFiscalYearEnd")
    fund_age  = _days_since(fund_ts)
    fund_as_of = _date_from_unix(fund_ts)

    # Also check financialsAsOfDate if available (string format)
    if fund_age is None:
        fao = info.get("financialsAsOfDate")
        if fao:
            try:
                d = date.fromisoformat(str(fao)[:10])
                fund_age   = _days_since_date(d)
                fund_as_of = d
            except Exception:
                pass

    fund_result = _classify_fundamentals(ticker, fund_age, fund_as_of)

    # ── Worst-case summary ────────────────────
    worst = _worst(price_result.status, fund_result.status)

    # Build a one-line summary
    if worst == "fresh":
        summary_label = "Data current"
        summary_flag  = "✅"
    elif worst == "stale":
        # Show which layer is stale
        stale_layers = []
        if price_result.status == "stale":
            stale_layers.append("price")
        if fund_result.status in ("stale", "very_stale"):
            stale_layers.append("fundamentals")
        summary_label = f"Stale: {', '.join(stale_layers)}"
        summary_flag  = "🟡"
    elif worst == "very_stale":
        stale_layers = []
        if price_result.status == "very_stale":
            stale_layers.append("price")
        if fund_result.status == "very_stale":
            stale_layers.append("fundamentals")
        summary_label = f"Very stale: {', '.join(stale_layers)} — verify before acting"
        summary_flag  = "🔴"
    else:
        summary_label = "Data age unknown — treat with caution"
        summary_flag  = "❓"

    return TickerFreshness(
        ticker=ticker,
        price=price_result,
        fundamentals=fund_result,
        worst_status=worst,
        summary_label=summary_label,
        summary_flag=summary_flag,
    )


def freshness_flag_text(tf: TickerFreshness) -> Optional[str]:
    """
    Return a report flag string if data is stale or unknown.
    Returns None if data is fresh — no clutter needed.
    """
    if tf.worst_status == "fresh":
        return None
    lines = []
    if tf.price.status != "fresh":
        lines.append(f"{tf.price.flag}  {tf.price.label}")
    if tf.fundamentals.status != "fresh":
        lines.append(f"{tf.fundamentals.flag}  {tf.fundamentals.label}")
    return "\n".join(lines) if lines else None
