"""Simulate scripted checkout traffic, so the detector can be watched catching it.

    docker compose exec backend python -m scripts.simulate_agent_cadence

What this is
------------
A demonstration harness. It creates ordinary Razorpay TEST-MODE orders from a
handful of accounts that happen to share one payment instrument, at a fixed
4.0-second interval, and delivers them through the normal webhook path. Then it
runs the detector so the cluster appears in the console while you watch.

It exists to make one claim visible: a machine keeps time in a way a person
cannot, and that regularity is itself a signal. Every order it sends is a
legitimate test-mode API call against a local instance. Nothing here bypasses,
degrades, or probes anything - the whole point is to be *caught*, promptly and
visibly, by the detector running next to it.

Why 4.0 seconds
---------------
Fast enough to be plainly non-human, slow enough to read on screen as it
happens. The detector classifies a cluster `agent_like` when the median gap is
under 30s and the coefficient of variation is under 0.5; a fixed 4.0s interval
sits far inside both, so the classification is unambiguous rather than marginal.

Why 6 accounts x 4 orders
-------------------------
Timing can only be measured for an account with at least 3 transactions
(MIN_TRANSACTIONS_FOR_TIMING). Four each leaves a margin, so every account
contributes to the cadence call instead of some being silently unmeasurable.
24 orders at 4.0s is ~96 seconds, inside the two-minute budget.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import requests
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from detection.config import DetectorConfig
from detection.pipeline import run_detection
from scripts.demo_reset import DEMO_RINGS, transactions_outside
from scripts.seed_rings import build_order_paid_event, sign

OK = "[ok]"
FAIL = "[FAIL]"

# ---- shape of the run ------------------------------------------------------
ACCOUNTS = 6
ORDERS_PER_ACCOUNT = 4
INTERVAL_SECONDS = 4.0
#: Re-run detection every N orders so the console sees the cluster form rather
#: than appearing fully-built at the end.
DETECT_EVERY = 6

#: Promo codes the run walks through in order - the systematic sweep is part of
#: what makes scripted activity legible.
PROMO_CODES = (
    "WELCOME10", "WELCOME15", "WELCOME20", "WELCOME25",
    "FIRSTORDER", "NEWUSER100", "TRYUS200", "SAVEBIG",
)

#: Small, plausible basket values in paise.
AMOUNTS_PAISE = (19900, 24900, 29900, 34900, 39900, 44900)


#: Marker embedded in every entity reference this script creates, so a later
#: `demo_reset` can purge previous demonstration runs. Without it each run
#: leaves six accounts behind that keep forming their own cluster, and the
#: queue quietly grows between takes.
LIVE_DEMO_MARKER = "live"


def token(kind: str, value: str) -> str:
    """Opaque, non-PII reference, tagged as belonging to a demonstration run."""
    digest = hashlib.sha256(f"agentdemo|{kind}|{value}".encode()).hexdigest()[:20]
    return f"{kind}_{LIVE_DEMO_MARKER}_{digest}"


def elapsed_stamp(started: float) -> str:
    """Time since the run began, from a MONOTONIC clock.

    Deliberately not wall-clock. A container's wall clock can drift - an early
    test run displayed timestamps spanning 14.8s for a run that monotonic
    measured at 12.1s - and on a demo whose whole claim is "look how regular
    this interval is", a drifting on-screen clock quietly contradicts the
    number in the summary. Monotonic cannot jump, so what is displayed and what
    is measured are the same quantity.
    """
    seconds = time.monotonic() - started
    return f"t+{int(seconds // 60):01d}:{seconds % 60:06.3f}"


# ---------------------------------------------------------------------------
# Detection, kept off the timing loop
# ---------------------------------------------------------------------------
#
# The interval regularity is the entire claim this demonstration makes, so
# nothing may sit between two orders. Detection therefore runs on its own
# thread with its own Session (Sessions are not safe to share across threads),
# and the main loop only ever picks up a result that is already waiting.

_detect_lock = threading.Lock()
_detect_thread: threading.Thread | None = None
_detect_result: float | None = None
_detect_customers: list[str] = []

#: Detection here runs at the SAME scope `demo_reset` used, so the live cluster
#: joins the three curated ones instead of the queue re-expanding to all twelve
#: seeded rings mid-demonstration. Computed once at startup; the detector still
#: receives only an opaque set of ids.
_detect_exclusions: set[uuid.UUID] = set()


def _detect_and_score() -> None:
    global _detect_result
    db = SessionLocal()
    try:
        run_detection(
            db,
            config=DetectorConfig(),
            exclude_transaction_ids=_detect_exclusions,
            persist=True,
            scope_label="live-demo",
        )
        db.commit()
        _, score = _demo_cluster_state(db, _detect_customers)
        with _detect_lock:
            _detect_result = score
    except Exception:  # noqa: BLE001 - a failed pass must not stop the run
        db.rollback()
    finally:
        db.close()


def _spawn_detection() -> None:
    """Start a detection pass if one is not already running."""
    global _detect_thread
    if _detect_thread is not None and _detect_thread.is_alive():
        return
    _detect_thread = threading.Thread(target=_detect_and_score, daemon=True)
    _detect_thread.start()


def _await_detection() -> None:
    if _detect_thread is not None:
        _detect_thread.join(timeout=20)


def _run_detection_once() -> None:
    """Synchronous pass, for the final state the summary reports."""
    _detect_and_score()


_case_file_thread: threading.Thread | None = None
_case_file_done = threading.Event()


def _write_case_file(cluster_id: uuid.UUID) -> None:
    """Ask Claude to explain the cluster, off the timing loop."""
    from app.case_files import generate_case_file

    db = SessionLocal()
    try:
        asyncio.run(generate_case_file(db, cluster_id, force=True))
        db.commit()
        _case_file_done.set()
    except Exception:  # noqa: BLE001 - the run continues without one
        db.rollback()
    finally:
        db.close()


def _spawn_case_file(cluster_id: uuid.UUID) -> None:
    """Start case-file generation once, as soon as the cluster is real.

    Fired in the background so the demonstration needs no manual step: by the
    time the run ends, the console already shows Claude's explanation next to
    the cadence classification.
    """
    global _case_file_thread
    if _case_file_thread is not None:
        return
    _case_file_thread = threading.Thread(
        target=_write_case_file, args=(cluster_id,), daemon=True
    )
    _case_file_thread.start()


def _demo_cluster_id(db, customers: list[str]) -> uuid.UUID | None:
    row = db.execute(
        text(
            """
            SELECT c.id FROM clusters c
            JOIN cluster_members m ON m.cluster_id = c.id
            JOIN entities e ON e.id = m.entity_id
            WHERE e.external_ref = ANY(:refs)
            ORDER BY c.score DESC LIMIT 1
            """
        ),
        {"refs": customers},
    ).first()
    return row[0] if row else None


def _drain_detection_result() -> float | None:
    """Take whatever the background pass found, without waiting for it."""
    global _detect_result
    with _detect_lock:
        value, _detect_result = _detect_result, None
    return value


def main() -> int:  # noqa: C901 - a linear script reads better flat
    parser = argparse.ArgumentParser(
        description="Send scripted test-mode checkout traffic so the detector "
        "can be observed flagging it."
    )
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument(
        "--interval", type=float, default=INTERVAL_SECONDS,
        help="seconds between orders (default 4.0)",
    )
    parser.add_argument(
        "--accounts", type=int, default=ACCOUNTS,
    )
    parser.add_argument(
        "--orders-per-account", type=int, default=ORDERS_PER_ACCOUNT,
    )
    args = parser.parse_args()

    settings = get_settings()
    total = args.accounts * args.orders_per_account
    expected_seconds = total * args.interval

    print("=" * 68)
    print("RingSentinel — scripted-cadence demonstration")
    print("=" * 68)
    print(f"  {args.accounts} accounts sharing ONE payment instrument")
    print(f"  {total} test-mode orders, one every {args.interval:.1f}s "
          f"(~{expected_seconds:.0f}s)")
    print("  Local test-mode instance only. This exists to be detected.")
    print()

    # ---- credentials ------------------------------------------------------
    try:
        from app.razorpay_client import LiveKeyRefused, RazorpayTestClient

        client = RazorpayTestClient(
            settings.razorpay_key_id or "",
            settings.razorpay_key_secret or "",
            rate_per_second=3.0,
        )
    except LiveKeyRefused as exc:
        print(f"{FAIL} {exc}")
        return 2

    secret = settings.razorpay_webhook_secret
    if not secret:
        print(f"{FAIL} RAZORPAY_WEBHOOK_SECRET is not set.")
        return 2

    # ---- identities -------------------------------------------------------
    # Run-scoped, so each run forms its own cluster rather than merging with a
    # previous demo. Old ones are cleared by scripts.demo_reset.
    run_id = uuid.uuid4().hex[:8]
    shared_instrument = token("inst", f"shared-{run_id}")
    shared_device = token("dev", f"shared-{run_id}")
    customers = [token("cust", f"{run_id}-{i}") for i in range(args.accounts)]

    global _detect_customers, _detect_exclusions
    _detect_customers = customers
    _detect_exclusions = transactions_outside(db_scope := SessionLocal(), DEMO_RINGS)
    db_scope.close()

    print(f"  run id           : {run_id}")
    print(f"  shared instrument: {shared_instrument[:26]}…")
    print()

    session = requests.Session()
    webhook_url = args.api_base.rstrip("/") + "/webhooks/razorpay"
    db = SessionLocal()

    sent = 0
    failures = 0
    first_seen_at: float | None = None
    first_seen_score = 0.0
    started = time.monotonic()
    gaps: list[float] = []
    previous_fire: float | None = None

    print(f"  {'time':<14}{'#':>3}  {'account':<10}{'promo':<13}{'amount':>9}  status")
    print("  " + "-" * 62)

    try:
        for index in range(total):
            # Deadline-based pacing: sleep until the scheduled moment rather
            # than sleeping a fixed amount after variable work. Otherwise API
            # latency accumulates and the interval visibly drifts on camera.
            target = started + index * args.interval
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)

            fired = time.monotonic()
            if previous_fire is not None:
                gaps.append(fired - previous_fire)
            previous_fire = fired

            account_index = index % args.accounts
            customer = customers[account_index]
            promo = PROMO_CODES[index % len(PROMO_CODES)]
            amount = AMOUNTS_PAISE[index % len(AMOUNTS_PAISE)]

            notes = {
                "rs_customer_ref": customer,
                "rs_device_ref": shared_device,
                "rs_instrument_ref": shared_instrument,
                "rs_occurred_at": datetime.now(timezone.utc).isoformat(),
                "rs_archetype": "live_demo",
                "rs_split": "demo",
                "rs_seq": str(index),
                "rs_promo_code": promo,
            }

            line = (
                f"  {elapsed_stamp(started):<14}{index + 1:>3}  acct-{account_index}    "
                f"{promo:<13}{amount / 100:>8.2f}  "
            )
            try:
                order = client.create_order(
                    amount_paise=amount,
                    currency="INR",
                    receipt=f"rs-demo-{run_id}-{index:03d}",
                    notes=notes,
                )
                body = json.dumps(
                    build_order_paid_event(
                        order,
                        type("Row", (), {"seq": index, "amount_paise": amount,
                                         "currency": "INR"})(),
                    ),
                    separators=(",", ":"),
                ).encode()
                response = session.post(
                    webhook_url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Razorpay-Signature": sign(body, secret),
                    },
                    timeout=20,
                )
                if response.status_code == 200:
                    sent += 1
                    print(line + "sent", flush=True)
                else:
                    failures += 1
                    print(line + f"{FAIL} webhook {response.status_code}", flush=True)
            except Exception as exc:  # noqa: BLE001 - one bad order must not stop the run
                failures += 1
                print(line + f"{FAIL} {type(exc).__name__}", flush=True)

            # ---- let the detector look --------------------------------
            # Runs on its own thread. Detection is fast, but it must never sit
            # between two orders: the interval regularity is the entire claim
            # this demonstration makes, and a stutter would undercut it on
            # camera. The final pass below is awaited so the summary is exact.
            if (index + 1) % DETECT_EVERY == 0 and index != total - 1:
                _spawn_detection()

            if index == total - 1:
                _await_detection()
                _run_detection_once()
                score = _demo_cluster_score(db, customers)
                if score is not None:
                    marker = ""
                    if first_seen_at is None and score >= DetectorConfig().score_threshold:
                        first_seen_at = time.monotonic() - started
                        first_seen_score = score
                        marker = "   <-- CROSSED THE FLAG THRESHOLD"
                    print(f"  {'':<14}     detector: cluster scores {score:.3f}"
                          f"{marker}", flush=True)
                else:
                    print(f"  {'':<14}     detector: no cluster yet "
                          f"(needs {DetectorConfig().min_cluster_customers} accounts)",
                          flush=True)

            # Report anything the background pass found, without blocking.
            # Every result is printed, not just the first: watching the score
            # climb as more orders land is the point. Only the crossing itself
            # is recorded once.
            reported = _drain_detection_result()
            if reported is not None:
                crossed_now = (
                    first_seen_at is None
                    and reported >= DetectorConfig().score_threshold
                )
                if crossed_now:
                    first_seen_at = time.monotonic() - started
                    first_seen_score = reported
                    cluster_id = _demo_cluster_id(db, customers)
                    if cluster_id is not None:
                        _spawn_case_file(cluster_id)
                        print(f"  {'':<14}     Claude is writing the case file…",
                              flush=True)
                marker = "   <-- CROSSED THE FLAG THRESHOLD" if crossed_now else ""
                print(f"  {'':<14}     detector: cluster scores {reported:.3f}"
                      f"{marker}", flush=True)

        elapsed = time.monotonic() - started

        # ---- summary ------------------------------------------------------
        print()
        print("=" * 68)
        print("RESULT")
        print("=" * 68)
        print(f"  orders sent            : {sent} of {total}")
        if failures:
            print(f"  failures               : {failures}")
        print(f"  elapsed                : {elapsed:.1f}s")

        if gaps:
            mean_gap = sum(gaps) / len(gaps)
            spread = max(gaps) - min(gaps)
            print(f"  interval held          : mean {mean_gap:.2f}s, "
                  f"spread {spread * 1000:.0f}ms")

        # Give a case file already in flight a moment to land, so the console
        # is complete when the run ends rather than a few seconds after.
        if _case_file_thread is not None:
            _case_file_thread.join(timeout=25)

        cadence, score = _demo_cluster_state(db, customers)
        if first_seen_at is not None:
            print(f"  crossed threshold at   : {first_seen_at:.0f}s "
                  f"(score {first_seen_score:.3f})")
        else:
            print("  crossed threshold at   : never — cluster stayed below "
                  f"{DetectorConfig().score_threshold}")
        if score is not None:
            print(f"  final score            : {score:.3f}")
            print(f"  cadence classification : {cadence}")
            print(f"  case file              : "
                  f"{'written by Claude' if _case_file_done.is_set() else 'not ready'}")
            if cadence == "agent_like":
                print()
                print("  The detector reached that from timing alone: a fixed")
                print("  interval has a coefficient of variation near zero, which")
                print("  no person produces across 24 consecutive orders.")
        print()
        print(f"{OK} open http://localhost:3000/console — the cluster is in the queue")
        return 0 if not failures else 1
    finally:
        db.close()


def _demo_cluster_score(db, customers: list[str]) -> float | None:
    """Score of the cluster containing these accounts, if one exists yet."""
    _, score = _demo_cluster_state(db, customers)
    return score


def _demo_cluster_state(db, customers: list[str]) -> tuple[str | None, float | None]:
    row = db.execute(
        text(
            """
            SELECT c.cadence::text AS cadence, c.score
            FROM clusters c
            JOIN cluster_members m ON m.cluster_id = c.id
            JOIN entities e ON e.id = m.entity_id
            WHERE e.external_ref = ANY(:refs)
            ORDER BY c.score DESC
            LIMIT 1
            """
        ),
        {"refs": customers},
    ).first()
    return (row[0], float(row[1])) if row else (None, None)


if __name__ == "__main__":
    sys.exit(main())
