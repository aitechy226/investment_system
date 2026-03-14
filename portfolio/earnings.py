# earnings.py
# ─────────────────────────────────────────────
# Earnings date fetching and classification.
# Used by both portfolio/ and research/.
#
# Copy this file into BOTH folders:
#   portfolio/earnings.py
#   research/earnings.py
#
# yfinance provides earnings dates via two routes:
#   1. info["earningsTimestamp"]     — next earnings Unix timestamp
#   2. info["earningsDate"]          — list, sometimes available
#   3. tk.calendar                   — most reliable, returns DataFrame
#
# We try all three in order and take the first
# valid future date we find.
# ─────────────────────────────────────────────

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import yfinance as yf


# ── Urgency windows ───────────────────────────
EARNINGS_CRITICAL_DAYS = 7    # RED flag  — earnings within 7 days
EARNINGS_WARNING_DAYS  = 30   # AMBER flag — earnings within 30 days
EARNINGS_WATCH_DAYS    = 60   # BLUE note  — earnings within 60 days


@dataclass
class EarningsInfo:
    ticker:            str
    next_earnings_date: Optional[date]   # None if unknown
    days_until:         Optional[int]    # None if unknown or past
    urgency:            str              # "critical" | "warning" | "watch" | "clear" | "unknown"
    label:              str              # human-readable string for display
    flag:               str              # emoji flag for report


def fetch_earnings_date(ticker: str) -> EarningsInfo:
    """
    Fetch the next earnings date for a ticker.
    Tries three yfinance routes in order.
    Returns EarningsInfo with urgency classification.
    """
    next_date: Optional[date] = None

    try:
        tk   = yf.Ticker(ticker)
        info = tk.info
        today = date.today()

        # ── Route 1: tk.calendar ─────────────────
        # Most reliable — returns a dict with "Earnings Date"
        try:
            cal = tk.calendar
            if cal is not None and not cal.empty:
                # calendar is a DataFrame; "Earnings Date" is a column
                if "Earnings Date" in cal.columns:
                    for val in cal["Earnings Date"]:
                        if val is None:
                            continue
                        try:
                            d = val.date() if hasattr(val, "date") else val
                            if d >= today:
                                next_date = d
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        # ── Route 2: info["earningsTimestamp"] ───
        if next_date is None:
            ts = info.get("earningsTimestamp")
            if ts is not None:
                try:
                    d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
                    if d >= today:
                        next_date = d
                except Exception:
                    pass

        # ── Route 3: info["earningsDate"] list ───
        if next_date is None:
            ed_list = info.get("earningsDate")
            if ed_list:
                if not isinstance(ed_list, list):
                    ed_list = [ed_list]
                for val in ed_list:
                    try:
                        if isinstance(val, (int, float)):
                            d = datetime.fromtimestamp(int(val), tz=timezone.utc).date()
                        elif hasattr(val, "date"):
                            d = val.date()
                        else:
                            d = date.fromisoformat(str(val)[:10])
                        if d >= today:
                            next_date = d
                            break
                    except Exception:
                        continue

    except Exception:
        pass

    return _classify(ticker, next_date)


def _classify(ticker: str, next_date: Optional[date]) -> EarningsInfo:
    """Classify the earnings date into an urgency tier."""
    today = date.today()

    if next_date is None:
        return EarningsInfo(
            ticker=ticker,
            next_earnings_date=None,
            days_until=None,
            urgency="unknown",
            label="Earnings date unknown",
            flag="❓",
        )

    days = (next_date - today).days

    if days < 0:
        # Date is in the past — stale data
        return EarningsInfo(
            ticker=ticker,
            next_earnings_date=next_date,
            days_until=None,
            urgency="unknown",
            label=f"Last known earnings: {next_date.strftime('%b %d')} (may be stale)",
            flag="❓",
        )

    date_str = next_date.strftime("%b %d, %Y")

    if days <= EARNINGS_CRITICAL_DAYS:
        return EarningsInfo(
            ticker=ticker,
            next_earnings_date=next_date,
            days_until=days,
            urgency="critical",
            label=f"Earnings in {days}d — {date_str}",
            flag="🔴",
        )
    if days <= EARNINGS_WARNING_DAYS:
        return EarningsInfo(
            ticker=ticker,
            next_earnings_date=next_date,
            days_until=days,
            urgency="warning",
            label=f"Earnings in {days}d — {date_str}",
            flag="🟡",
        )
    if days <= EARNINGS_WATCH_DAYS:
        return EarningsInfo(
            ticker=ticker,
            next_earnings_date=next_date,
            days_until=days,
            urgency="watch",
            label=f"Earnings in {days}d — {date_str}",
            flag="🔵",
        )

    return EarningsInfo(
        ticker=ticker,
        next_earnings_date=next_date,
        days_until=days,
        urgency="clear",
        label=f"Next earnings: {date_str} ({days}d away)",
        flag="✔️",
    )


def fetch_earnings_batch(tickers: list[str]) -> dict[str, EarningsInfo]:
    """
    Fetch earnings dates for a list of tickers.
    Returns dict: ticker → EarningsInfo.
    Sequential (yfinance calendar doesn't batch well).
    """
    results = {}
    for ticker in tickers:
        results[ticker] = fetch_earnings_date(ticker)
    return results


def earnings_flag_text(info: EarningsInfo) -> Optional[str]:
    """
    Return a report flag string if earnings are within watch window.
    Returns None if earnings are clear (>60 days away) or unknown.
    """
    if info.urgency in ("critical", "warning", "watch"):
        return f"{info.flag}  {info.label}"
    return None
