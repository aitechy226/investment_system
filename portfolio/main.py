#!/usr/bin/env python3
# portfolio/main.py
# ─────────────────────────────────────────────
# Entry point for the Weekly Pulse Report.
#
# Run from the portfolio/ directory:
#   python main.py
#   python main.py --no-llm     (data + PDF only, fast test)
#   python main.py --output my.pdf
# ─────────────────────────────────────────────

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Ensure imports resolve from this folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    DEFAULT_LLM_BACKEND,
    OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    GROK_MODEL,
    LiveDataUnavailableError,
)


def _check_ollama_running():
    """Verify Ollama is reachable before starting agents."""
    import urllib.request
    from config import OLLAMA_BASE_URL, OLLAMA_MODEL
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
    except Exception:
        print(f"\n  ERROR: Cannot reach Ollama at {OLLAMA_BASE_URL}")
        print("  Make sure Ollama is running: https://ollama.com")
        print(f"  Then pull the model: ollama pull {OLLAMA_MODEL}")
        print("  Or use external LLM: python main.py --llm external\n")
        sys.exit(1)


def _check_grok_key():
    """Verify Grok API key is set before starting agents."""
    from config import GROK_API_KEY
    if not GROK_API_KEY or GROK_API_KEY == "YOUR_GROK_API_KEY_HERE":
        print("\n  ERROR: GROK_API_KEY not set.")
        print("  Run: export GROK_API_KEY='xai-...'")
        print("  Or use local LLM: python main.py --llm local\n")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Weekly Portfolio Pulse Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "LLM backends:\n"
            "  local     Ollama running on your machine (default, free)\n"
            "  external  Grok via xAI API (higher quality, costs per token)\n"
            "\nExamples:\n"
            "  python main.py                    # local Ollama, default model\n"
            "  python main.py --llm external     # Grok API\n"
            "  python main.py --no-llm           # data + PDF only, no AI\n"
            "  python main.py -p path/to/positions.csv  # use specific portfolio CSV\n"
        )
    )
    parser.add_argument(
        "--llm",
        type=str,
        default=DEFAULT_LLM_BACKEND,
        choices=["local", "external"],
        help="LLM backend: 'local' (Ollama) or 'external' (Grok). Default: local",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip all LLM agents — data and PDF only (fastest, free)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom PDF output path",
    )
    parser.add_argument(
        "--portfolio",
        "-p",
        type=str,
        default=None,
        help="Path to portfolio CSV (broker export or standard format). Default: config PORTFOLIO_CSV",
    )
    args = parser.parse_args()
    backend = args.llm if not args.no_llm else None

    print("\n" + "═" * 55)
    print("  WEEKLY PULSE REPORT")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  %H:%M')}")
    if args.no_llm:
        print("  LLM: disabled (--no-llm)")
    elif args.llm == "local":
        print(f"  LLM: local Ollama ({OLLAMA_MODEL})")
    else:
        print(f"  LLM: external Grok ({GROK_MODEL})")
    print("═" * 55 + "\n")

    try:
        _run_report(args)
    except LiveDataUnavailableError as e:
        print(f"\nERROR: {e}")
        if e.__cause__:
            cause = e.__cause__
            print(f"Original/backend error ({type(cause).__name__}): {cause}")
        sys.exit(1)


def _run_report(args):
    from config import PORTFOLIO_CSV
    from portfolio import build_portfolio

    # ── Step 1: Load portfolio ────────────────
    csv_path = os.path.abspath(args.portfolio) if args.portfolio else PORTFOLIO_CSV
    print(f"[1/4] Loading portfolio from CSV... ({csv_path})")
    t0 = time.time()

    if not os.path.exists(csv_path):
        print(f"\nERROR: Portfolio file not found: {csv_path}")
        print("Use --portfolio /path/to/your.csv or set PORTFOLIO_CSV in config.py")
        sys.exit(1)

    portfolio = build_portfolio(csv_path)
    print(f"  ✓ {len(portfolio.positions)} positions loaded  "
          f"(${portfolio.total_value:,.0f} total value)  [{time.time()-t0:.1f}s]")

    # ── Step 2: Fetch macro data ──────────────
    print("[2/4] Fetching macro market data...")
    t1 = time.time()
    from macro import fetch_macro_snapshot
    macro = fetch_macro_snapshot()
    print(f"  ✓ Macro snapshot ready  [{time.time()-t1:.1f}s]")

    # ── Step 3: Run LLM agents ────────────────
    messages = []
    if args.no_llm:
        print("[3/4] Skipping LLM agents (--no-llm flag set)")
    else:
        # Validate backend availability before spending time on agents
        if args.llm == "local":
            _check_ollama_running()
        elif args.llm == "external":
            _check_grok_key()
        print(f"[3/4] Running AI analysis agents ({args.llm} LLM)...")
        t2 = time.time()
        from langchain_core.messages import HumanMessage
        from agents import (
            health_agent, macro_agent, risk_agent, synthesis_agent,
            fundamentals_node, verifier_agent, _fmt_portfolio, _fmt_macro,
        )

        portfolio_summary = _fmt_portfolio(portfolio)
        macro_summary     = _fmt_macro(macro)

        state = {
            "messages":             [HumanMessage(content="Run weekly pulse")],
            "portfolio":            portfolio,
            "macro":                macro,
            "portfolio_summary":    portfolio_summary,
            "macro_summary":        macro_summary,
            "fundamentals_summary": "",
            "fundamentals_risk":    "",
            "verification_report":  None,
            "llm_backend":          args.llm,
        }

        print("  → Fundamentals scoring...")
        from agents import fundamentals_node
        result = fundamentals_node(state)
        state["fundamentals_summary"] = result["fundamentals_summary"]
        state["fundamentals_risk"]    = result["fundamentals_risk"]

        # Run health, macro, risk agents in parallel (independent of each other)
        print("  → Health / Macro / Risk agents (parallel)...")
        with ThreadPoolExecutor(max_workers=3) as executor:
            f_health = executor.submit(health_agent, state)
            f_macro  = executor.submit(macro_agent, state)
            f_risk   = executor.submit(risk_agent, state)
            for fut in as_completed([f_health, f_macro, f_risk]):
                result = fut.result()
                state["messages"] += result["messages"]

        print("  → Synthesis agent...")
        result = synthesis_agent(state)
        state["messages"] += result["messages"]

        print("  → Verifier agent...")
        from agents import verifier_agent
        result = verifier_agent(state)
        state["messages"]          += result["messages"]
        state["verification_report"] = result["verification_report"]

        messages = state["messages"]
        print(f"  ✓ AI analysis complete  [{time.time()-t2:.1f}s]")

    # ── Step 4: Generate PDF ──────────────────
    print("[4/4] Generating PDF report...")
    t3 = time.time()
    from report import generate_pdf
    verification_report = state.get("verification_report") if not args.no_llm else None
    output_path = generate_pdf(
        portfolio, macro, messages,
        output_path=args.output,
        verification_report=verification_report,
    )
    print(f"  ✓ Report saved: {output_path}  [{time.time()-t3:.1f}s]")

    print("\n" + "═" * 55)
    print(f"  DONE — {output_path}")
    print("═" * 55 + "\n")


if __name__ == "__main__":
    main()
