"""Have Claude design the blind-spot tests, then run them. Everything rolls back.

    docker compose exec backend python -m scripts.adversarial_cases
    docker compose exec backend python -m scripts.adversarial_cases --count 6

BLINDSPOTS.md carries a caveat it cannot answer for itself: the three
robustness cases share an author with the detector, so they probe weaknesses we
already knew about. This closes that gap by asking a model which has never seen
the detector's source to design the cases from its published description alone.

Defensive only, and structurally so. Claude returns a SPECIFICATION — a shape,
never transactions — which `evaluation/adversarial.py` realises deterministically
in our own code. The cases are inserted through the real ingest path, scored by
the real detector, measured, and rolled back in a `finally`. It runs with
`allowed_tools=[]`: there is no function for it to call.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.db import SessionLocal
from detection.config import DetectorConfig
from evaluation.adversarial import build_prompt, parse_specs, realise
from evaluation.blindspots import measure

OK = "[ok]"


async def _ask(prompt: str) -> tuple[str, str, float]:
    """One turn, no tools. Returns (reply, model, cost_usd)."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        query,
    )

    from app.config import get_settings

    kwargs: dict = {
        "system_prompt": (
            "You design test cases that probe a fraud-detection system for "
            "blind spots, so its limits can be reported honestly. You return "
            "only JSON specifications. You never produce operational guidance."
        ),
        "allowed_tools": [],
        "max_turns": 1,
    }
    model_name = get_settings().claude_case_file_model
    if model_name:
        kwargs["model"] = model_name

    chunks: list[str] = []
    model = ""
    cost = 0.0
    async for message in query(prompt=prompt, options=ClaudeAgentOptions(**kwargs)):
        if isinstance(message, AssistantMessage):
            model = getattr(message, "model", "") or model
            for block in message.content:
                piece = getattr(block, "text", None)
                if piece:
                    chunks.append(piece)
        elif isinstance(message, ResultMessage):
            cost = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
    return "".join(chunks), model, cost


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claude designs blind-spot cases; the real detector runs them."
    )
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument(
        "--show-specs", action="store_true",
        help="Print the specifications Claude returned, before they are run.",
    )
    args = parser.parse_args()

    config = DetectorConfig()

    print("Asking Claude to design cases against the detector's published design.")
    print("It has not seen the source. It returns shapes; this code makes the data.")
    try:
        reply, model, cost = asyncio.run(_ask(build_prompt(config, args.count)))
    except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
        print(f"\nClaude call failed: {exc}")
        print("Run scripts.verify_claude_auth to check the credential path.")
        return 1

    try:
        specs = parse_specs(reply)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCould not parse the reply: {exc}")
        print(reply[:600])
        return 1

    if not specs:
        print("\nClaude returned no usable specifications.")
        return 1

    print(f"  {model or 'claude'} returned {len(specs)} specifications "
          f"(${cost:.4f})")
    if args.show_specs:
        for s in specs:
            print(f"    {s.key}: {s.accounts} accounts, "
                  f"inst={s.shared_instruments} dev={s.shared_devices} "
                  f"addr={s.shared_addresses}, {s.txns_per_account}tx, {s.cadence}, "
                  f"expect_flag={s.should_be_flagged}")

    cases = [realise(spec) for spec in specs]

    db = SessionLocal()
    try:
        print("\nRunning them through the real ingest path and detector…")
        report = measure(db, config, cases=cases)

        print()
        print("=" * 78)
        print("  CASES DESIGNED BY A MODEL THAT DID NOT WRITE THE DETECTOR")
        print("=" * 78)
        print()
        correct = 0
        for outcome, spec in zip(report.outcomes, specs):
            mark = OK if outcome.correct else "[MISS]"
            correct += 1 if outcome.correct else 0
            state = "flagged" if outcome.flagged else "not flagged"
            score = f" at {outcome.score}" if outcome.score else ""
            want = "should flag" if spec.should_be_flagged else "should NOT flag"
            print(f"  {mark:<7} {outcome.case.title[:42]:<44}{want}")
            print(f"          -> {state}{score}")
            if spec.hypothesis:
                print(f"          {spec.hypothesis[:88]}")
        print()
        print(f"  detector handled {correct} of {len(report.outcomes)} correctly")
        print()
        if correct < len(report.outcomes):
            print("  The misses are the point. A case an independent designer")
            print("  found and we did not is exactly what BLINDSPOTS.md said it")
            print("  could not produce on its own.")
        else:
            print("  ⚠ All handled correctly. That is a weaker result than it")
            print("  looks: one round of five cases from one model is not a")
            print("  robustness proof, and the sample says nothing about the")
            print("  weaknesses neither author thought of.")
        print("=" * 78)
        print(f"\n{OK} nothing persisted - every case was rolled back")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
