# portfolio/agents.py
# ─────────────────────────────────────────────
# LangGraph multi-agent pipeline for the Weekly Pulse Report.
# Live data only: portfolio from CSV (no hardcoded tickers); macro from config files + live fetch.
#
# Graph:
#   START
#     → portfolio_node
#     → macro_node
#     → health_agent
#     → macro_agent
#     → risk_agent
#     → synthesis_agent
#   END
# ─────────────────────────────────────────────

from __future__ import annotations

import operator
import os
import sys
from typing import Annotated, Any, Dict, List, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    GROK_API_KEY, GROK_BASE_URL, GROK_MODEL,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    DEFAULT_LLM_BACKEND, PORTFOLIO_CSV,
)
from macro import MacroSnapshot, fetch_macro_snapshot
from portfolio import Portfolio, build_portfolio
from fundamental_bridge import (
    score_holdings,
    fmt_fundamental_context_for_health,
    fmt_fundamental_context_for_risk,
)
from verifier import run_verifier, VerificationReport


class PulseState(TypedDict):
    messages:             Annotated[List[BaseMessage], operator.add]
    portfolio:            Any
    macro:                Any
    portfolio_summary:    str
    macro_summary:        str
    fundamentals_summary: str   # per-holding fundamental scores
    fundamentals_risk:    str   # risk-focused fundamental summary
    verification_report:  Any   # VerificationReport from verifier agent
    llm_backend:          str   # "local" | "external"


def _make_llm(backend: str = DEFAULT_LLM_BACKEND):
    """
    Factory that returns the correct LLM based on backend.

    backend="local"    → Ollama (llama3.2:latest by default)
                          Requires Ollama running locally.
                          Free, private, no API key needed.

    backend="external" → Grok via xAI API.
                          Requires GROK_API_KEY env var.
                          Higher quality, costs per token.
    """
    if backend == "external":
        if not GROK_API_KEY or GROK_API_KEY == "YOUR_GROK_API_KEY_HERE":
            raise ValueError(
                "External LLM requested but GROK_API_KEY is not set. "
                "Run: export GROK_API_KEY='xai-...'"
            )
        return ChatOpenAI(
            model=GROK_MODEL,
            api_key=GROK_API_KEY,
            base_url=GROK_BASE_URL,
            temperature=0.4,
            max_tokens=1500,
        )

    # Default: local Ollama
    # Uses the OpenAI-compatible endpoint that Ollama exposes
    return ChatOpenAI(
        model=OLLAMA_MODEL,
        api_key="ollama",          # Ollama ignores this but the SDK requires it
        base_url=f"{OLLAMA_BASE_URL}/v1",
        temperature=0.4,
        max_tokens=1500,
    )


def _fmt_portfolio(portfolio: Portfolio) -> str:
    lines = [
        f"Portfolio as of: {portfolio.as_of}",
        f"Total Market Value: ${portfolio.total_value:,.0f}",
        f"Total Cost Basis:   ${portfolio.total_cost:,.0f}",
        f"Overall Gain/Loss:  {portfolio.total_gain_pct:+.1f}%",
        "",
        "HOLDINGS:",
        f"{'Ticker':<8} {'Company':<28} {'Shares':>7} {'AvgCost':>8} "
        f"{'Price':>8} {'Value':>10} {'G/L%':>7} {'Wk%':>7} {'Sector':<24}",
        "-" * 115,
    ]
    for p in portfolio.positions:
        price_str = f"${p.current_price:.2f}"    if p.current_price   else "n/a"
        value_str = f"${p.market_value:,.0f}"    if p.market_value    else "n/a"
        gl_str    = f"{p.gain_loss_pct:+.1f}%"  if p.gain_loss_pct is not None else "n/a"
        wk_str    = f"{p.week_change_pct:+.1f}%" if p.week_change_pct is not None else "n/a"
        name      = (p.company_name or p.ticker)[:27]
        lines.append(
            f"{p.ticker:<8} {name:<28} {p.shares:>7.1f} ${p.avg_cost:>7.2f} "
            f"{price_str:>8} {value_str:>10} {gl_str:>7} {wk_str:>7} {p.sector:<24}"
        )
    lines += ["", "SECTOR WEIGHTS:"]
    for sector, pct in sorted(portfolio.sector_weights.items(), key=lambda x: -x[1]):
        bar = "█" * int(pct / 2)
        lines.append(f"  {sector:<30} {pct:5.1f}%  {bar}")
    lines += ["", "ASSET CLASS WEIGHTS:"]
    for cls, pct in sorted(portfolio.class_weights.items(), key=lambda x: -x[1]):
        lines.append(f"  {cls:<20} {pct:5.1f}%")
    return "\n".join(lines)


def _fmt_macro(macro: MacroSnapshot) -> str:
    lines = [
        f"Macro Snapshot as of: {macro.as_of}",
        "",
        macro.vix_interpretation,
        "",
        "MARKET INDICES (weekly performance):",
        f"{'Symbol':<8} {'Label':<22} {'Price':>8} {'1Wk%':>7} {'1Mo%':>7} {'1Yr%':>7}",
        "-" * 65,
    ]
    for m in macro.indices:
        price = f"${m.current_price:.2f}" if m.current_price else "n/a"
        wk    = f"{m.week_change_pct:+.1f}%"  if m.week_change_pct  is not None else "n/a"
        mo    = f"{m.month_change_pct:+.1f}%" if m.month_change_pct is not None else "n/a"
        yr    = f"{m.year_change_pct:+.1f}%"  if m.year_change_pct  is not None else "n/a"
        lines.append(f"{m.symbol:<8} {m.label:<22} {price:>8} {wk:>7} {mo:>7} {yr:>7}")
    lines += ["", "SECTOR ROTATION (best → worst this week):",
              f"{'ETF':<6} {'Sector':<28} {'1Wk%':>7} {'1Mo%':>7}", "-" * 52]
    for s in macro.sectors:
        wk = f"{s.week_change_pct:+.1f}%"  if s.week_change_pct  is not None else "n/a"
        mo = f"{s.month_change_pct:+.1f}%" if s.month_change_pct is not None else "n/a"
        lines.append(f"{s.symbol:<6} {s.label:<28} {wk:>7} {mo:>7}")
    return "\n".join(lines)


def portfolio_node(state: PulseState) -> PulseState:
    print("  [1/6] Loading portfolio...")
    csv_path = state.get("portfolio_csv") or PORTFOLIO_CSV
    portfolio = build_portfolio(csv_path)
    return {"portfolio": portfolio, "portfolio_summary": _fmt_portfolio(portfolio), "messages": []}


def macro_node(state: PulseState) -> PulseState:
    print("  [2/6] Fetching macro data...")
    macro = fetch_macro_snapshot()
    return {"macro": macro, "macro_summary": _fmt_macro(macro), "messages": []}


def fundamentals_node(state: PulseState) -> PulseState:
    """
    Score all holdings using the four-module fundamental engine.
    Runs after portfolio data is loaded — scores only your holdings
    (not the full S&P 500), so this takes seconds not minutes.
    """
    print("  [3/7] Scoring holdings fundamentals...")
    tickers = [p.ticker for p in state["portfolio"].positions]
    scores  = score_holdings(tickers)
    return {
        "fundamentals_summary": fmt_fundamental_context_for_health(scores),
        "fundamentals_risk":    fmt_fundamental_context_for_risk(scores),
        "messages": [],
    }


def health_agent(state: PulseState) -> PulseState:
    print("  [4/7] Running portfolio health agent...")
    llm    = _make_llm(state.get("llm_backend", DEFAULT_LLM_BACKEND))
    prompt = (
        "You are a senior portfolio analyst reviewing a client's weekly holdings.\n\n"
        "STYLE: Short, clear sentences. No jargon. No buzzwords. Be direct.\n"
        "CONSTRAINT: Only reference numbers that appear in the data below.\n\n"
        f"PORTFOLIO DATA:\n{state['portfolio_summary']}\n\n"
        f"FUNDAMENTAL SCORES:\n{state['fundamentals_summary']}\n\n"
        "TASK — Write a concise Portfolio Health Assessment covering:\n"
        "1. CONCENTRATION RISK: Are any single stocks or sectors dangerously overweight?\n"
        "2. DIVERSIFICATION: Is the portfolio well spread, or does it have blind spots?\n"
        "3. FUNDAMENTAL QUALITY: Which holdings score strongly or weakly on fundamentals? "
           "Call out any with weak quality or value scores.\n"
        "4. WINNERS & LOSERS: Which positions are working, which are not?\n"
        "5. REBALANCING FLAGS: Any positions that have drifted significantly?\n\n"
        "Keep each section to 2-3 short sentences. Total under 300 words."
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"messages": [AIMessage(content=f"PORTFOLIO HEALTH:\n{response.content}", name="HealthAgent")]}


def macro_agent(state: PulseState) -> PulseState:
    print("  [5/7] Running macro context agent...")
    llm    = _make_llm(state.get("llm_backend", DEFAULT_LLM_BACKEND))
    prompt = (
        "You are a macro strategist at a wealth management firm.\n\n"
        "STYLE: Short, clear sentences. No jargon. Be direct and specific.\n"
        "CONSTRAINT: Only reference numbers that appear in the data below.\n\n"
        f"MACRO DATA:\n{state['macro_summary']}\n\n"
        f"CLIENT PORTFOLIO SECTOR WEIGHTS:\n"
        + "\n".join(f"  {k}: {v:.1f}%" for k, v in (state["portfolio"].sector_weights or {}).items())
        + "\n\n"
        "TASK — Write a concise Macro Context section covering:\n"
        "1. MARKET REGIME: What is the overall market tone this week?\n"
        "2. SECTOR ROTATION: What sectors are gaining/losing favour, and does this affect the client?\n"
        "3. KEY RISKS: Name 2-3 macro risks most relevant to this portfolio right now.\n"
        "4. OPPORTUNITY: Is there one macro-driven opportunity worth noting?\n\n"
        "Keep each section to 2-3 short sentences. Total under 250 words."
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"messages": [AIMessage(content=f"MACRO CONTEXT:\n{response.content}", name="MacroAgent")]}


def risk_agent(state: PulseState) -> PulseState:
    print("  [6/7] Running risk and alerts agent...")
    llm     = _make_llm(state.get("llm_backend", DEFAULT_LLM_BACKEND))
    alerts  = []
    for p in state["portfolio"].positions:
        if p.week_change_pct is not None and abs(p.week_change_pct) >= 5.0:
            direction = "up" if p.week_change_pct > 0 else "down"
            alerts.append(f"{p.ticker} moved {p.week_change_pct:+.1f}% this week ({direction})")
    alert_text = "\n".join(alerts) if alerts else "No positions moved more than 5% this week."

    earnings_alerts = []
    for p in state["portfolio"].positions:
        if p.earnings and p.earnings.urgency in ("critical", "warning"):
            earnings_alerts.append(f"{p.ticker}: {p.earnings.flag} {p.earnings.label}")
    earnings_text = (
        "\n".join(earnings_alerts)
        if earnings_alerts
        else "No holdings with earnings within 30 days."
    )
    prompt = (
        "You are a risk officer reviewing a client's portfolio.\n\n"
        "STYLE: Be blunt and direct. Use a bullet-point format for flags.\n"
        "CONSTRAINT: Only reference numbers from the data provided.\n\n"
        f"SIGNIFICANT MOVERS THIS WEEK:\n{alert_text}\n\n"
        f"UPCOMING EARNINGS (within 30 days):\n{earnings_text}\n\n"
        f"FUNDAMENTAL RISK FLAGS:\n{state['fundamentals_risk']}\n\n"
        f"PORTFOLIO DATA:\n{state['portfolio_summary']}\n\n"
        "TASK — Produce a Risk & Alerts section:\n"
        "- FLAG positions that moved significantly and need a review\n"
        "- FLAG any sector now over 35% of the portfolio\n"
        "- FLAG any position down more than 20% from cost basis\n"
        "- FLAG any position where current price is near its 52-week low\n"
        "- FLAG any holding with earnings within 7 days as a critical risk\n"
        "- FLAG any holding with earnings within 30 days as something to monitor\n"
        "- Close with a TRAFFIC LIGHT: GREEN / AMBER / RED and one sentence why.\n\n"
        "Keep total under 200 words."
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"messages": [AIMessage(content=f"RISK & ALERTS:\n{response.content}", name="RiskAgent")]}


def synthesis_agent(state: PulseState) -> PulseState:
    print("  [7/8] Running synthesis agent...")
    llm        = _make_llm(state.get("llm_backend", DEFAULT_LLM_BACKEND))
    health_view = next((m.content for m in state["messages"] if getattr(m, "name", None) == "HealthAgent"), "")
    macro_view  = next((m.content for m in state["messages"] if getattr(m, "name", None) == "MacroAgent"),  "")
    risk_view   = next((m.content for m in state["messages"] if getattr(m, "name", None) == "RiskAgent"),   "")
    prompt = (
        "You are a senior investment advisor writing a weekly briefing for a private client.\n\n"
        "CLIENT PROFILE:\n"
        "- 55 years old, 10-year investment horizon\n"
        "- $500K actively managed portfolio, 95% equities / 5% ETFs\n"
        "- Goal: aggressive growth, accepts volatility\n"
        "- Makes 1-2 investment decisions per month\n\n"
        "STYLE: Write like a trusted advisor, not a robot. Short paragraphs. "
        "Plain language. No buzzwords. Be honest — including when the answer is 'do nothing.'\n\n"
        f"PORTFOLIO HEALTH:\n{health_view}\n\n"
        f"MACRO CONTEXT:\n{macro_view}\n\n"
        f"RISK & ALERTS:\n{risk_view}\n\n"
        f"FUNDAMENTAL QUALITY CONTEXT:\n{state['fundamentals_summary']}\n\n"
        "TASK:\n"
        "EXECUTIVE SUMMARY (3-4 short paragraphs): Synthesise all four inputs. "
        "What is the overall state of this portfolio? What does the macro environment mean specifically? "
        "Are the holdings fundamentally sound or are there quality concerns?\n\n"
        "ACTION ITEMS FOR THE WEEK AHEAD (numbered list): "
        "Give 3-5 specific, actionable items grounded in both price data AND fundamental scores. "
        "If the right answer is to do nothing, say so clearly. "
        "If a holding scores poorly on fundamentals, say whether to review or hold.\n\n"
        "Total under 400 words."
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"messages": [AIMessage(content=f"EXECUTIVE SUMMARY:\n{response.content}", name="Synthesis")]}


def verifier_agent(state: PulseState) -> PulseState:
    """
    Checks the synthesis output against all raw data sources.
    Flags SUPPORTED / UNSUPPORTED / CONTRADICTED / CAVEAT claims.
    Does not rewrite the synthesis — adds an audit layer.
    """
    print("  [8/8] Running verifier agent...")
    llm = _make_llm(state.get("llm_backend", DEFAULT_LLM_BACKEND))

    synthesis_output = next(
        (m.content for m in state["messages"]
         if getattr(m, "name", None) == "Synthesis"), ""
    )

    report = run_verifier(
        synthesis_output     = synthesis_output,
        portfolio_summary    = state["portfolio_summary"],
        fundamentals_summary = state["fundamentals_summary"],
        macro_summary        = state["macro_summary"],
        portfolio            = state["portfolio"],
        llm                  = llm,
    )

    # Build a concise text representation for the message log
    verdict_icon = {"PASS": "✅", "CAUTION": "🟡", "FAIL": "🔴"}.get(
        report.overall_verdict, "❓"
    )
    lines = [f"VERIFICATION REPORT {verdict_icon} {report.overall_verdict}:",
             f"Summary: {report.summary}",
             f"Supported: {report.supported_count}  "
             f"Unsupported: {report.unsupported_count}  "
             f"Contradicted: {report.contradicted_count}  "
             f"Caveats: {report.caveat_count}",
             ""]
    for item in report.items:
        icon = {"SUPPORTED": "✅", "UNSUPPORTED": "🟡",
                "CONTRADICTED": "🔴", "CAVEAT": "🔵"}.get(item.verdict, "❓")
        lines.append(f"  {icon} [{item.verdict}] {item.claim}")
        if item.evidence:
            lines.append(f"       → {item.evidence}")

    return {
        "messages": [AIMessage(
            content="\n".join(lines),
            name="Verifier"
        )],
        "verification_report": report,
    }


def build_graph() -> Any:
    workflow = StateGraph(PulseState)
    workflow.add_node("portfolio",    portfolio_node)
    workflow.add_node("macro",         macro_node)
    workflow.add_node("fundamentals",  fundamentals_node)
    workflow.add_node("health",        health_agent)
    workflow.add_node("macro_ai",      macro_agent)
    workflow.add_node("risk",          risk_agent)
    workflow.add_node("synthesis",     synthesis_agent)
    workflow.add_node("verifier",      verifier_agent)
    workflow.add_edge(START,            "portfolio")
    workflow.add_edge("portfolio",     "macro")
    workflow.add_edge("macro",         "fundamentals")
    workflow.add_edge("fundamentals",  "health")
    workflow.add_edge("health",        "macro_ai")
    workflow.add_edge("macro_ai",      "risk")
    workflow.add_edge("risk",          "synthesis")
    workflow.add_edge("synthesis",     "verifier")
    workflow.add_edge("verifier",      END)
    return workflow.compile()
