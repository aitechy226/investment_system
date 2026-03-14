#!/usr/bin/env python3
# research/run_fundamentals.py
# ─────────────────────────────────────────────
# Standalone runner for the Fundamental
# Scoring Report. No dependency on the
# portfolio/ folder — fully self-contained.
#
# Run from the research/ directory:
#   python run_fundamentals.py
#   python run_fundamentals.py --top 30
#   python run_fundamentals.py --watchlist TICKER1,TICKER2,TICKER3
#   python run_fundamentals.py --output my_report.pdf
# ─────────────────────────────────────────────

import argparse
import os
import sys
import time
from datetime import datetime

# Ensure all imports resolve from research/ folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def main():
    parser = argparse.ArgumentParser(description="Fundamental Scoring Report")
    parser.add_argument("--top",          type=int,   default=25,   help="Top N for composite list (default 25)")
    parser.add_argument("--strategy-top", type=int,   default=15,   help="Top N per strategy (default 15)")
    parser.add_argument("--min-score",    type=float, default=45.0, help="Min composite score for View A (default 45)")
    parser.add_argument("--output",       type=str,   default=None, help="PDF output path")
    parser.add_argument("--watchlist",    type=str,   default=None,
                        help="Comma-separated tickers for View C (e.g. TICKER1,TICKER2)")
    args = parser.parse_args()

    print("\n" + "═" * 60)
    print("  FUNDAMENTAL SCORING REPORT")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  %H:%M')}")
    print("═" * 60 + "\n")

    # ── Step 1: Fetch S&P 500 universe ────────
    print("[1/6] Fetching S&P 500 ticker universe from Wikipedia...")
    t0 = time.time()
    from recommendations import get_ticker_universe, LiveDataRequiredError
    try:
        universe = get_ticker_universe()
        print(f"  ✓ {len(universe)} tickers loaded  [{time.time()-t0:.1f}s]")
    except LiveDataRequiredError as e:
        print(f"\n  ERROR: {e}")
        if getattr(e, "__cause__", None):
            c = e.__cause__
            print(f"  Backend error ({type(c).__name__}): {c}")
        sys.exit(1)

    # ── Step 2: Parallel fetch all ticker data ─
    print("[2/6] Fetching live fundamentals for all tickers (parallel, ~3-5 min)...")
    t1 = time.time()
    from recommendations import load_all_ticker_data
    import recommendations as rec_module
    load_all_ticker_data()
    cached = rec_module._cached_info or {}
    print(f"  ✓ {len(cached)} tickers with live data  [{time.time()-t1:.1f}s]")

    # ── Step 3: Score all tickers (parallel) ───
    print("[3/6] Scoring tickers across 4 fundamental modules (parallel)...")
    t2 = time.time()
    from fundamentals import (
        score_universe,
        enrich_with_earnings,
        view_composite_ranked,
        view_by_strategy,
        view_watchlist_flags,
    )
    all_scores = score_universe(cached)
    print(f"  ✓ {len(all_scores)} tickers scored  [{time.time()-t2:.1f}s]")

    # ── Step 3b: Earnings dates ───────────────
    # Fetched for watchlist tickers only (fast).
    # Full universe enrichment would take ~30 min.
    # Watchlist enrichment happens after view_c below.

    # ── Step 4: Build three views ─────────────
    print("[4/6] Building output views...")

    view_a = view_composite_ranked(all_scores, top_n=args.top, min_composite=args.min_score)
    print(f"  → View A (composite): {len(view_a)} ideas")

    view_b = view_by_strategy(all_scores, top_n=args.strategy_top)
    for strategy, items in view_b.items():
        print(f"  → View B [{strategy}]: {len(items)} ideas")

    # View C: use --watchlist arg if provided, otherwise prompt
    watchlist = []
    if args.watchlist:
        watchlist = [t.strip().upper() for t in args.watchlist.split(",") if t.strip()]
        print(f"  → View C watchlist: {watchlist}")
    else:
        print("  → View C: no --watchlist provided, skipping holdings assessment")

    view_c_scores, skipped = view_watchlist_flags(all_scores, watchlist)
    if watchlist:
        print(f"  → View C: {len(view_c_scores)} holdings scored, {len(skipped)} skipped")

    # ── Step 5: Enrich watchlist with earnings ─
    print("[5/6] Fetching earnings dates for watchlist...")
    t5 = time.time()
    if view_c_scores:
        enrich_with_earnings(view_c_scores)
        print(f"  ✓ Earnings dates fetched  [{time.time()-t5:.1f}s]")
    else:
        print("  → Skipped (no watchlist)")

    # ── Step 6: Generate PDF ──────────────────
    print("[6/6] Generating PDF...")
    t4 = time.time()
    from fundamentals_report import generate_fundamentals_pdf
    output_path = generate_fundamentals_pdf(
        view_a_scores=view_a,
        view_b_dict=view_b,
        view_c_scores=view_c_scores,
        skipped_symbols=skipped,
        output_path=args.output,
        reports_dir=REPORTS_DIR,
    )
    print(f"  ✓ Report saved: {output_path}  [{time.time()-t4:.1f}s]")

    print("\n" + "═" * 60)
    print(f"  DONE — {output_path}")
    print("═" * 60 + "\n")

    # Terminal summary
    print("TOP 10 COMPOSITE SCORES:")
    print(f"  {'#':<3} {'Ticker':<8} {'Company':<28} {'Quality':>7} {'Value':>6} {'Mom':>5} {'Inc':>5} {'Score':>6}")
    print("  " + "-" * 70)
    for i, s in enumerate(view_a[:10], 1):
        print(
            f"  {i:<3} {s.symbol:<8} {s.name[:27]:<28} "
            f"{s.quality_score:>7.1f} {s.value_score:>6.1f} "
            f"{s.momentum_score:>5.1f} {s.income_score:>5.1f} "
            f"{s.composite_score:>6.1f}"
        )
    print()


if __name__ == "__main__":
    main()
