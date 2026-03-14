#!/usr/bin/env python3
# diagnose.py
# ─────────────────────────────────────────────
# Pre-flight diagnostic for the investment system.
# Run this before your first real run to catch
# every likely failure point.
#
# Run from the investment_system/ root:
#   python diagnose.py
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed
# ─────────────────────────────────────────────

import os
import sys
import time
import importlib
from datetime import datetime

# ── Colour helpers (no dependencies) ─────────
def _green(s):  return f"\033[92m{s}\033[0m"
def _red(s):    return f"\033[91m{s}\033[0m"
def _amber(s):  return f"\033[93m{s}\033[0m"
def _bold(s):   return f"\033[1m{s}\033[0m"
def _grey(s):   return f"\033[90m{s}\033[0m"

PASS  = _green("  ✅ PASS")
FAIL  = _red("  ❌ FAIL")
WARN  = _amber("  ⚠️  WARN")
INFO  = _grey("  ℹ️  INFO")

_failures = []
_warnings = []


def _check(label: str, fn):
    """Run a check function, print result, record failures."""
    try:
        result = fn()
        if result is True:
            print(f"{PASS}  {label}")
        elif result is False:
            print(f"{FAIL}  {label}")
            _failures.append(label)
        elif isinstance(result, tuple) and len(result) == 2 and result[0] is False:
            print(f"{FAIL}  {label} — {_red(str(result[1]))}")
            _failures.append(label)
        elif isinstance(result, str) and result.startswith("WARN:"):
            print(f"{WARN}  {label} — {result[5:].strip()}")
            _warnings.append(label)
        elif isinstance(result, str):
            print(f"{PASS}  {label} — {_grey(result)}")
        else:
            print(f"{PASS}  {label}")
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        print(f"{FAIL}  {label} — {_red(err_msg)}")
        _failures.append(label)


def _section(title: str):
    print(f"\n{_bold(title)}")
    print("─" * 55)


# ─────────────────────────────────────────────
# 1. Folder structure
# ─────────────────────────────────────────────

def check_folder_structure():
    _section("1. FOLDER STRUCTURE")

    root = os.path.dirname(os.path.abspath(__file__))

    required_dirs = [
        "portfolio",
        "research",
        "portfolio/reports",
        "research/reports",
    ]
    for d in required_dirs:
        path = os.path.join(root, d)
        _check(f"Directory exists: {d}/",
               lambda p=path: os.path.isdir(p) or _mk(p))

    portfolio_files = [
        "main.py", "config.py", "portfolio.py",
        "macro.py", "agents.py", "report.py", "earnings.py",
        "data_freshness.py", "fundamental_bridge.py", "verifier.py",
    ]
    for f in portfolio_files:
        path = os.path.join(root, "portfolio", f)
        _check(f"portfolio/{f}", lambda p=path: os.path.isfile(p))
    # At least one portfolio CSV and macro config CSVs (no hardcoded tickers)
    def _has_portfolio_csv():
        port_dir = os.path.join(root, "portfolio")
        if not os.path.isdir(port_dir):
            return False
        return any(f.endswith(".csv") for f in os.listdir(port_dir))
    _check("portfolio/*.csv (at least one)", _has_portfolio_csv)
    _check("portfolio/macro_indices.csv", lambda: os.path.isfile(os.path.join(root, "portfolio", "macro_indices.csv")))
    _check("portfolio/sector_etfs.csv", lambda: os.path.isfile(os.path.join(root, "portfolio", "sector_etfs.csv")))

    research_files = [
        "run_fundamentals.py", "fundamentals.py", "fundamentals_report.py",
        "recommendations.py", "earnings.py", "data_freshness.py",
    ]
    for f in research_files:
        path = os.path.join(root, "research", f)
        _check(f"research/{f}", lambda p=path: os.path.isfile(p))

    _check("requirements.txt",
           lambda: os.path.isfile(os.path.join(root, "requirements.txt")))


def _mk(path):
    """Create directory and return True."""
    os.makedirs(path, exist_ok=True)
    return True


# ─────────────────────────────────────────────
# 2. Python dependencies
# ─────────────────────────────────────────────

def check_dependencies():
    _section("2. PYTHON DEPENDENCIES")

    packages = {
        "yfinance":          "yfinance",
        "reportlab":         "reportlab",
        "pandas":            "pandas",
        "requests":          "requests",
        "certifi":           "certifi",
        "langchain_core":    "langchain-core",
        "langchain_openai":  "langchain-openai",
        "langgraph":         "langgraph",
    }

    for module, pip_name in packages.items():
        def _imp(m=module, p=pip_name):
            try:
                mod = importlib.import_module(m)
                ver = getattr(mod, "__version__", "unknown version")
                return ver
            except ImportError:
                raise ImportError(f"Not installed. Run: pip install {p}")
        _check(f"import {module}", _imp)


# ─────────────────────────────────────────────
# 3. API key
# ─────────────────────────────────────────────

def check_api_key():
    _section("3. GROK API KEY")

    def _key_set():
        key = os.environ.get("GROK_API_KEY", "")
        if not key or key == "YOUR_GROK_API_KEY_HERE":
            raise ValueError(
                "GROK_API_KEY not set. Run: export GROK_API_KEY='xai-...'"
            )
        if not key.startswith("xai-"):
            return "WARN:Key found but doesn't start with 'xai-' — verify it's correct"
        masked = key[:8] + "..." + key[-4:]
        return f"Key found: {masked}"
    _check("GROK_API_KEY environment variable", _key_set)

    def _config_key():
        root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(root, "portfolio"))
        from config import GROK_API_KEY, GROK_BASE_URL, GROK_MODEL
        if GROK_API_KEY == "YOUR_GROK_API_KEY_HERE":
            return "WARN:config.py still has placeholder key — using env var is preferred"
        return f"Model: {GROK_MODEL}  Base URL: {GROK_BASE_URL}"
    _check("config.py settings", _config_key)


# ─────────────────────────────────────────────
# 4. Portfolio CSV
# ─────────────────────────────────────────────

def check_portfolio_csv(csv_path=None):
    """Validate portfolio CSV (standard or broker format). csv_path defaults to portfolio/portfolio.csv or first .csv in portfolio/."""
    root = os.path.dirname(os.path.abspath(__file__))
    if csv_path is None:
        default = os.path.join(root, "portfolio", "portfolio.csv")
        if os.path.isfile(default):
            csv_path = default
        else:
            port_dir = os.path.join(root, "portfolio")
            csvs = sorted(f for f in os.listdir(port_dir) if f.endswith(".csv")) if os.path.isdir(port_dir) else []
            csv_path = os.path.join(port_dir, csvs[0]) if csvs else default
    else:
        csv_path = os.path.abspath(csv_path)
    label = os.path.basename(csv_path)

    _section("4. PORTFOLIO CSV")
    print(_grey(f"  File: {csv_path}\n"))

    def _csv_exists():
        return os.path.isfile(csv_path)
    _check(f"{label} exists", _csv_exists)

    def _csv_parseable():
        # Use portfolio.load_portfolio so both standard and broker formats are accepted
        port_dir = os.path.join(root, "portfolio")
        sys.path.insert(0, port_dir)
        try:
            from portfolio import load_portfolio
            positions = load_portfolio(csv_path)
        except Exception as e:
            raise ValueError(str(e))
        finally:
            if port_dir in sys.path:
                sys.path.remove(port_dir)
        if not positions:
            return "WARN:No positions loaded (file may be empty or only summary rows)"
        return f"{len(positions)} positions loaded (broker or standard format)"
    _check(f"{label} is valid and parseable", _csv_parseable)

    def _csv_sectors():
        sys.path.insert(0, os.path.join(root, "portfolio"))
        try:
            from portfolio import load_portfolio
            positions = load_portfolio(csv_path)
        except Exception:
            return "Skip (parse failed)"
        finally:
            if os.path.join(root, "portfolio") in sys.path:
                sys.path.remove(os.path.join(root, "portfolio"))
        # Unknown sector is a critical issue — report has no value; diagnose fails so user fixes before run
        unknown = [p.ticker for p in positions if not (p.sector or "").strip() or (p.sector or "").strip().lower() == "unknown"]
        if unknown:
            return (False, f"Sector is Unknown for: {', '.join(unknown)}. Use a portfolio CSV with a 'sector' column, or ensure live data returns sector for these symbols (report will also fail at run time until fixed).")
        valid_sectors = {
            "Technology", "Healthcare", "Financials", "Financial Services",
            "Energy", "Consumer Staples", "Consumer Discretionary",
            "Industrials", "Materials", "Communication Services",
            "Utilities", "Real Estate", "Broad Market",
        }
        issues = [f"{p.ticker}: '{p.sector}'" for p in positions if (p.sector or "").strip() not in valid_sectors]
        if issues:
            return f"WARN:Unrecognised sectors: {'; '.join(issues)}"
        return "Sector values OK"
    _check("No Unknown sectors (required for report)", _csv_sectors)

    def _csv_asset_class():
        sys.path.insert(0, os.path.join(root, "portfolio"))
        try:
            from portfolio import load_portfolio
            positions = load_portfolio(csv_path)
        except Exception:
            return "Skip (parse failed)"
        finally:
            if os.path.join(root, "portfolio") in sys.path:
                sys.path.remove(os.path.join(root, "portfolio"))
        issues = [f"{p.ticker}: '{p.asset_class}'" for p in positions
                  if p.asset_class.strip().lower() not in ("equity", "etf")]
        if issues:
            return f"WARN:asset_class should be 'Equity' or 'ETF': {'; '.join(issues)}"
        return "Asset class values OK"
    _check("asset_class values are Equity or ETF", _csv_asset_class)

    def _csv_holdings_list():
        sys.path.insert(0, os.path.join(root, "portfolio"))
        try:
            from portfolio import load_portfolio
            positions = load_portfolio(csv_path)
        except Exception:
            return "Skip (parse failed)"
        finally:
            if os.path.join(root, "portfolio") in sys.path:
                sys.path.remove(os.path.join(root, "portfolio"))
        tickers = [p.ticker.strip().upper() for p in positions]
        return f"Holdings: {', '.join(sorted(tickers))}" if tickers else "No positions"
    _check("Portfolio holdings listed", _csv_holdings_list)


# ─────────────────────────────────────────────
# 5. Python imports (internal modules)
# ─────────────────────────────────────────────

def check_internal_imports():
    _section("5. INTERNAL MODULE IMPORTS")

    root = os.path.dirname(os.path.abspath(__file__))

    portfolio_modules = [
        "config", "portfolio", "macro", "earnings",
        "data_freshness", "verifier",
    ]
    for mod in portfolio_modules:
        def _imp(m=mod, r=root):
            path = os.path.join(r, "portfolio")
            if path not in sys.path:
                sys.path.insert(0, path)
            importlib.import_module(m)
            return True
        _check(f"portfolio/{mod}.py imports cleanly", _imp)

    research_modules = [
        "recommendations", "fundamentals",
        "earnings", "data_freshness",
    ]
    for mod in research_modules:
        def _imp(m=mod, r=root):
            file_path = os.path.join(r, "research", f"{m}.py")
            unique_name = f"_diag_research_{m}"
            # Remove stale entry if present
            if unique_name in sys.modules:
                del sys.modules[unique_name]
            spec = importlib.util.spec_from_file_location(unique_name, file_path)
            if spec is None:
                raise ImportError(f"Could not load spec for {file_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[unique_name] = module  # register before exec
            spec.loader.exec_module(module)
            return True
        _check(f"research/{mod}.py imports cleanly", _imp)

    def _bridge():
        path = os.path.join(root, "portfolio")
        if path not in sys.path:
            sys.path.insert(0, path)
        import fundamental_bridge
        return True
    _check("portfolio/fundamental_bridge.py (reaches research/)", _bridge)


# ─────────────────────────────────────────────
# 6. Live data — smoke test using portfolio tickers (no hardcoded symbols)
# ─────────────────────────────────────────────

def check_live_data(positions=None):
    """Use first portfolio ticker and first macro index from config files for live checks. No hardcoded tickers."""
    _section("6. LIVE DATA (using portfolio + macro config)")
    root = os.path.dirname(os.path.abspath(__file__))
    port_dir = os.path.join(root, "portfolio")
    probe_ticker = positions[0].ticker if positions else None
    macro_tickers = []
    if port_dir not in sys.path:
        sys.path.insert(0, port_dir)
    try:
        from macro import get_macro_indices
        from config import LiveDataUnavailableError
        macro_tickers = get_macro_indices()
    except LiveDataUnavailableError:
        raise
    except Exception:
        macro_tickers = []
    macro_probe = macro_tickers[0][0] if macro_tickers else None

    if not probe_ticker:
        print(_grey("  No portfolio positions — skipping ticker-based live checks. Use -p path/to/portfolio.csv"))
        _check("Yahoo Finance price fetch", lambda: "Skip (no portfolio)")
        _check("Fundamental fields available", lambda: "Skip (no portfolio)")
        _check("Earnings date fetch", lambda: "Skip (no portfolio)")
        _check("Data freshness assessment", lambda: "Skip (no portfolio)")
    else:
        print(f"  {_grey('Fetching live data for ' + probe_ticker + ' — takes ~5 seconds...')}")

        def _price():
            import yfinance as yf
            tk = yf.Ticker(probe_ticker)
            info = tk.info
            price = (info.get("currentPrice") or info.get("regularMarketPrice"))
            if not price:
                raise ValueError("No price returned — Yahoo Finance may be rate-limiting")
            return f"{probe_ticker} price: ${price:.2f}"
        _check("Yahoo Finance price fetch", _price)

        def _fundamentals():
            import yfinance as yf
            info = yf.Ticker(probe_ticker).info
            fields = ["forwardPE", "returnOnEquity", "revenueGrowth", "freeCashflow", "mostRecentQuarter"]
            missing = [f for f in fields if info.get(f) is None]
            if len(missing) > 2:
                return f"WARN:Many fundamental fields missing: {missing} — scoring will use fewer signals"
            return f"{len(fields) - len(missing)}/{len(fields)} fundamental fields available"
        _check("Fundamental fields available", _fundamentals)

        def _earnings_date():
            from earnings import fetch_earnings_date
            ei = fetch_earnings_date(probe_ticker)
            if ei.urgency == "unknown":
                return f"WARN:Earnings date unavailable for {probe_ticker} — yfinance calendar may be down"
            return f"{probe_ticker} next earnings: {ei.label}"
        _check("Earnings date fetch", _earnings_date)

        def _data_freshness():
            import yfinance as yf
            from data_freshness import assess_freshness
            info = yf.Ticker(probe_ticker).info
            tf = assess_freshness(probe_ticker, info)
            if tf.worst_status == "very_stale":
                return f"WARN:{probe_ticker} data is very stale ({tf.summary_label})"
            return f"{probe_ticker}: {tf.summary_label}"
        _check("Data freshness assessment", _data_freshness)

    if not macro_probe:
        print(_grey("  No macro_indices.csv — skipping macro fetch. Add portfolio/macro_indices.csv"))
        _check("Macro ticker fetch", lambda: "Skip (no macro config)")
    else:
        def _macro():
            import yfinance as yf
            info = yf.Ticker(macro_probe).info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice")
            if not price:
                raise ValueError(f"{macro_probe} price unavailable")
            return f"{macro_probe}: ${price:.2f}"
        _check("Macro ticker fetch", _macro)


# ─────────────────────────────────────────────
# 7. Fundamental scoring smoke test (uses portfolio tickers only)
# ─────────────────────────────────────────────

def check_scoring(positions=None):
    """Use portfolio tickers for scoring checks. No hardcoded symbols."""
    _section("7. FUNDAMENTAL SCORING SMOKE TEST")
    root = os.path.dirname(os.path.abspath(__file__))
    tickers = [p.ticker for p in positions] if positions else []
    if not tickers:
        print(_grey("  No portfolio positions — skipping. Use -p path/to/portfolio.csv"))
        _check("Score ticker across 4 modules", lambda: "Skip (no portfolio)")
        _check("fundamental_bridge path resolution", lambda: "Skip (no portfolio)")
        return
    probe = tickers[0]
    second = tickers[1] if len(tickers) > 1 else probe
    print(f"  {_grey('Scoring ' + probe + ' through all four modules (live data)...')}")

    def _score():
        import yfinance as yf
        sys.path.insert(0, os.path.join(root, "research"))
        from fundamentals import score_ticker
        info = yf.Ticker(probe).info
        fs = score_ticker(probe, "Stock", info)
        if fs.skipped:
            return f"WARN:{probe} skipped quality gate: {fs.skip_reason}"
        return (f"Q:{fs.quality_score:.0f} V:{fs.value_score:.0f} "
                f"M:{fs.momentum_score:.0f} I:{fs.income_score:.0f} → Composite:{fs.composite_score:.0f}")
    _check("Score ticker across 4 modules", _score)

    def _bridge_score():
        sys.path.insert(0, os.path.join(root, "portfolio"))
        from fundamental_bridge import score_holdings, fmt_fundamental_scores
        to_score = tickers[:2]
        scores = score_holdings(to_score)
        if not scores:
            raise ValueError("fundamental_bridge returned no scores")
        text = fmt_fundamental_scores(scores)
        if probe not in text:
            raise ValueError(f"formatted output missing {probe}")
        return f"Bridge scored {len(scores)} tickers successfully"
    _check("fundamental_bridge path resolution", _bridge_score)


# ─────────────────────────────────────────────
# 8. LLM backend connectivity
# ─────────────────────────────────────────────

def check_api_connectivity():
    _section("8. LLM BACKEND CONNECTIVITY")

    # ── Local Ollama ──────────────────────────
    def _ollama_running():
        import urllib.request
        import sys, os
        root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(root, "portfolio"))
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL
        try:
            urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
            return f"Ollama reachable at {OLLAMA_BASE_URL}"
        except Exception as e:
            return f"WARN:Ollama not reachable at {OLLAMA_BASE_URL} — "\
                   f"install from https://ollama.com then run: ollama pull {OLLAMA_MODEL}"
    _check("Local Ollama server reachable", _ollama_running)

    def _ollama_model():
        import urllib.request, json
        import sys, os
        root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(root, "portfolio"))
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=3) as r:
                data   = json.loads(r.read())
                models = [m["name"] for m in data.get("models", [])]
                if not any(OLLAMA_MODEL.split(":")[0] in m for m in models):
                    return (f"WARN:Model '{OLLAMA_MODEL}' not found in Ollama. "
                            f"Run: ollama pull {OLLAMA_MODEL}. "
                            f"Available: {', '.join(models[:5]) or 'none'}")
                return f"Model '{OLLAMA_MODEL}' available"
        except Exception:
            return "WARN:Could not check model list — is Ollama running?"
    _check(f"Ollama model available (default: llama3.2:latest)", _ollama_model)

    def _ollama_inference():
        """Quick inference test — only if Ollama is running."""
        import urllib.request
        import sys, os
        root = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(root, "portfolio"))
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL
        try:
            urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        except Exception:
            return "WARN:Skipped — Ollama not running"
        print(f"  {_grey('Testing Ollama inference (may take 10-30s for first run)...')}")
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        llm = ChatOpenAI(
            model=OLLAMA_MODEL,
            api_key="ollama",
            base_url=f"{OLLAMA_BASE_URL}/v1",
            temperature=0,
            max_tokens=10,
        )
        t0       = time.time()
        response = llm.invoke([HumanMessage(content="Reply with the single word: OK")])
        elapsed  = time.time() - t0
        reply    = response.content.strip()[:30]
        return f"Response: '{reply}' ({elapsed:.1f}s)"
    _check("Ollama inference test", _ollama_inference)

    # ── External Grok ─────────────────────────
    print(f"  {_grey('--- External Grok (optional) ---')}")

    def _grok_key():
        key = os.environ.get("GROK_API_KEY", "")
        if not key or key == "YOUR_GROK_API_KEY_HERE":
            return "WARN:GROK_API_KEY not set — external LLM unavailable (local will be used)"
        masked = key[:8] + "..." + key[-4:]
        return f"Key found: {masked}"
    _check("Grok API key set", _grok_key)

    def _grok_call():
        import sys as _sys, os as _os
        key = _os.environ.get("GROK_API_KEY", "")
        if not key or key == "YOUR_GROK_API_KEY_HERE":
            return "WARN:Skipped — GROK_API_KEY not set"
        root = _os.path.dirname(_os.path.abspath(__file__))
        if root + "/portfolio" not in _sys.path:
            _sys.path.insert(0, _os.path.join(root, "portfolio"))
        from config import GROK_BASE_URL, GROK_MODEL
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        print(f"  {_grey('Sending minimal test message to Grok...')}")
        llm = ChatOpenAI(
            model=GROK_MODEL,
            api_key=key,
            base_url=GROK_BASE_URL,
            temperature=0,
            max_tokens=10,
        )
        t0       = time.time()
        response = llm.invoke([HumanMessage(content="Reply with the single word: OK")])
        elapsed  = time.time() - t0
        return f"Response: '{response.content.strip()[:30]}' ({elapsed:.1f}s)"
    _check("Grok API test call", _grok_call)


# ─────────────────────────────────────────────
# 9. PDF generation smoke test
# ─────────────────────────────────────────────

def check_pdf_generation():
    _section("9. PDF GENERATION SMOKE TEST")

    def _reportlab():
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        import tempfile, os

        tmp = tempfile.mktemp(suffix=".pdf")
        try:
            doc    = SimpleDocTemplate(tmp, pagesize=letter)
            styles = getSampleStyleSheet()
            doc.build([Paragraph("Diagnostic test PDF", styles["Normal"])])
            size   = os.path.getsize(tmp)
            return f"PDF created ({size} bytes)"
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    _check("ReportLab can create a PDF", _reportlab)


# ─────────────────────────────────────────────
# 10. Wikipedia S&P 500 fetch (research)
# ─────────────────────────────────────────────

def check_sp500_fetch():
    _section("10. S&P 500 UNIVERSE FETCH (research)")
    print(f"  {_grey('Fetching S&P 500 list from Wikipedia...')}")

    def _wiki():
        import sys, os, importlib.util
        root      = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(root, "research", "recommendations.py")
        unique    = "_diag_rec_wiki"
        if unique in sys.modules:
            del sys.modules[unique]
        spec = importlib.util.spec_from_file_location(unique, file_path)
        if spec is None:
            raise ImportError(f"Cannot load {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        spec.loader.exec_module(module)
        tickers = module._fetch_ticker_universe_live()
        if len(tickers) < 400:
            return f"WARN:Only {len(tickers)} tickers fetched — expected ~500"
        return f"{len(tickers)} tickers fetched from Wikipedia"
    _check("Wikipedia S&P 500 list accessible", _wiki)


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────

def _print_summary():
    print("\n" + "═" * 55)
    print(_bold("  DIAGNOSTIC SUMMARY"))
    print("═" * 55)

    total_checks = 0
    # Count from prints above — approximate
    if not _failures and not _warnings:
        print(_green("  ✅ All checks passed — system is ready to run."))
        print()
        print("  Next steps:")
        print("  1. Use your portfolio CSV: python main.py -p path/to/positions.csv")
        print("  2. cd portfolio && python main.py --no-llm  (test data only)")
        print("  3. cd portfolio && python main.py           (full run with AI)")
    else:
        if _failures:
            print(_red(f"  ❌ {len(_failures)} check(s) FAILED — must fix before running:"))
            for f in _failures:
                print(_red(f"       • {f}"))
        if _warnings:
            print(_amber(f"\n  ⚠️  {len(_warnings)} warning(s) — system will run but review these:"))
            for w in _warnings:
                print(_amber(f"       • {w}"))
        print()
        print("  Fix failures first, then re-run: python diagnose.py")

    print("═" * 55 + "\n")
    return 1 if _failures else 0


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def _resolve_portfolio_path(portfolio_arg):
    """Resolve portfolio CSV path (same logic as check_portfolio_csv)."""
    root = os.path.dirname(os.path.abspath(__file__))
    if portfolio_arg:
        return os.path.abspath(portfolio_arg)
    default = os.path.join(root, "portfolio", "portfolio.csv")
    if os.path.isfile(default):
        return default
    port_dir = os.path.join(root, "portfolio")
    csvs = sorted(f for f in os.listdir(port_dir) if f.endswith(".csv")) if os.path.isdir(port_dir) else []
    return os.path.join(port_dir, csvs[0]) if csvs else default


def _load_positions_for_diagnose(csv_path):
    """Load portfolio positions for live-data checks. Returns [] if path missing or parse fails."""
    root = os.path.dirname(os.path.abspath(__file__))
    port_dir = os.path.join(root, "portfolio")
    if not os.path.isfile(csv_path):
        return []
    added = False
    if port_dir not in sys.path:
        sys.path.insert(0, port_dir)
        added = True
    try:
        from portfolio import load_portfolio
        return load_portfolio(csv_path)
    except Exception:
        return []
    finally:
        if added and port_dir in sys.path:
            sys.path.remove(port_dir)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Investment system diagnostic")
    parser.add_argument(
        "--portfolio", "-p",
        type=str,
        default=None,
        help="Path to portfolio CSV (default: portfolio/portfolio.csv or first .csv in portfolio/)",
    )
    args = parser.parse_args()

    csv_path = _resolve_portfolio_path(args.portfolio)
    positions = _load_positions_for_diagnose(csv_path)

    print("\n" + "═" * 55)
    print(_bold("  INVESTMENT SYSTEM DIAGNOSTIC"))
    print(f"  {datetime.now().strftime('%A, %B %d %Y  %H:%M')}")
    print("═" * 55)

    try:
        check_folder_structure()
        check_dependencies()
        check_api_key()
        check_portfolio_csv(csv_path=csv_path)
        check_internal_imports()
        check_live_data(positions=positions)
        check_scoring(positions=positions)
        check_api_connectivity()
        check_pdf_generation()
        check_sp500_fetch()
    except Exception as e:
        root = os.path.dirname(os.path.abspath(__file__))
        if os.path.join(root, "portfolio") not in sys.path:
            sys.path.insert(0, os.path.join(root, "portfolio"))
        try:
            from config import LiveDataUnavailableError
            if isinstance(e, LiveDataUnavailableError):
                print(_red(f"\n  LIVE DATA RULE: {e}"))
                if e.__cause__:
                    c = e.__cause__
                    print(_red(f"  Backend error ({type(c).__name__}): {c}"))
                sys.exit(1)
        except ImportError:
            pass
        raise

    exit_code = _print_summary()
    sys.exit(exit_code)
