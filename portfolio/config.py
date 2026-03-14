# portfolio/config.py
# ─────────────────────────────────────────────
# Weekly Pulse Report — Configuration
#
# ═══════════════════════════════════════════════════════════════════════════════
# HARD RULE (non-negotiable):
#   ALL data in reports MUST be CURRENT live market data from external sources.
#   NOTHING may be hardcoded, guessed, or silently ignored.
#   Any failure to retrieve required external data MUST cause report generation
#   to FAIL with an appropriate, descriptive error message (no report PDF).
# ═══════════════════════════════════════════════════════════════════════════════
#
# - Portfolio: from CSV provided at runtime (--portfolio or PORTFOLIO_CSV).
# - Macro/sector: symbol lists from macro_indices.csv / sector_etfs.csv; data fetched live each run.
# - All price, fundamental, and macro data are fetched at execution time.
# - On fetch failure: raise LiveDataUnavailableError; entry points exit with error, no PDF.
# ─────────────────────────────────────────────

import os


class LiveDataUnavailableError(RuntimeError):
    """
    Raised when live data could not be retrieved. Do not use hardcoded tickers or default lists.
    For diagnosis and troubleshooting, always include the backend/original error in the message
    (e.g. exception type and str(e)) and use 'raise ... from e' to chain the cause.
    """

    MESSAGE = "Live data could not be retrieved. Do not use hardcoded tickers or default lists."

# ── LLM Backend ───────────────────────────────
# Default: local Ollama (free, private, no API key needed)
# Override at runtime with: python main.py --llm external
#
# LOCAL (Ollama):
#   - Requires Ollama running: https://ollama.com
#   - Pull the model first: ollama pull llama3.2:latest
#   - Runs entirely on your machine, no API costs
#
# EXTERNAL (Grok via xAI API):
#   - Requires: export GROK_API_KEY="xai-..."
#   - Higher quality output, costs per token
#   - Get a key at: https://console.x.ai

DEFAULT_LLM_BACKEND = "local"   # "local" | "external"

# ── Local Ollama settings ─────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL",    "llama3.2:latest")

# ── External Grok settings ────────────────────
GROK_API_KEY  = os.environ.get("GROK_API_KEY", "YOUR_GROK_API_KEY_HERE")
GROK_BASE_URL = "https://api.x.ai/v1"
GROK_MODEL    = os.environ.get("GROK_MODEL", "grok-3-latest")

# ── Portfolio ─────────────────────────────────
# Default CSV path; overridden by main.py --portfolio / -p (e.g. broker export).
_HERE         = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_CSV = os.path.join(_HERE, "portfolio.csv")

# ── Output ────────────────────────────────────
REPORTS_DIR   = os.path.join(_HERE, "reports")

# ── Macro / sector data (live only; no hardcoded tickers) ─
# Paths to CSV files defining which indices/sectors to fetch each run.
# Edit these files to change symbols; data is always fetched live.
MACRO_INDICES_CSV  = os.path.join(_HERE, "macro_indices.csv")
SECTOR_ETFS_CSV   = os.path.join(_HERE, "sector_etfs.csv")

# ── Alert thresholds ──────────────────────────
ALERT_MOVE_PCT      = 5.0
REBALANCE_DRIFT_PCT = 5.0
