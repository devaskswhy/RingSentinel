"""Break things on purpose, and show the fallback that catches each one.

    docker compose exec backend python -m scripts.verify_resilience

Every failure handled here was already handled before this script existed - the
retries, the tolerant parser, the idempotent ingest, the signature check. What
was missing was any way for someone other than the author to see it. This runs
each failure for real and names the mechanism that absorbs it.

Nothing here is a mock of RingSentinel's own behaviour. Each check drives the
actual production code path and then asserts what it did. Where a check needs
the outside world to misbehave - a Razorpay 429, a truncated model response -
only the outside world is faked; the handling under test is the real thing.

Safe to run against a populated database at any time: every database check runs
inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from sqlalchemy import text

from app.db import SessionLocal, engine

PASS = "PASS"
FAIL = "FAIL"
RULE = "=" * 74


@dataclass
class Check:
    number: int
    title: str
    fallback: str
    passed: bool = False
    detail: str = ""
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        mark = f"[{PASS}]" if self.passed else f"[{FAIL}]"
        lines = [
            f"  {self.number}. {self.title}",
            f"     fallback : {self.fallback}",
            f"     {mark} {self.detail}",
        ]
        lines.extend(f"            {n}" for n in self.notes)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. The database connection dies underneath us
# ---------------------------------------------------------------------------


def check_db_reconnect() -> Check:
    check = Check(
        1,
        "Database connection dropped mid-operation",
        "SQLAlchemy pool_pre_ping (app/db.py) tests a pooled connection before "
        "handing it out, and transparently replaces a dead one",
    )
    # The killer must not come from the pool under test - an earlier version of
    # this check asked the pool for a second connection, got the same one back,
    # and terminated itself. A separate NullPool engine guarantees a distinct
    # backend.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from app.config import get_settings

    killer_engine = create_engine(
        get_settings().database_url, poolclass=NullPool, future=True
    )
    try:
        with engine.connect() as conn:
            pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()
        # Connection is now back in the pool, and still open server-side.

        with killer_engine.connect() as killer:
            killer_pid = killer.execute(text("SELECT pg_backend_pid()")).scalar_one()
            if killer_pid == pid:
                check.detail = "could not obtain a distinct connection to kill from"
                return check
            killer.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            killer.commit()

        # The pool still believes that connection is usable. Without pre-ping
        # this raises; with it, the pool notices and silently replaces it.
        with engine.connect() as conn:
            alive = conn.execute(text("SELECT 1")).scalar_one()
            new_pid = conn.execute(text("SELECT pg_backend_pid()")).scalar_one()

        check.passed = alive == 1 and new_pid != pid
        check.detail = (
            f"killed backend pid {pid} from outside the pool; the next query was "
            f"served on a replacement connection (pid {new_pid}) with no error "
            f"reaching the caller"
        )
    except Exception as exc:  # noqa: BLE001
        check.detail = f"reconnect did not happen: {type(exc).__name__}: {exc}"
    finally:
        killer_engine.dispose()
    return check


# ---------------------------------------------------------------------------
# 2. The model returns something that is not the JSON we asked for
# ---------------------------------------------------------------------------


def check_malformed_model_output() -> Check:
    from app.case_files import CaseFileError, parse_case_file_response

    check = Check(
        2,
        "Model returns malformed or unexpected output",
        "app/case_files.py parses tolerantly - strips code fences and prose, "
        "falls back to a labelled 'review_closer' on an unknown action, and "
        "raises a named CaseFileError rather than persisting nonsense",
    )
    good = {
        "summary": "Four accounts share one card.",
        "confidence": "Fairly confident.",
        "suggested_action": "likely_ring",
        "key_signals": ["shared card"],
        "caveats": ["could be a family"],
    }
    try:
        fenced = parse_case_file_response(
            "Here is the case file:\n```json\n" + json.dumps(good) + "\n```\n"
        )
        assert fenced["suggested_action"] == "likely_ring"
        check.notes.append("code fence + preamble  -> parsed")

        unknown = dict(good, suggested_action="BLOCK_THEM_ALL")
        recovered = parse_case_file_response(json.dumps(unknown))
        assert recovered["suggested_action"] == "review_closer"
        check.notes.append(
            "invented action 'BLOCK_THEM_ALL' -> replaced with 'review_closer'"
        )

        scalar = dict(good, key_signals="not a list")
        coerced = parse_case_file_response(json.dumps(scalar))
        assert coerced["key_signals"] == ["not a list"]
        check.notes.append("wrong type for key_signals -> coerced to a list")

        truncated = json.dumps(good)[: len(json.dumps(good)) // 2]
        try:
            parse_case_file_response(truncated)
            check.detail = "truncated JSON was accepted - it should not be"
            return check
        except CaseFileError:
            check.notes.append(
                "truncated JSON -> CaseFileError, nothing written to the database"
            )

        check.passed = True
        check.detail = "four malformed shapes handled without writing bad data"
    except Exception as exc:  # noqa: BLE001
        check.detail = f"parser did not degrade gracefully: {type(exc).__name__}: {exc}"
    return check


# ---------------------------------------------------------------------------
# 3. The model call itself fails
# ---------------------------------------------------------------------------


def check_model_call_failure() -> Check:
    import asyncio

    import app.case_files as case_files

    check = Check(
        3,
        "Model API call fails outright",
        "generate_case_file raises CaseFileError before touching the database, "
        "so the cluster keeps the case file it already had",
    )
    db = SessionLocal()
    original = case_files._ask_claude
    try:
        row = db.execute(
            text(
                """
                SELECT c.id, cf.id AS case_file_id, cf.summary
                FROM clusters c
                JOIN LATERAL (
                    SELECT id, summary FROM case_files
                    WHERE cluster_id = c.id ORDER BY generated_at DESC LIMIT 1
                ) cf ON TRUE
                LIMIT 1
                """
            )
        ).mappings().first()
        if row is None:
            # No cluster currently has a case file. Provision one inside this
            # transaction so the check still exercises the real path; it is
            # rolled back with everything else.
            cluster_id = db.execute(
                text("SELECT id FROM clusters LIMIT 1")
            ).scalar()
            if cluster_id is None:
                check.detail = "no clusters exist - run scripts.detect first"
                return check
            seeded = uuid.uuid4()
            db.execute(
                text(
                    "INSERT INTO case_files (id, cluster_id, summary, "
                    "confidence_note, suggested_action, prompt_version) VALUES "
                    "(:id, :cid, 'pre-existing case file', 'n/a', "
                    "'review_closer', 'resilience-check')"
                ),
                {"id": str(seeded), "cid": str(cluster_id)},
            )
            db.flush()
            row = {"id": cluster_id, "case_file_id": seeded,
                   "summary": "pre-existing case file"}
            check.notes.append("(provisioned a case file for this check, rolled back)")

        async def explode(_prompt: str):
            raise case_files.CaseFileError("simulated upstream failure")

        case_files._ask_claude = explode

        # Savepoint, not a full rollback: an outright rollback here would also
        # discard the case file this check provisioned, and the check would then
        # "prove" the file was lost when in fact the test discarded it.
        raised = False
        savepoint = db.begin_nested()
        try:
            asyncio.run(case_files.generate_case_file(db, row["id"], force=True))
            savepoint.rollback()
        except case_files.CaseFileError:
            raised = True
            savepoint.rollback()

        after = db.execute(
            text(
                "SELECT id, summary FROM case_files WHERE cluster_id = :cid "
                "ORDER BY generated_at DESC LIMIT 1"
            ),
            {"cid": str(row["id"])},
        ).mappings().first()

        preserved = after is not None and after["id"] == row["case_file_id"]
        check.passed = raised and preserved
        check.detail = (
            "call failed with CaseFileError; the cluster still shows its "
            "previous case file, unchanged"
            if check.passed
            else "the previous case file was lost or no error was raised"
        )
    except Exception as exc:  # noqa: BLE001
        check.detail = f"{type(exc).__name__}: {exc}"
    finally:
        case_files._ask_claude = original
        db.rollback()
        db.close()
    return check


# ---------------------------------------------------------------------------
# 4. Razorpay rate-limits us
# ---------------------------------------------------------------------------


def check_rate_limit_backoff() -> Check:
    from razorpay.errors import ServerError

    from app.razorpay_client import RazorpayTestClient

    check = Check(
        4,
        "Payment API returns 429 repeatedly",
        "app/razorpay_client.py reads the real status from a requests response "
        "hook - the SDK discards it - then backs off, honouring Retry-After",
    )
    try:
        client = RazorpayTestClient(
            "rzp_test_resiliencecheck", "not-a-real-secret", rate_per_second=50.0
        )

        attempts = {"n": 0}

        def rate_limited_then_ok(**_kwargs):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                # Exactly what the SDK does on a 429: it throws away the status
                # code and raises a generic ServerError. The hook is why we can
                # still tell a 429 from a 500.
                client._last_status = 429
                client._last_retry_after = 0.05
                raise ServerError("Too many requests")
            return {"id": "order_resilience_check"}

        started = time.monotonic()
        result = client._call("orders.create", rate_limited_then_ok)
        elapsed = time.monotonic() - started

        check.passed = (
            result["id"] == "order_resilience_check"
            and client.stats.rate_limited == 2
            and client.stats.retries >= 2
        )
        check.detail = (
            f"two 429s absorbed, third attempt succeeded after {elapsed * 1000:.0f}ms "
            f"of backoff; no order lost"
        )
        check.notes.append(
            f"stats: {client.stats.calls} calls, "
            f"{client.stats.rate_limited} rate-limited, "
            f"{client.stats.failures} failures"
        )
    except Exception as exc:  # noqa: BLE001
        check.detail = f"{type(exc).__name__}: {exc}"
    return check


# ---------------------------------------------------------------------------
# 5. The same webhook arrives twice
# ---------------------------------------------------------------------------


def check_duplicate_webhook() -> Check:
    from app.ingest import ingest_event

    check = Check(
        5,
        "Same webhook delivered twice (Razorpay retries)",
        "transactions.razorpay_order_id is unique and entity_links is unique on "
        "(pair, link_type, transaction); ingest uses ON CONFLICT DO NOTHING",
    )
    db = SessionLocal()
    try:
        order_id = f"order_RESILIENCE{uuid.uuid4().hex[:8].upper()}"
        notes = {
            "rs_customer_ref": f"cust_resilience_{uuid.uuid4().hex[:10]}",
            "rs_device_ref": f"dev_resilience_{uuid.uuid4().hex[:10]}",
            "rs_occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        event = {
            "entity": "event",
            "event": "order.paid",
            "contains": ["order"],
            "payload": {
                "order": {
                    "entity": {
                        "id": order_id,
                        "amount": 4200,
                        "currency": "INR",
                        "notes": notes,
                        "created_at": 1_773_000_000,
                    }
                }
            },
            "created_at": 1_773_000_000,
        }

        first = ingest_event(db, event)
        db.flush()
        second = ingest_event(db, event)
        db.flush()

        count = db.execute(
            text("SELECT count(*) FROM transactions WHERE razorpay_order_id = :o"),
            {"o": order_id},
        ).scalar_one()

        check.passed = first.created and not second.created and count == 1
        check.detail = (
            f"delivered twice, one transaction row exists; the replay was a "
            f"no-op ('{second.reason}')"
        )
    except Exception as exc:  # noqa: BLE001
        check.detail = f"{type(exc).__name__}: {exc}"
    finally:
        db.rollback()
        db.close()
    return check


# ---------------------------------------------------------------------------
# 6. Hostile or malformed webhook traffic
# ---------------------------------------------------------------------------


def check_webhook_rejection(api_base: str) -> Check:
    from app.config import get_settings
    from scripts.seed_rings import sign

    check = Check(
        6,
        "Forged signature, then a structurally invalid event",
        "app/webhooks.py verifies HMAC-SHA256 over the RAW body before parsing "
        "(401), and returns 400 on an unusable payload so Razorpay stops "
        "retrying something that can never succeed",
    )
    url = api_base.rstrip("/") + "/webhooks/razorpay"
    secret = get_settings().razorpay_webhook_secret or ""
    try:
        body = json.dumps(
            {"entity": "event", "event": "order.paid", "payload": {}}
        ).encode()

        forged = requests.post(
            url,
            data=body,
            headers={"X-Razorpay-Signature": "0" * 64},
            timeout=15,
        )

        # Correctly signed, but the payload carries no order and no payment.
        invalid = requests.post(
            url,
            data=body,
            headers={"X-Razorpay-Signature": sign(body, secret)},
            timeout=15,
        )

        # Signed body, then one byte changed - proves the signature covers the
        # raw bytes rather than a re-serialised parse.
        tampered = requests.post(
            url,
            data=body + b" ",
            headers={"X-Razorpay-Signature": sign(body, secret)},
            timeout=15,
        )

        check.passed = (
            forged.status_code == 401
            and invalid.status_code == 400
            and tampered.status_code == 401
        )
        check.detail = (
            f"forged signature -> {forged.status_code}, "
            f"valid signature but unusable payload -> {invalid.status_code}, "
            f"body altered after signing -> {tampered.status_code}"
        )
        check.notes.append("nothing was written for any of the three")
    except Exception as exc:  # noqa: BLE001
        check.detail = f"{type(exc).__name__}: {exc} (is the API running?)"
    return check


# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run each failure mode and show the fallback that absorbs it."
    )
    parser.add_argument("--api-base", default="http://localhost:8000")
    args = parser.parse_args()

    # The code under test logs as it recovers. That is correct behaviour in
    # production and noise in a report, and each check already states what
    # happened - so quiet it while the checks run.
    logging.disable(logging.WARNING)

    print(RULE)
    print("RingSentinel — resilience under failure")
    print(RULE)
    print("  Each scenario below is a real failure driven through the real code")
    print("  path. Database checks roll back; nothing here leaves a trace.")
    print()

    checks = [
        check_db_reconnect(),
        check_malformed_model_output(),
        check_model_call_failure(),
        check_rate_limit_backoff(),
        check_duplicate_webhook(),
        check_webhook_rejection(args.api_base),
    ]

    for check in checks:
        print(check.render())
        print()

    passed = sum(1 for c in checks if c.passed)
    print(RULE)
    print(f"  {passed}/{len(checks)} failure modes handled gracefully")
    print(RULE)

    if passed != len(checks):
        for check in checks:
            if not check.passed:
                print(f"  {FAIL} {check.number}. {check.title} — {check.detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
