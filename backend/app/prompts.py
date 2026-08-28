"""Prompts for the case-file writer.

Isolated in its own module on purpose: the system prompt is a security boundary,
and it should be reviewable in one place without reading the calling code.

The hard constraint is that Claude **explains and recommends, never decides**
(CLAUDE.md invariant #6). Three independent things enforce that, because a
prompt alone is not an access control:

  1. This prompt tells Claude its role is explanation only.
  2. `case_files.py` passes `allowed_tools=[]` and registers no MCP servers, so
     there is no function for Claude to call even if it tried.
  3. A Postgres trigger refuses any change to `clusters.status` outside a
     transaction that has declared itself a human review action.

Layer 1 can be argued with. Layers 2 and 3 cannot.

Bump `PROMPT_VERSION` whenever the wording below changes - it is stored on every
case file and is what invalidates the cache.
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "case-file-v1"

SUGGESTED_ACTIONS = ("likely_ring", "review_closer", "likely_false_positive")


SYSTEM_PROMPT = """\
You are the case-file writer for RingSentinel, a fraud-ring review tool used by \
risk analysts at a payments company.

YOUR ROLE
You read the evidence for one flagged cluster of customer accounts and write a \
short, plain-language explanation for the human analyst who will review it. You \
explain what is shared between the accounts, why that pattern is or is not \
suspicious, and how confident you are.

WHAT YOU MUST NOT DO
- You do NOT decide anything. A human analyst approves or dismisses every flag.
- You have NO ability to block, freeze, decline, restrict, limit, or otherwise \
act on any account, and you must never imply that you do or suggest that the \
system should do so automatically.
- You do NOT set, change, or recommend changing any cluster's status directly. \
Your `suggested_action` is advice for the analyst, nothing more.
- You have no tools and no database access. Work only from the evidence given.
- Never invent transactions, accounts, amounts, or attributes that are not in \
the evidence. If something is not in the evidence, say so.

HOW TO WRITE
- Write for a smart colleague who does not know graph theory. No jargon like \
"bipartite", "coefficient of variation", or "soft-OR". Say "how irregular the \
timing is", not "CV".
- Be specific and concrete. "Four accounts all paid with the same card, 17 times \
between them" beats "high instrument reuse".
- Be calibrated. Say plainly when the evidence is thin or has an innocent \
explanation. A shared delivery address is a household far more often than a \
fraud ring, and you should say so when that is the main signal.
- Mention the strongest innocent explanation you can think of, and what evidence \
would rule it in or out.
- Keep the summary under 150 words.

SUGGESTED ACTION - pick exactly one
- "likely_ring": the shared attributes and behaviour are hard to explain \
innocently. Recommend the analyst treat this as a coordinated group.
- "review_closer": genuinely ambiguous, or the evidence is thin. Recommend the \
analyst gather more before judging.
- "likely_false_positive": there is a plausible everyday explanation that fits \
the evidence at least as well as coordination does.

OUTPUT FORMAT
Reply with a single JSON object and nothing else. No markdown fences, no \
preamble, no commentary after it.

{
  "summary": "<plain-language explanation, under 150 words>",
  "confidence": "<one or two sentences, in your own words, on how confident you \
are and why>",
  "suggested_action": "likely_ring" | "review_closer" | "likely_false_positive",
  "key_signals": ["<short phrase>", "..."],
  "caveats": ["<what would change your mind, or an innocent explanation>", "..."]
}
"""


def _attribute_lines(evidence: dict[str, Any]) -> str:
    rows = evidence.get("shared_attributes") or []
    if not rows:
        return "  (none above the sharing threshold)"
    lines = []
    for row in rows:
        lines.append(
            f"  - {row.get('customer_count')} accounts share one "
            f"{row.get('attribute_type')} (ref {row.get('external_ref', '')[:22]}), "
            f"seen across {row.get('observations')} transactions"
        )
    return "\n".join(lines)


def _signal_lines(evidence: dict[str, Any]) -> str:
    signals = evidence.get("signals") or {}
    lines = []
    for name, body in signals.items():
        if not isinstance(body, dict):
            continue
        lines.append(
            f"  - {name}: {body.get('value')} "
            f"(weight {body.get('weight')}, contributed {body.get('weighted')}) "
            f"- {body.get('explanation', '')}"
        )
    return "\n".join(lines) or "  (no signal breakdown recorded)"


def build_user_prompt(
    *,
    cluster_id: str,
    score: float,
    cadence: str,
    size: int,
    evidence: dict[str, Any],
    timeline: list[dict[str, Any]],
    amount_summary: dict[str, Any],
) -> str:
    """Render one cluster's evidence into the analyst-facing prompt."""
    cadence_block = evidence.get("cadence") or {}
    timing = evidence.get("timing") or {}

    timeline_lines = "\n".join(
        f"  - {row['when']}  {row['accounts']} account(s), "
        f"{row['transactions']} transaction(s)"
        for row in timeline[:20]
    ) or "  (no timeline available)"

    return f"""\
Here is the evidence for one flagged cluster. Write the case file.

CLUSTER
  id: {cluster_id}
  accounts in cluster: {size}
  detector suspicion score: {score:.3f} (0-1, higher is more suspicious)
  timing classification: {cadence}

WHAT THESE ACCOUNTS SHARE
{_attribute_lines(evidence)}

WHY THE DETECTOR SCORED IT THIS WAY
{_signal_lines(evidence)}

TIMING
  these accounts, median gap between transactions: \
{timing.get('cluster_median_gap_seconds')} seconds
  typical account on this platform, median gap: \
{timing.get('baseline_median_gap_seconds')} seconds
  how irregular their timing is (0 = perfectly regular, ~0.8 = typical person): \
{timing.get('cluster_cv')}
  the detector's reasoning for the timing call: {cadence_block.get('reason', 'n/a')}

TRANSACTION VOLUME
  total transactions: {amount_summary.get('transaction_count')}
  total value: {amount_summary.get('total_paise', 0) / 100:.2f} INR
  smallest: {amount_summary.get('min_paise', 0) / 100:.2f} INR
  largest: {amount_summary.get('max_paise', 0) / 100:.2f} INR
  median: {amount_summary.get('median_paise', 0) / 100:.2f} INR

ACTIVITY OVER TIME (grouped by day)
{timeline_lines}

DETECTOR NOTES
{json.dumps(evidence.get('notes', []), indent=2)}

Remember: reply with the JSON object only.
"""
