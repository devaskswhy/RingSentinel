"""Case-file generation via the Claude Agent SDK.

Claude reads one cluster's evidence and writes a plain-language explanation for
the analyst who will review it. It explains and recommends; it never decides.

Three things enforce that, not one:

  1. The system prompt in `prompts.py` states the role.
  2. `allowed_tools=[]` with no MCP servers registered - there is no function for
     Claude to call, so tool use is not merely discouraged, it is impossible.
  3. A Postgres trigger rejects any change to `clusters.status` outside a
     transaction that has declared itself a human review action.

Claude does not see ground truth either
---------------------------------------
The transaction context assembled here comes from `v_transactions_detector`, the
same ground-truth-free view the detector uses. If Claude could read
`is_synthetic_ring_id`, its case files would be trivially correct and the whole
demonstration would be worthless. Invariant #4 covers the LLM layer too.

Credentials
-----------
The SDK resolves credentials itself, in order: ANTHROPIC_API_KEY (pay-as-you-go,
not used here), CLAUDE_CODE_OAUTH_TOKEN (subscription, headless), then
~/.claude/.credentials.json. Nothing in this module hardcodes a credential
source, so moving between subscription and API billing is a config change only.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AuditActor, AuditLog, CaseFile, SuggestedAction
from app.prompts import PROMPT_VERSION, SUGGESTED_ACTIONS, SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger(__name__)

#: Fallback when Claude returns something unparseable.
FALLBACK_ACTION = "review_closer"


class CaseFileError(RuntimeError):
    """Generation failed. The cluster keeps whatever case file it already had."""


@dataclass
class GenerationOutcome:
    cluster_id: uuid.UUID
    case_file_id: uuid.UUID | None
    created: bool
    reused: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def gather_cluster_context(db: Session, cluster_id: uuid.UUID) -> dict[str, Any]:
    """Collect everything Claude needs about one cluster.

    Reads `v_transactions_detector`, never the base table - Claude must not see
    the evaluation label any more than the detector may.
    """
    cluster = db.execute(
        text(
            "SELECT id, score, status::text AS status, cadence::text AS cadence, "
            "evidence_json, detector_version FROM clusters WHERE id = :cid"
        ),
        {"cid": str(cluster_id)},
    ).mappings().first()
    if cluster is None:
        raise CaseFileError(f"cluster {cluster_id} not found")

    members = db.execute(
        text(
            """
            SELECT e.id, e.type::text AS type, e.external_ref
            FROM cluster_members m
            JOIN entities e ON e.id = m.entity_id
            WHERE m.cluster_id = :cid
            """
        ),
        {"cid": str(cluster_id)},
    ).mappings().all()

    customer_ids = [str(m["id"]) for m in members if m["type"] == "customer"]
    if not customer_ids:
        raise CaseFileError(f"cluster {cluster_id} has no customer members")

    amounts = db.execute(
        text(
            """
            SELECT amount FROM v_transactions_detector
            WHERE customer_entity_id = ANY(:ids)
            """
        ),
        {"ids": customer_ids},
    ).scalars().all()

    timeline = db.execute(
        text(
            """
            SELECT date_trunc('day', created_at)         AS day,
                   count(*)                              AS transactions,
                   count(DISTINCT customer_entity_id)    AS accounts
            FROM v_transactions_detector
            WHERE customer_entity_id = ANY(:ids)
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"ids": customer_ids},
    ).mappings().all()

    amount_summary = {
        "transaction_count": len(amounts),
        "total_paise": sum(amounts) if amounts else 0,
        "min_paise": min(amounts) if amounts else 0,
        "max_paise": max(amounts) if amounts else 0,
        "median_paise": int(statistics.median(amounts)) if amounts else 0,
    }

    return {
        "cluster": dict(cluster),
        "members": [dict(m) for m in members],
        "customer_ids": customer_ids,
        "amount_summary": amount_summary,
        "timeline": [
            {
                "when": row["day"].strftime("%Y-%m-%d"),
                "transactions": row["transactions"],
                "accounts": row["accounts"],
            }
            for row in timeline
        ],
    }


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_case_file_response(raw: str) -> dict[str, Any]:
    """Pull the JSON object out of Claude's reply, tolerantly.

    The prompt asks for bare JSON, but a stray code fence or a sentence before
    the object should degrade to a usable case file rather than an exception.
    """
    text_body = raw.strip()

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_body, re.DOTALL)
    if fenced:
        text_body = fenced.group(1)
    else:
        start, end = text_body.find("{"), text_body.rfind("}")
        if start != -1 and end > start:
            text_body = text_body[start : end + 1]

    try:
        parsed = json.loads(text_body)
    except json.JSONDecodeError as exc:
        raise CaseFileError(f"could not parse Claude's reply as JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise CaseFileError("Claude's reply was not a JSON object")

    action = str(parsed.get("suggested_action", "")).strip()
    if action not in SUGGESTED_ACTIONS:
        log.warning("unexpected suggested_action %r; falling back", action)
        parsed["suggested_action"] = FALLBACK_ACTION

    for field in ("summary", "confidence"):
        if not str(parsed.get(field, "")).strip():
            raise CaseFileError(f"Claude's reply had no {field}")

    for field in ("key_signals", "caveats"):
        value = parsed.get(field)
        if not isinstance(value, list):
            parsed[field] = [str(value)] if value else []
        else:
            parsed[field] = [str(v) for v in value]

    return parsed


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def find_cached(db: Session, cluster_id: uuid.UUID, score: float) -> CaseFile | None:
    """Most recent case file still valid for this cluster.

    A cached file is reused only when it was written by the current prompt
    version AND against the same detector score. Retuning the detector changes
    the score, which correctly invalidates the explanation of it.
    """
    return (
        db.query(CaseFile)
        .filter(
            CaseFile.cluster_id == cluster_id,
            CaseFile.prompt_version == PROMPT_VERSION,
            CaseFile.cluster_score_at_generation == round(score, 6),
        )
        .order_by(CaseFile.generated_at.desc())
        .first()
    )


async def _ask_claude(user_prompt: str) -> tuple[str, str, dict]:
    """Run one turn against the Agent SDK.

    Returns (reply_text, model, telemetry). Telemetry carries the SDK's own
    measured cost and token usage for this call, so cost-per-cluster is an
    observation rather than an estimate.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            query,
        )
    except ImportError as exc:  # pragma: no cover
        raise CaseFileError(
            "claude-agent-sdk is not installed; run pip install -r requirements.txt"
        ) from exc

    from app.config import get_settings

    option_kwargs: dict = {
        "system_prompt": SYSTEM_PROMPT,
        # No tools. Not "tools it should not use" - no tools exist for it to
        # call, so the explain-only boundary is structural, not advisory.
        "allowed_tools": [],
        "max_turns": 1,
    }
    configured_model = get_settings().claude_case_file_model
    if configured_model:
        option_kwargs["model"] = configured_model

    options = ClaudeAgentOptions(**option_kwargs)

    chunks: list[str] = []
    model = ""
    telemetry: dict = {}
    try:
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                model = getattr(message, "model", "") or model
                for block in message.content:
                    piece = getattr(block, "text", None)
                    if piece:
                        chunks.append(piece)
            elif isinstance(message, ResultMessage):
                if getattr(message, "subtype", "") not in ("success", ""):
                    raise CaseFileError(
                        f"Agent SDK returned subtype={message.subtype!r}"
                    )
                telemetry = _telemetry_from(message)
    except CaseFileError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CaseFileError(
            f"Agent SDK call failed ({type(exc).__name__}): {exc}"
        ) from exc

    reply = "".join(chunks).strip()
    if not reply:
        raise CaseFileError("Agent SDK returned an empty reply")
    return reply, model, telemetry


def _telemetry_from(message) -> dict:  # noqa: ANN001 - SDK type
    """Pull measured cost and token usage out of the SDK's ResultMessage.

    Defensive about shape: the SDK reports usage as a dict whose keys have
    varied across versions, so unknown shapes degrade to zeros rather than
    raising. A missing cost number should never fail a case file.
    """
    usage = getattr(message, "usage", None) or {}
    if not isinstance(usage, dict):
        usage = {}

    def _int(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    # Input arrives in three buckets and they are NOT interchangeable for
    # pricing: fresh input, cache writes, and cache reads are each billed at a
    # different rate. Observed on a real call: input_tokens=2 with
    # cache_creation_input_tokens=12785 - reading `input_tokens` alone would
    # under-report the prompt by four orders of magnitude.
    #
    # So the token counts here are INFORMATIONAL. `cost_usd` is the SDK's own
    # measured figure and is the number to trust; it already accounts for the
    # tier mix. Anything costing this out should use cost_usd, not arithmetic
    # over these token counts.
    total_input = (
        _int("input_tokens", "prompt_tokens")
        + _int("cache_creation_input_tokens")
        + _int("cache_read_input_tokens")
    )

    return {
        "cost_usd": float(getattr(message, "total_cost_usd", 0.0) or 0.0),
        "input_tokens": total_input,
        "output_tokens": _int("output_tokens", "completion_tokens"),
        "duration_ms": int(getattr(message, "duration_ms", 0) or 0),
        "usage": usage,
        "model_usage": getattr(message, "model_usage", None) or {},
    }


async def generate_case_file(
    db: Session, cluster_id: uuid.UUID, force: bool = False
) -> GenerationOutcome:
    """Produce (or reuse) the case file for one cluster."""
    context = gather_cluster_context(db, cluster_id)
    cluster = context["cluster"]
    score = float(cluster["score"])

    if not force:
        cached = find_cached(db, cluster_id, score)
        if cached is not None:
            return GenerationOutcome(
                cluster_id=cluster_id,
                case_file_id=cached.id,
                created=False,
                reused=True,
                reason="cached case file still valid for this prompt and score",
            )

    user_prompt = build_user_prompt(
        cluster_id=str(cluster_id),
        score=score,
        cadence=cluster["cadence"],
        size=len(context["customer_ids"]),
        evidence=cluster["evidence_json"] or {},
        timeline=context["timeline"],
        amount_summary=context["amount_summary"],
    )

    reply, model, telemetry = await _ask_claude(user_prompt)
    parsed = parse_case_file_response(reply)

    case_file = CaseFile(
        id=uuid.uuid4(),
        cluster_id=cluster_id,
        summary=str(parsed["summary"]).strip(),
        confidence_note=str(parsed["confidence"]).strip(),
        suggested_action=SuggestedAction(parsed["suggested_action"]),
        key_signals=parsed.get("key_signals", []),
        caveats=parsed.get("caveats", []),
        raw_response=parsed,
        model=model or "unknown",
        prompt_version=PROMPT_VERSION,
        cluster_score_at_generation=round(score, 6),
        detector_version=cluster.get("detector_version") or "",
        generated_at=datetime.now(timezone.utc),
        cost_usd=telemetry.get("cost_usd", 0.0),
        input_tokens=telemetry.get("input_tokens", 0),
        output_tokens=telemetry.get("output_tokens", 0),
        duration_ms=telemetry.get("duration_ms", 0),
        usage_json={
            "usage": telemetry.get("usage", {}),
            "model_usage": telemetry.get("model_usage", {}),
        },
    )
    db.add(case_file)
    db.flush()

    # actor='claude' - invariant #6. Claude's contribution is logged as its own,
    # never attributed to the system or to a human.
    db.add(
        AuditLog(
            actor=AuditActor.claude,
            action="case_file_generated",
            target_type="cluster",
            target_id=str(cluster_id),
            detail_json={
                "case_file_id": str(case_file.id),
                "suggested_action": case_file.suggested_action.value,
                "prompt_version": PROMPT_VERSION,
                "model": case_file.model,
                "cluster_score": score,
                "cost_usd": telemetry.get("cost_usd", 0.0),
                "input_tokens": telemetry.get("input_tokens", 0),
                "output_tokens": telemetry.get("output_tokens", 0),
                "detector_version": case_file.detector_version,
                "note": (
                    "recommendation only; cluster status unchanged and still "
                    "awaiting human review"
                ),
            },
        )
    )

    return GenerationOutcome(
        cluster_id=cluster_id,
        case_file_id=case_file.id,
        created=True,
        reused=False,
    )
