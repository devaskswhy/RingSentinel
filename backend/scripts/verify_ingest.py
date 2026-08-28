"""Self-test for the ingestion pipeline. Writes nothing permanent.

Every assertion runs inside a transaction that is rolled back at the end, so
this can be run against a populated database at any time without polluting the
corpus - and without inserting transactions that lack a real Razorpay order id.

What it proves:
  1. one event -> one customer + its attribute entities + one edge each
  2. re-delivering the same event is a no-op (Razorpay retries webhooks)
  3. two accounts on the same device converge on ONE device entity - the ring
     signal the whole product depends on
  4. edges honour the canonical entity_id_a < entity_id_b ordering
  5. the ground-truth label lands in transactions.is_synthetic_ring_id
  6. v_transactions_detector does NOT expose that label
  7. the synthetic event time survives the round trip, so cadence is preserved

Run:  docker compose exec backend python -m scripts.verify_ingest
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.db import SessionLocal
from app.ingest import ingest_event

OK = "[ok]"
FAIL = "[FAIL]"

FIXED_TIME = datetime(2026, 3, 14, 9, 26, 53, tzinfo=timezone.utc)


def make_event(
    order_id: str,
    customer: str,
    device: str | None = None,
    address: str | None = None,
    instrument: str | None = None,
    ring_label: str | None = None,
    amount: int = 12345,
    event_name: str = "order.paid",
) -> dict[str, Any]:
    notes: dict[str, str] = {
        "rs_customer_ref": customer,
        "rs_occurred_at": FIXED_TIME.isoformat(),
        "rs_archetype": "selftest",
        "rs_split": "selftest",
    }
    if device:
        notes["rs_device_ref"] = device
    if address:
        notes["rs_address_ref"] = address
    if instrument:
        notes["rs_instrument_ref"] = instrument
    if ring_label:
        notes["rs_ring_label"] = ring_label

    order = {
        "id": order_id,
        "entity": "order",
        "amount": amount,
        "currency": "INR",
        "status": "paid",
        "notes": notes,
        "created_at": 1_773_000_000,
    }
    payload: dict[str, Any] = {"order": {"entity": order}}
    if event_name == "payment.captured":
        payload = {
            "payment": {
                "entity": {
                    "id": f"pay_{order_id[-8:]}",
                    "entity": "payment",
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": order_id,
                    "notes": notes,
                    "created_at": 1_773_000_000,
                }
            }
        }
    return {
        "entity": "event",
        "account_id": "acc_selftest",
        "event": event_name,
        "contains": list(payload.keys()),
        "payload": payload,
        "created_at": 1_773_000_000,
    }


def main() -> int:  # noqa: C901 - a linear checklist reads better flat here
    problems: list[str] = []
    db = SessionLocal()

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  {OK} {label}")
        else:
            print(f"  {FAIL} {label}{(' - ' + detail) if detail else ''}")
            problems.append(label)

    try:
        print("Ingest pipeline self-test (rolled back at the end)\n")

        # -- 1. basic shape ------------------------------------------------
        print("Single event:")
        ev = make_event(
            "order_SELFTEST0001",
            "cust_selftest_a",
            device="dev_selftest_shared",
            address="addr_selftest_a",
            instrument="inst_selftest_a",
            ring_label="ring_99|selftest|agent|tuning",
        )
        r1 = ingest_event(db, ev)
        db.flush()
        check("transaction created", r1.created)
        check("4 entities created", r1.entities_created == 4, f"got {r1.entities_created}")
        check("3 edges created", r1.links_created == 3, f"got {r1.links_created}")

        # -- 2. idempotency ------------------------------------------------
        print("\nRedelivery (Razorpay retries webhooks):")
        r2 = ingest_event(db, ev)
        db.flush()
        check("second delivery is a no-op", not r2.created)
        check("no duplicate entities", r2.entities_created == 0)
        check("no duplicate edges", r2.links_created == 0)
        count = db.execute(
            text(
                "SELECT count(*) FROM transactions WHERE razorpay_order_id = "
                "'order_SELFTEST0001'"
            )
        ).scalar_one()
        check("exactly one transaction row", count == 1, f"got {count}")

        # -- 3. convergence: the ring signal --------------------------------
        print("\nTwo accounts sharing one device:")
        ev2 = make_event(
            "order_SELFTEST0002",
            "cust_selftest_b",
            device="dev_selftest_shared",  # same device as account A
            address="addr_selftest_b",
            instrument="inst_selftest_b",
        )
        r3 = ingest_event(db, ev2)
        db.flush()
        check("device entity reused, not duplicated", r3.entities_created == 3,
              f"got {r3.entities_created} (expected 3: customer+address+instrument)")

        shared = db.execute(
            text(
                "SELECT count(*) FROM entities WHERE external_ref = 'dev_selftest_shared'"
            )
        ).scalar_one()
        check("exactly one shared device entity", shared == 1, f"got {shared}")

        neighbours = db.execute(
            text(
                """
                SELECT count(DISTINCT t.customer_entity_id)
                FROM entity_links el
                JOIN entities d ON d.id IN (el.entity_id_a, el.entity_id_b)
                JOIN transactions t ON t.id = el.transaction_id
                WHERE d.external_ref = 'dev_selftest_shared'
                  AND el.link_type = 'shared_device'
                """
            )
        ).scalar_one()
        check("both accounts attach to that device", neighbours == 2, f"got {neighbours}")

        # -- 4. canonical edge ordering -------------------------------------
        print("\nSchema invariants:")
        bad_order = db.execute(
            text("SELECT count(*) FROM entity_links WHERE NOT (entity_id_a < entity_id_b)")
        ).scalar_one()
        check("all edges canonically ordered (a < b)", bad_order == 0, f"got {bad_order}")

        # -- 5/6. ground truth stored but not exposed ------------------------
        label = db.execute(
            text(
                "SELECT is_synthetic_ring_id FROM transactions WHERE "
                "razorpay_order_id = 'order_SELFTEST0001'"
            )
        ).scalar_one()
        check("ground-truth label stored", label == "ring_99|selftest|agent|tuning",
              f"got {label!r}")

        detector_cols = {
            r[0]
            for r in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'v_transactions_detector'"
                )
            ).all()
        }
        check(
            "detector view hides is_synthetic_ring_id",
            "is_synthetic_ring_id" not in detector_cols,
        )
        check(
            "detector view still exposes the order id",
            "razorpay_order_id" in detector_cols,
        )

        # -- 7. cadence preservation ----------------------------------------
        print("\nTiming:")
        stored = db.execute(
            text(
                "SELECT created_at FROM transactions WHERE razorpay_order_id = "
                "'order_SELFTEST0001'"
            )
        ).scalar_one()
        check(
            "synthetic event time preserved (not seed wall-clock)",
            stored == FIXED_TIME,
            f"got {stored} expected {FIXED_TIME}",
        )

        # -- payment.captured path ------------------------------------------
        print("\npayment.captured event shape:")
        ev3 = make_event(
            "order_SELFTEST0003",
            "cust_selftest_c",
            device="dev_selftest_c",
            event_name="payment.captured",
        )
        r4 = ingest_event(db, ev3)
        db.flush()
        check("payment.captured ingests via order_id", r4.created)
        check("one edge from a device-only event", r4.links_created == 1,
              f"got {r4.links_created}")

    finally:
        db.rollback()
        db.close()

    print("\n" + "=" * 60)
    if problems:
        print(f"{FAIL} {len(problems)} check(s) failed:")
        for p in problems:
            print(f"   - {p}")
        return 1
    print(f"{OK} ingest pipeline verified. Database left untouched (rolled back).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
