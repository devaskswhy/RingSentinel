"""Phase 2 seed: plan a synthetic corpus, create it at Razorpay, ingest it.

    docker compose exec backend python -m scripts.seed_rings --help

Pipeline per transaction:

    plan row  ->  REAL Razorpay test-mode order (or payment link)
              ->  webhook envelope built from the real API response
              ->  HMAC-signed and POSTed to /webhooks/razorpay
              ->  entities / entity_links / transactions

The generator never touches Postgres. Everything arrives through the same
webhook path production would use.

An honest note about the payment leg
------------------------------------
Razorpay's Payments API cannot create payments - the docs are explicit that it
exists "only to retrieve payment details or change the status from authorized to
captured and not to collect payments". Real payments originate from Checkout in
a browser, or from S2S endpoints that require per-account enablement.

So: every **order** in this corpus is a genuine Razorpay test-mode record with a
real `order_...` id you can fetch back from the API. The payment entity attached
to the emitted `order.paid` event is synthesized locally and is flagged as such
(`synthesized: true`) inside the event. Nothing in the graph depends on it - the
ingest keys off the real order.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
from collections import Counter
from typing import Any

import requests
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine
from app.ingest import ingest_event
from app.razorpay_client import LiveKeyRefused, RazorpayTestClient
from generator.config import GeneratorConfig
from generator.plan import build_plan
from generator.planned import INTENT_PAYMENT_LINK, PlannedTransaction

OK = "[ok]"
FAIL = "[FAIL]"
WARN = "[warn]"


# ---------------------------------------------------------------------------
# Event construction
# ---------------------------------------------------------------------------


def build_order_paid_event(
    order: dict[str, Any], row: PlannedTransaction
) -> dict[str, Any]:
    """Wrap a real Razorpay order in an order.paid envelope.

    The order entity is exactly what Razorpay returned. The payment entity is
    synthesized - see the module docstring - and marked so nobody later mistakes
    it for a real captured payment.
    """
    now = int(time.time())
    return {
        "entity": "event",
        "account_id": "acc_ringsentinel_test",
        "event": "order.paid",
        "contains": ["payment", "order"],
        "payload": {
            "order": {"entity": order},
            "payment": {
                "entity": {
                    "id": f"pay_synthetic_{row.seq:07d}",
                    "entity": "payment",
                    "amount": order.get("amount", row.amount_paise),
                    "currency": order.get("currency", row.currency),
                    "status": "captured",
                    "order_id": order.get("id"),
                    "created_at": now,
                    "notes": order.get("notes", {}),
                    # Explicitly not a real Razorpay payment record.
                    "synthesized": True,
                }
            },
        },
        "created_at": now,
    }


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class WebhookDelivery:
    """Delivers signed events to the running API - the real ingestion path."""

    def __init__(self, api_base: str, secret: str, timeout: float = 30.0) -> None:
        self.url = api_base.rstrip("/") + "/webhooks/razorpay"
        self.secret = secret
        self.timeout = timeout
        self.session = requests.Session()

    def deliver(self, event: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(event, separators=(",", ":")).encode("utf-8")
        response = self.session.post(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sign(body, self.secret),
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"webhook returned {response.status_code}: {response.text[:300]}"
            )
        return response.json()

    def preflight(self) -> None:
        health = self.url.rsplit("/webhooks/", 1)[0] + "/health"
        response = self.session.get(health, timeout=10)
        response.raise_for_status()


class DirectDelivery:
    """Calls the ingest function in-process.

    Same code path as the webhook route minus HTTP and signature verification.
    For running the seed when the API container is not up.
    """

    def __init__(self) -> None:
        self.session = SessionLocal()

    def deliver(self, event: dict[str, Any]) -> dict[str, Any]:
        result = ingest_event(self.session, event)
        self.session.commit()
        return {"created": result.created, "order_id": result.order_id}

    def preflight(self) -> None:
        self.session.execute(text("SELECT 1"))


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def reset_corpus() -> None:
    """Clear graph data so a re-run does not stack a second corpus on top.

    audit_log is deliberately NOT touched - it is append-only by trigger and
    clearing it would violate CLAUDE.md invariant #3.
    """
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM entity_links"))
        conn.execute(text("DELETE FROM cluster_members"))
        conn.execute(text("DELETE FROM clusters"))
        conn.execute(text("DELETE FROM transactions"))
        conn.execute(text("DELETE FROM entities"))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_against_plan(sent_order_ids: list[str]) -> list[str]:
    """Confirm Postgres reflects exactly the orders we actually sent."""
    problems: list[str] = []
    with engine.begin() as conn:
        in_db = set(
            conn.execute(text("SELECT razorpay_order_id FROM transactions")).scalars()
        )
        missing = [oid for oid in sent_order_ids if oid not in in_db]
        if missing:
            problems.append(
                f"{len(missing)} orders created at Razorpay never reached Postgres "
                f"(e.g. {missing[:3]})"
            )

        real_prefix = conn.execute(
            text(
                "SELECT count(*) FROM transactions WHERE razorpay_order_id NOT LIKE 'order_%'"
            )
        ).scalar_one()
        if real_prefix:
            problems.append(
                f"{real_prefix} transactions do not carry a real Razorpay order id"
            )

        orphan_links = conn.execute(
            text(
                """
                SELECT count(*) FROM entity_links el
                LEFT JOIN transactions t ON t.id = el.transaction_id
                WHERE t.id IS NULL
                """
            )
        ).scalar_one()
        if orphan_links:
            problems.append(f"{orphan_links} entity_links reference no transaction")
    return problems


def print_corpus_report() -> None:
    with engine.begin() as conn:
        totals = conn.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM entities)     AS entities,
                    (SELECT count(*) FROM entity_links) AS links,
                    (SELECT count(*) FROM transactions) AS transactions
                """
            )
        ).mappings().one()
        print("\nIn Postgres:")
        print(f"  entities      : {totals['entities']}")
        print(f"  entity_links  : {totals['links']}")
        print(f"  transactions  : {totals['transactions']}")

        print("\n  entities by type:")
        for row in conn.execute(
            text("SELECT type::text AS t, count(*) c FROM entities GROUP BY 1 ORDER BY 1")
        ).mappings():
            print(f"    {row['t']:<12} {row['c']:>5}")

        print("\n  links by type:")
        for row in conn.execute(
            text(
                "SELECT link_type::text AS t, count(*) c FROM entity_links "
                "GROUP BY 1 ORDER BY 1"
            )
        ).mappings():
            print(f"    {row['t']:<20} {row['c']:>5}")

        print("\n  seeded rings (ground truth):")
        print(f"    {'ring':<9}{'pattern':<15}{'cadence':<9}{'split':<9}{'txns':>6}{'accts':>7}")
        for row in conn.execute(
            text(
                """
                SELECT split_part(is_synthetic_ring_id,'|',1) ring,
                       split_part(is_synthetic_ring_id,'|',2) pattern,
                       split_part(is_synthetic_ring_id,'|',3) cadence,
                       split_part(is_synthetic_ring_id,'|',4) split,
                       count(*) txns,
                       count(DISTINCT customer_entity_id) accts
                FROM transactions
                WHERE is_synthetic_ring_id IS NOT NULL
                GROUP BY 1,2,3,4 ORDER BY 1
                """
            )
        ).mappings():
            marker = "  <- HELD OUT" if row["split"] == "holdout" else ""
            print(
                f"    {row['ring']:<9}{row['pattern']:<15}{row['cadence']:<9}"
                f"{row['split']:<9}{row['txns']:>6}{row['accts']:>7}{marker}"
            )

        normal = conn.execute(
            text(
                "SELECT count(*) FROM transactions WHERE is_synthetic_ring_id IS NULL"
            )
        ).scalar_one()
        print(f"\n    normal (unlabelled) transactions: {normal}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed RingSentinel with a synthetic fraud-ring corpus "
        "backed by real Razorpay test-mode orders."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="only process the first N rows"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="plan only; make no Razorpay calls and write nothing",
    )
    parser.add_argument(
        "--deliver",
        choices=("webhook", "direct"),
        default="webhook",
        help="webhook (default, the real path) or in-process ingest",
    )
    parser.add_argument(
        "--api-base", default="http://localhost:8000", help="API base URL"
    )
    parser.add_argument(
        "--rate", type=float, default=4.0, help="max Razorpay calls per second"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="clear existing graph data first (audit_log is never touched)",
    )
    parser.add_argument("--seed", type=int, default=None, help="override random seed")
    args = parser.parse_args()

    settings = get_settings()
    config = GeneratorConfig(seed=args.seed) if args.seed else GeneratorConfig()

    print("RingSentinel Phase 2 seed")
    print(f"  {config.describe()}\n")

    plan = build_plan(config)
    rows = list(plan.transactions)
    if args.limit:
        rows = rows[: args.limit]

    print("Planned corpus:")
    for line in plan.summary_lines():
        print(f"  {line}")
    if args.limit:
        print(f"\n  --limit {args.limit}: processing {len(rows)} of "
              f"{len(plan.transactions)} planned rows")

    if args.dry_run:
        print(f"\n{OK} dry run - no Razorpay calls made, nothing written.")
        return 0

    # ---- Credentials -----------------------------------------------------
    try:
        client = RazorpayTestClient(
            settings.razorpay_key_id or "",
            settings.razorpay_key_secret or "",
            rate_per_second=args.rate,
        )
    except LiveKeyRefused as exc:
        print(f"\n{FAIL} {exc}")
        print("\n  Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env.")
        print("  Razorpay Dashboard -> Test Mode -> Account & Settings -> API Keys")
        return 2

    if args.deliver == "webhook" and not settings.razorpay_webhook_secret:
        print(f"\n{FAIL} RAZORPAY_WEBHOOK_SECRET is not set.")
        print("  The webhook receiver refuses unverified events. Set any value")
        print("  locally (the seed signs with the same secret), or use")
        print("  --deliver direct to bypass HTTP.")
        return 2

    delivery = (
        WebhookDelivery(args.api_base, settings.razorpay_webhook_secret or "")
        if args.deliver == "webhook"
        else DirectDelivery()
    )

    try:
        delivery.preflight()
    except Exception as exc:  # noqa: BLE001
        print(f"\n{FAIL} delivery preflight failed: {exc}")
        if args.deliver == "webhook":
            print(f"  Is the API up at {args.api_base}? Try: docker compose up -d")
        return 2

    if args.reset:
        print(f"\n{WARN} --reset: clearing existing graph data (audit_log preserved)")
        reset_corpus()

    # ---- Execute ---------------------------------------------------------
    print(f"\nCreating {len(rows)} real Razorpay test-mode records "
          f"at <= {args.rate}/s and ingesting via {args.deliver}...\n")

    started = time.monotonic()
    sent_order_ids: list[str] = []
    ingested = 0
    duplicates = 0
    failures: list[str] = []
    intents = Counter()

    for index, row in enumerate(rows, start=1):
        try:
            if row.intent == INTENT_PAYMENT_LINK:
                link = client.create_payment_link(
                    amount_paise=row.amount_paise,
                    currency=row.currency,
                    reference_id=row.receipt,
                    notes=row.razorpay_notes(),
                )
                intents["payment_link"] += 1
                # A payment link carries its own order once paid; for graph
                # purposes we still need an order record, so create one too.
                order = client.create_order(
                    amount_paise=row.amount_paise,
                    currency=row.currency,
                    receipt=row.receipt,
                    notes={**row.razorpay_notes(), "rs_plink": str(link.get("id", ""))[:256]},
                )
            else:
                order = client.create_order(
                    amount_paise=row.amount_paise,
                    currency=row.currency,
                    receipt=row.receipt,
                    notes=row.razorpay_notes(),
                )
                intents["order"] += 1

            sent_order_ids.append(order["id"])

            result = delivery.deliver(build_order_paid_event(order, row))
            if result.get("created"):
                ingested += 1
            else:
                duplicates += 1

        except Exception as exc:  # noqa: BLE001 - one bad row must not kill the run
            failures.append(f"seq={row.seq}: {type(exc).__name__}: {exc}")
            if len(failures) >= 25:
                print(f"\n{FAIL} 25 consecutive-ish failures; stopping early.")
                break

        if index % 100 == 0 or index == len(rows):
            elapsed = time.monotonic() - started
            rate = index / elapsed if elapsed else 0
            print(
                f"  {index:>5}/{len(rows)}  ingested={ingested:<5} "
                f"dup={duplicates:<4} fail={len(failures):<4} "
                f"{rate:5.1f}/s  elapsed={elapsed:6.1f}s"
            )

    elapsed = time.monotonic() - started

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 66)
    print("SEED SUMMARY")
    print("=" * 66)
    print(f"  rows processed        : {len(sent_order_ids) + len(failures)}")
    print(f"  Razorpay API calls    : {client.stats.calls}")
    print(f"    orders created      : {intents['order']}")
    print(f"    payment links       : {intents['payment_link']}")
    print(f"    retries             : {client.stats.retries}")
    print(f"    429 rate-limited    : {client.stats.rate_limited}")
    print(f"  transactions ingested : {ingested}")
    print(f"  duplicates skipped    : {duplicates}")
    print(f"  failures              : {len(failures)}")
    print(f"  elapsed               : {elapsed:.1f}s")

    if failures:
        print("\n  first failures:")
        for line in failures[:5]:
            print(f"    - {line}")

    print_corpus_report()

    problems = verify_against_plan(sent_order_ids)
    print()
    if problems:
        print(f"{FAIL} verification found {len(problems)} problem(s):")
        for problem in problems:
            print(f"   - {problem}")
        return 1

    print(f"{OK} every Razorpay order created is present in Postgres.")
    print(f"{OK} rings 09-12 are held out - do not tune against them.")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
