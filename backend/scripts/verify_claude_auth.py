"""Verify the Claude Agent SDK can authenticate before Phase 4 depends on it.

RingSentinel's case-file writer (Phase 4) runs on the Claude Agent SDK. The SDK
does not take an API key directly - it launches a bundled Claude Code binary as
a subprocess, and that subprocess resolves credentials in this order:

  1. ANTHROPIC_API_KEY            - pay-as-you-go billing
  2. CLAUDE_CODE_OAUTH_TOKEN      - long-lived subscription token
                                    (generate with: claude setup-token)
  3. ~/.claude/.credentials.json  - the interactive `claude` login on this host

Paths 2 and 3 both bill against a Claude subscription rather than API credit,
which is what this project wants for local development and the demo.

Run it with:  python -m scripts.verify_claude_auth
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PROMPT = "Reply with exactly the word: RINGSENTINEL_AUTH_OK"


def describe_credential_source() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY (pay-as-you-go API billing)"
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return "CLAUDE_CODE_OAUTH_TOKEN (subscription OAuth, headless)"

    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists():
        try:
            data = json.loads(creds.read_text())
            oauth = data.get("claudeAiOauth", {})
            plan = oauth.get("subscriptionType", "unknown")
            return f"~/.claude/.credentials.json (subscription OAuth, plan={plan})"
        except (OSError, json.JSONDecodeError):
            return "~/.claude/.credentials.json (present but unreadable)"

    return "NONE FOUND"


async def run_probe() -> int:
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            query,
        )
    except ImportError:
        print("[FAIL] claude-agent-sdk is not installed.")
        print("       pip install -r requirements.txt")
        return 1

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=1,
        system_prompt="Answer with the exact string requested. Nothing else.",
    )

    reply_parts: list[str] = []
    result_subtype: str | None = None

    try:
        async for message in query(prompt=PROMPT, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    text = getattr(block, "text", None)
                    if text:
                        reply_parts.append(text)
            elif isinstance(message, ResultMessage):
                result_subtype = message.subtype
    except Exception as exc:  # noqa: BLE001 - report any auth/transport failure
        print(f"[FAIL] Agent SDK call raised {type(exc).__name__}: {exc}")
        return 1

    reply = "".join(reply_parts).strip()
    print(f"  result   : {result_subtype}")
    print(f"  reply    : {reply!r}")

    if "RINGSENTINEL_AUTH_OK" in reply:
        print("\n[ok] Claude Agent SDK authenticated and responding.")
        return 0

    print("\n[FAIL] SDK responded but not with the expected token.")
    return 1


def main() -> int:
    print("RingSentinel - Claude Agent SDK auth check\n")
    source = describe_credential_source()
    print(f"  credential source: {source}")

    if source == "NONE FOUND":
        print("\n[FAIL] No Claude credentials available.")
        print("       Run `claude setup-token` and export CLAUDE_CODE_OAUTH_TOKEN,")
        print("       or log in interactively with `claude`.")
        return 1

    print()
    return asyncio.run(run_probe())


if __name__ == "__main__":
    sys.exit(main())
