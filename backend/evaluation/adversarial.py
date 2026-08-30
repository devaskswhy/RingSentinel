"""Let a model that did not write the detector design the tests for it.

BLINDSPOTS.md carries a caveat it could not answer on its own: *"the cases share
an author with the detector — they probe the weaknesses we already knew about,
because those are the ones we could think of."* Three hand-written cases cannot
escape that, however carefully they are chosen. So the cases are designed here
by Claude, which has never seen the detector's source and is given only its
published design.

⚠ DEFENSIVE ONLY, AND THE DESIGN ENFORCES IT RATHER THAN PROMISING IT.

  This is red-teaming a detector against itself — the standard way to find
  where your own instrument is blind — and three properties keep it there:

  1. Claude returns a SPECIFICATION, never transactions. It names a shape
     (how many accounts, what they share, how they are paced). This module
     realises it. Nothing the model emits is executed or ingested directly.
  2. The specifications never leave the harness. Cases are inserted, measured
     and rolled back in a `finally`, exactly as `evaluation/blindspots.py` does.
  3. Results are reported as weakness CLASSES and scores. A reproducible recipe
     for defeating the detector is not written to any file this repo publishes.

  What is produced is a measurement of our own blind spots. Nothing here is
  usable as guidance for evading anything, and the prompt asks for coverage of
  a detector's failure modes rather than for ways to beat one.

The model runs with `allowed_tools=[]` and no MCP servers, as everywhere else
in this project: there is no function for it to call even if the prompt were
subverted. It designs; it decides nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import Random

from detection.config import DetectorConfig
from generator.robustness_cases import RobustnessCase, RobustnessTransaction

#: Deterministic realisation: the same specification always yields the same
#: transactions, so a case can be re-run and argued with.
ADVERSARIAL_SEED = 20260902

#: Bounds. A specification outside these is clamped rather than rejected — the
#: model is designing tests, not configuring the system, and a case that would
#: insert a million rows is a mistake rather than an attack.
MAX_ACCOUNTS = 40
MAX_TXNS_PER_ACCOUNT = 60


@dataclass(frozen=True)
class CaseSpec:
    """What Claude returns. A shape, never data."""

    key: str
    title: str
    should_be_flagged: bool
    hypothesis: str
    accounts: int
    shared_instruments: int
    shared_devices: int
    shared_addresses: int
    txns_per_account: int
    window_days: float
    cadence: str  # "agent" | "human" | "irregular"

    @staticmethod
    def from_json(raw: dict) -> "CaseSpec":
        def clamp(v, lo, hi, default):
            try:
                return max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                return default

        key = re.sub(r"[^a-z0-9_]+", "_", str(raw.get("key", "case")).lower())[:40]
        return CaseSpec(
            key=key or "case",
            title=str(raw.get("title", key))[:90],
            should_be_flagged=bool(raw.get("should_be_flagged", True)),
            hypothesis=str(raw.get("hypothesis", ""))[:400],
            accounts=clamp(raw.get("accounts"), 2, MAX_ACCOUNTS, 5),
            shared_instruments=clamp(raw.get("shared_instruments"), 0, 3, 1),
            shared_devices=clamp(raw.get("shared_devices"), 0, 3, 0),
            shared_addresses=clamp(raw.get("shared_addresses"), 0, 3, 0),
            txns_per_account=clamp(raw.get("txns_per_account"), 1, MAX_TXNS_PER_ACCOUNT, 4),
            window_days=float(raw.get("window_days") or 14) or 14.0,
            cadence=str(raw.get("cadence", "human")).lower(),
        )


def _ref(kind: str, case: str, index: int) -> str:
    digest = hashlib.sha256(f"adversarial|{case}|{kind}|{index}".encode()).hexdigest()[:20]
    return f"{kind}_adv_{digest}"


def realise(spec: CaseSpec, window_end: datetime | None = None) -> RobustnessCase:
    """Turn a specification into transactions. THIS module decides the data.

    Claude names a shape; the numbers, timestamps and identifiers are generated
    here from a fixed seed. That boundary is what keeps a model's output from
    being executed rather than merely described.
    """
    rng = Random(f"{ADVERSARIAL_SEED}|{spec.key}")
    end = window_end or datetime.now(timezone.utc)

    instruments = [_ref("inst", spec.key, i) for i in range(spec.shared_instruments)]
    devices = [_ref("dev", spec.key, i) for i in range(spec.shared_devices)]
    addresses = [_ref("addr", spec.key, i) for i in range(spec.shared_addresses)]

    rows: list[RobustnessTransaction] = []
    for a in range(spec.accounts):
        customer = _ref("cust", spec.key, 1000 + a)
        # Anything not shared is the account's own, so an unshared attribute
        # cannot accidentally link two accounts together.
        own_inst = _ref("inst", spec.key, 5000 + a)
        own_dev = _ref("dev", spec.key, 6000 + a)
        own_addr = _ref("addr", spec.key, 7000 + a)

        cursor = end - timedelta(days=spec.window_days)
        for t in range(spec.txns_per_account):
            if spec.cadence == "agent":
                gap = 1.6
            elif spec.cadence == "irregular":
                gap = max(4.0, rng.lognormvariate(5.4, 1.5))
            else:
                gap = max(4.0, rng.lognormvariate(5.0, 1.1))
            span = max(1.0, spec.window_days * 86400 / max(1, spec.txns_per_account))
            cursor += timedelta(seconds=min(span, gap * rng.uniform(1, 60)))

            rows.append(
                RobustnessTransaction(
                    case=spec.key,
                    customer_ref=customer,
                    device_ref=devices[a % len(devices)] if devices else own_dev,
                    address_ref=addresses[a % len(addresses)] if addresses else own_addr,
                    instrument_ref=(
                        instruments[a % len(instruments)] if instruments else own_inst
                    ),
                    amount_paise=rng.randrange(9900, 499900, 100),
                    occurred_at=cursor,
                )
            )

    return RobustnessCase(
        key=spec.key,
        title=spec.title,
        should_be_flagged=spec.should_be_flagged,
        question=spec.hypothesis,
        transactions=tuple(rows),
    )


def build_prompt(config: DetectorConfig, count: int) -> str:
    """The brief given to Claude. Defensive framing is not decoration here."""
    return f"""You are helping test a fraud-ring DETECTOR for blind spots. This is
quality assurance on a defensive system: the goal is to find where our own
detector fails so we can report its limits honestly. Everything you design is
run against our own database and discarded.

You have never seen this detector's source. Here is its published design.

It builds a graph of accounts and the attributes they share (payment
instrument, device, delivery address), finds dense clusters, and scores each
cluster with four weighted signals:

  attribute reuse      {config.weight_attribute_reuse}  how many accounts funnel through one shared
                             attribute, saturating as f(k) = (k-1)/(k-1+{config.reuse_saturation_k})
  timing regularity    {config.weight_timing_regularity}  how metronomic the gaps between transactions
                             are, versus a population baseline
  concentration        {config.weight_concentration}  share of the cluster's volume through the
                             shared attributes
  account shallowness  {config.weight_account_shallowness}  fraction of accounts with almost no history

Attribute type weights: instrument 1.00, device 0.85, address 0.40.
A shared attribute is ignored below {config.min_customers_per_shared_attribute} accounts.
Clusters scoring >= {config.score_threshold} are flagged; >= {config.confident_score_threshold} is "confident".

Design {count} test cases that would be DIFFICULT for this detector to score
correctly. Include both kinds of failure:
  - a real coordinated ring it would MISS (should_be_flagged: true)
  - innocent behaviour it would WRONGLY FLAG (should_be_flagged: false)

Return ONLY a JSON array, no prose, each element exactly:

{{"key": "short_snake_case",
  "title": "Short human title",
  "should_be_flagged": true,
  "hypothesis": "one sentence: which signal this defeats and why",
  "accounts": 6,
  "shared_instruments": 1,
  "shared_devices": 0,
  "shared_addresses": 0,
  "txns_per_account": 4,
  "window_days": 21,
  "cadence": "human"}}

cadence is one of "agent", "human", "irregular". accounts <= {MAX_ACCOUNTS},
txns_per_account <= {MAX_TXNS_PER_ACCOUNT}. Return only the JSON array."""


def parse_specs(text: str) -> list[CaseSpec]:
    """Pull the JSON array out of a model reply, tolerantly.

    The reply may arrive fenced, prefixed, or with trailing commentary despite
    the instruction. A parser that only accepts perfectly clean output would
    fail on a response that is entirely usable.
    """
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.S)
    if fence:
        candidate = fence.group(1).strip()
    start, end = candidate.find("["), candidate.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in the model reply")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("model reply was not a JSON array")
    return [CaseSpec.from_json(item) for item in payload if isinstance(item, dict)]
