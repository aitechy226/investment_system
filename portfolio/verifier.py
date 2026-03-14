# portfolio/verifier.py
# ─────────────────────────────────────────────
# Verification agent for the Weekly Pulse Report.
#
# Reads the synthesis output alongside all raw
# data sources and checks each claim for:
#   - SUPPORTED: grounded in the data provided
#   - UNSUPPORTED: plausible but not verifiable
#   - CONTRADICTED: conflicts with the data
#
# The verifier has access to:
#   1. Portfolio price data (positions, G/L, weekly moves)
#   2. Fundamental scores (quality, value, momentum, income)
#   3. Macro snapshot (indices, VIX, sectors)
#   4. Earnings dates
#   5. Data freshness flags
#
# Output appended to PDF as a transparency section.
# Does NOT rewrite the synthesis — adds a separate
# audit trail so you can judge what to trust.
# ─────────────────────────────────────────────

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@dataclass
class VerificationItem:
    claim:      str        # the specific claim being checked
    verdict:    str        # "SUPPORTED" | "UNSUPPORTED" | "CONTRADICTED" | "CAVEAT"
    evidence:   str        # what data supports or refutes it
    severity:   str        # "info" | "warning" | "error"


@dataclass
class VerificationReport:
    items:            List[VerificationItem]
    overall_verdict:  str    # "PASS" | "CAUTION" | "FAIL"
    summary:          str    # one paragraph for the report
    supported_count:  int
    unsupported_count: int
    contradicted_count: int
    caveat_count:     int


def _build_verification_data(
    portfolio_summary: str,
    fundamentals_summary: str,
    macro_summary: str,
    portfolio,           # Portfolio object
) -> str:
    """
    Build a single structured data block for the verifier LLM.
    This is the ground truth it checks claims against.
    """
    lines = [
        "=== GROUND TRUTH DATA FOR VERIFICATION ===",
        "",
        "--- PORTFOLIO POSITIONS (live price data) ---",
        portfolio_summary,
        "",
        "--- FUNDAMENTAL SCORES (research engine) ---",
        fundamentals_summary,
        "",
        "--- MACRO SNAPSHOT ---",
        macro_summary,
        "",
    ]

    # Add earnings summary
    earnings_lines = ["--- EARNINGS CALENDAR ---"]
    equity_positions = [p for p in portfolio.positions if p.asset_class.lower() != "etf"]
    has_earnings = False
    for p in equity_positions:
        if p.earnings and p.earnings.urgency != "unknown":
            earnings_lines.append(
                f"  {p.ticker}: {p.earnings.flag} {p.earnings.label}"
            )
            has_earnings = True
    if not has_earnings:
        earnings_lines.append("  No earnings data available.")
    lines += earnings_lines
    lines.append("")

    # Add freshness warnings
    fresh_lines = ["--- DATA FRESHNESS ---"]
    has_issues = False
    for p in portfolio.positions:
        if p.freshness and p.freshness.worst_status in ("stale", "very_stale", "unknown"):
            fresh_lines.append(
                f"  {p.ticker}: {p.freshness.summary_flag} {p.freshness.summary_label}"
            )
            has_issues = True
    if not has_issues:
        fresh_lines.append("  All data current.")
    lines += fresh_lines

    return "\n".join(lines)


def _build_verifier_prompt(synthesis_output: str, ground_truth: str) -> str:
    return (
        "You are an independent fact-checker reviewing an AI-generated investment summary.\n\n"
        "Your job is to check every specific factual claim in the SUMMARY against the "
        "GROUND TRUTH DATA provided. You have no other sources.\n\n"
        "RULES:\n"
        "- Only check FACTUAL claims: numbers, directions, comparisons, recommendations.\n"
        "- Ignore style opinions ('well-diversified portfolio' is subjective — skip it).\n"
        "- Do NOT use your own market knowledge. Only use the GROUND TRUTH DATA.\n"
        "- Be concise. One line per claim.\n\n"
        "FOR EACH CLAIM, output one line in this exact format:\n"
        "  [VERDICT] \'Claim text\' — Evidence or reason\n\n"
        "VERDICT options:\n"
        "  SUPPORTED    — claim is directly backed by the data\n"
        "  UNSUPPORTED  — claim cannot be verified from the data (not necessarily wrong)\n"
        "  CONTRADICTED — claim conflicts with the data\n"
        "  CAVEAT       — claim is directionally correct but overstated or imprecise\n\n"
        "After all claims, write:\n"
        "OVERALL: [PASS / CAUTION / FAIL] — one sentence explanation.\n"
        "  PASS    = all or nearly all claims are SUPPORTED\n"
        "  CAUTION = some UNSUPPORTED or CAVEAT claims present\n"
        "  FAIL    = one or more CONTRADICTED claims found\n\n"
        f"SUMMARY TO VERIFY:\n{synthesis_output}\n\n"
        f"GROUND TRUTH DATA:\n{ground_truth}\n\n"
        "Check only the claims. Do not rewrite the summary."
    )


def _parse_verification_output(raw: str) -> VerificationReport:
    """
    Parse the LLM verifier output into structured VerificationItems.
    Robust to minor formatting variations.
    """
    items     = []
    overall   = "CAUTION"
    summary   = ""

    supported    = 0
    unsupported  = 0
    contradicted = 0
    caveat_count = 0

    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Overall verdict line
        if line.upper().startswith("OVERALL:"):
            rest = line[8:].strip()
            if "PASS" in rest.upper():
                overall  = "PASS"
            elif "FAIL" in rest.upper():
                overall  = "FAIL"
            else:
                overall  = "CAUTION"
            summary = rest
            continue

        # Claim lines: [VERDICT] 'claim' — evidence
        verdict = None
        for v in ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "CAVEAT"):
            if line.upper().startswith(f"[{v}]") or line.upper().startswith(v):
                verdict = v
                break

        if verdict is None:
            continue

        # Strip verdict prefix
        rest = line
        for prefix in (f"[{verdict}]", verdict):
            if rest.upper().startswith(prefix):
                rest = rest[len(prefix):].strip()
                break

        # Split on em-dash or regular dash
        if " — " in rest:
            claim_part, evidence_part = rest.split(" — ", 1)
        elif " - " in rest:
            claim_part, evidence_part = rest.split(" - ", 1)
        else:
            claim_part   = rest
            evidence_part = ""

        claim_part   = claim_part.strip().strip("\'").strip("\"")
        evidence_part = evidence_part.strip()

        severity = "info"
        if verdict == "CONTRADICTED":
            severity     = "error"
            contradicted += 1
        elif verdict == "UNSUPPORTED":
            severity    = "warning"
            unsupported += 1
        elif verdict == "CAVEAT":
            severity     = "warning"
            caveat_count += 1
        else:
            supported += 1

        items.append(VerificationItem(
            claim=claim_part,
            verdict=verdict,
            evidence=evidence_part,
            severity=severity,
        ))

    if not summary:
        if contradicted > 0:
            summary = f"Found {contradicted} contradicted claim(s). Review before acting."
        elif unsupported > 0:
            summary = f"Found {unsupported} unsupported claim(s). Treat with caution."
        else:
            summary = f"All {supported} checked claims are supported by the data."

    return VerificationReport(
        items=items,
        overall_verdict=overall,
        summary=summary,
        supported_count=supported,
        unsupported_count=unsupported,
        contradicted_count=contradicted,
        caveat_count=caveat_count,
    )


def run_verifier(
    synthesis_output:     str,
    portfolio_summary:    str,
    fundamentals_summary: str,
    macro_summary:        str,
    portfolio,
    llm,
) -> VerificationReport:
    """
    Run the verification agent against the synthesis output.
    Returns a structured VerificationReport.

    llm: a ChatOpenAI (or compatible) instance — passed in
         so verifier uses the same Grok backend as other agents.
    """
    from langchain_core.messages import HumanMessage

    ground_truth = _build_verification_data(
        portfolio_summary, fundamentals_summary, macro_summary, portfolio
    )
    prompt = _build_verifier_prompt(synthesis_output, ground_truth)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return _parse_verification_output(response.content)
    except Exception as e:
        # Verifier failure should never crash the report; surface backend error for diagnosis
        err_type = type(e).__name__
        err_detail = f"{err_type}: {e}"
        return VerificationReport(
            items=[VerificationItem(
                claim="Verification could not run",
                verdict="UNSUPPORTED",
                evidence=err_detail,
                severity="warning",
            )],
            overall_verdict="CAUTION",
            summary=f"Verifier failed. Backend error: {err_detail}",
            supported_count=0,
            unsupported_count=1,
            contradicted_count=0,
            caveat_count=0,
        )
