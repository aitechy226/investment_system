# Personal Investment System

Two independent subsystems — run them separately.

---

## Structure

```
investment_system/
├── portfolio/          ← YOUR portfolio analysis (private)
│   ├── main.py         ← run this for Weekly Pulse Report
│   ├── config.py       ← Grok API key, alert thresholds
│   ├── portfolio.py    ← loads CSV, enriches with live prices
│   ├── macro.py        ← fetches indices, VIX, sector ETFs
│   ├── agents.py       ← LangGraph AI agents
│   ├── report.py       ← Weekly Pulse PDF generator
│   ├── portfolio.csv   ← YOUR HOLDINGS — edit this
│   └── reports/        ← Weekly Pulse PDFs saved here
│
├── research/           ← market-wide research (no personal data)
│   ├── run_fundamentals.py     ← run this for Fundamentals Report
│   ├── fundamentals.py         ← 4-module scoring engine
│   ├── fundamentals_report.py  ← Fundamentals PDF renderer
│   ├── recommendations.py      ← S&P 500 data fetcher
│   └── reports/                ← Fundamentals PDFs saved here
│
├── requirements.txt    ← install once for both subsystems
└── README.md
```

---

## Setup

```bash
# Install all dependencies (once)
pip install -r requirements.txt

# Set your Grok API key (for portfolio/ only)
export GROK_API_KEY="your_key_here"
```

---

## Running the Portfolio Pulse (Weekly — Sunday evening)

```bash
cd portfolio
python main.py                   # full run with AI analysis
python main.py --no-llm          # data + PDF only (fast test)
python main.py --output my.pdf   # custom output path
```

Edit `portfolio/portfolio.csv` with your real holdings before first run.

---

## Running the Fundamentals Report (On demand)

```bash
cd research
python run_fundamentals.py                          # full S&P 500 scan
python run_fundamentals.py --top 30                 # top 30 composite ideas
python run_fundamentals.py --watchlist AAPL,MSFT    # score specific tickers
python run_fundamentals.py --output my_report.pdf   # custom path
```

Runtime: ~3-5 minutes (parallel fetching ~500 tickers).

---

## What Each Report Contains

**Weekly Pulse** (`portfolio/`)
- Your holdings with live prices, gain/loss, weekly change
- Sector allocation breakdown
- Macro snapshot: indices, VIX, sector rotation
- AI analysis: portfolio health, macro context, risk flags, action items

**Fundamentals Report** (`research/`)
- View A: Top 25 S&P 500 stocks by composite fundamental score
- View B: Top 15 per strategy (Quality, Value, Momentum, Income)
- View C: Your watchlist scored and flagged

---

## Troubleshooting

### "Sector is Unknown" — report fails or has no value

Sector is required for a useful report. If any ticker has sector **Unknown**, the run **fails** (no PDF is generated) and you get an error listing the tickers and how to fix.

**How to diagnose**

1. **Run the diagnostic** (from repo root):
   ```bash
   python diagnose.py
   ```
   If any position has sector Unknown from the CSV, the check *"No Unknown sectors (required for report)"* fails and lists the tickers.

2. **Read the error when you run the report** (`python main.py` or `python main.py -p your.csv`). It will say something like:
   - *"Sector is Unknown or missing for ticker(s): X, Y, Z."*
   - **Cause (1):** You used a **broker export CSV** that has no sector column. The system fills sector from live data (e.g. yfinance) when possible. If the data source doesn’t return sector for those symbols, the run fails.
   - **Cause (2):** The **data source** (e.g. yfinance) did not return sector — symbol invalid, rate limit, or temporary outage.

**Fixes**

- Use a **portfolio CSV that includes a `sector` column** (e.g. standard `portfolio.csv` format), or  
- Ensure the **live data source** returns sector for your symbols (check symbol spelling, try again later), or  
- For broker exports: run the report once; sector is filled from live data. If some tickers still show Unknown, add sector manually to a converted CSV or fix the symbol/data source.

---

## Push to GitLab

Use **only** the `investment_system` folder as your Git repo (not the parent AgenticAI folder).

1. **Create a new project on GitLab** (empty, no README).

2. **From your machine, in the `investment_system` directory:**

   ```bash
   cd /path/to/AgenticAI/investment_system

   git init
   git add .
   git commit -m "Initial commit: investment system"
   git remote add origin https://gitlab.com/YOUR_GROUP_OR_USER/investment_system.git
   git branch -M main
   git push -u origin main
   ```

   If your GitLab URL uses SSH instead:
   ```bash
   git remote add origin git@gitlab.com:YOUR_GROUP_OR_USER/investment_system.git
   ```

3. **Later pushes:** from inside `investment_system` run `git add .`, `git commit -m "..."`, then `git push`.

---

## Disclaimer

For personal research only. Not financial advice.
