"""Reset the console to a small, curated state for recording the pitch video.

    docker compose exec backend python -m scripts.demo_reset

Leaves exactly three clusters in the queue, each with a real Claude case file,
ready to approve or dismiss on camera. Re-runnable between takes.

Two deliberate departures from the obvious implementation
--------------------------------------------------------
**It does not wipe `audit_log`.** That table is append-only by trigger, and the
trigger is one of the things the demo is meant to showcase - dropping it for
convenience would disarm the strongest claim in the project. It is also
unnecessary: the console renders a cluster's audit trail by `target_id`, and
this script deletes and recreates clusters, so each one gets a fresh id and a
visibly clean history. Old rows reference dead cluster ids and never render.

**It curates by scope, not by fabrication.** Rather than inventing demo data,
it hands the detector an opaque set of transaction ids to exclude - the same
mechanism `evaluation/splits.py` uses - so only the chosen rings are in view.
Every cluster on screen is a real detection over real Razorpay test-mode
transactions. Nothing is staged.

Runtime
-------
Detection is ~0.1s. The cost is the three case files, so they are generated
concurrently rather than in sequence: ~15-20s instead of ~45-60s. That keeps the
whole reset under the 30s target.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid

from sqlalchemy import text

from app.case_files import CaseFileError, generate_case_file
from app.db import SessionLocal, engine
from detection.config import DetectorConfig
from detection.pipeline import run_detection

OK = "[ok]"
FAIL = "[FAIL]"

#: The three rings the demo shows, chosen for what each one demonstrates.
#: All three are genuine seeded rings - see the briefing printed at the end for
#: what each one actually is, so the narration can stay honest.
DEMO_RINGS = ("ring_10", "ring_11", "ring_08")

RING_ROLES = {
    "ring_10": (
        "THE OBVIOUS RING",
        "Eight accounts funnelling through one shared device and address at "
        "machine-regular intervals. Claude should call this likely_ring. This is "
        "your approve.",
    ),
    "ring_11": (
        "THE AMBIGUOUS ONE",
        "Four accounts on a shared payout account, but paced like people. Scores "
        "inside the [0.30, 0.45) band, so the detector files it as needs_review "
        "rather than asserting it. This is the 'the system says it is unsure' "
        "beat.",
    ),
    "ring_08": (
        "THE ONE THAT LOOKS INNOCENT",
        "Six accounts sharing a delivery address, human-paced, no shared card. "
        "Address is weighted 0.40 precisely because households share addresses, "
        "so this scores low and Claude has previously called it "
        "likely_false_positive.",
    ),
}


def transactions_outside(db, rings: tuple[str, ...]) -> set[uuid.UUID]:
    """Transaction ids for every OTHER seeded ring.

    Background traffic is never excluded - the detector still has to not trip
    over 900 unlabelled transactions, which is most of what makes the demo
    honest. Reads labels, which is fine: this is a demo harness, not detection
    code, and the detector receives only an opaque id set.
    """
    rows = db.execute(
        text(
            """
            SELECT id FROM transactions
            WHERE is_synthetic_ring_id IS NOT NULL
              AND split_part(is_synthetic_ring_id, '|', 1) <> ALL(:keep)
            """
        ),
        {"keep": list(rings)},
    ).scalars()
    return set(rows)


def wipe_clusters() -> int:
    """Delete clusters (cascading members and case files). audit_log untouched."""
    with engine.begin() as conn:
        removed = conn.execute(text("DELETE FROM clusters")).rowcount
    return int(removed or 0)


async def generate_all(cluster_ids: list[uuid.UUID]) -> tuple[int, list[str]]:
    """Write every case file concurrently.

    One Session per task: SQLAlchemy Sessions are not safe to share across
    concurrent coroutines, and quietly interleaving statements on one connection
    is the kind of bug that only shows up on camera.
    """

    async def one(cluster_id: uuid.UUID) -> str | None:
        db = SessionLocal()
        try:
            await generate_case_file(db, cluster_id, force=True)
            db.commit()
            return None
        except CaseFileError as exc:
            db.rollback()
            return f"{str(cluster_id)[:8]}: {exc}"
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            return f"{str(cluster_id)[:8]}: {type(exc).__name__}: {exc}"
        finally:
            db.close()

    results = await asyncio.gather(*(one(cid) for cid in cluster_ids))
    failures = [r for r in results if r]
    return len(cluster_ids) - len(failures), failures


def briefing(db) -> None:
    """Print what is on screen, including ground truth, so narration stays honest."""
    rows = db.execute(
        text(
            """
            SELECT c.id, c.status::text AS status, c.score,
                   c.cadence::text AS cadence,
                   c.evidence_json->>'headline' AS headline,
                   cf.suggested_action::text AS suggested,
                   (SELECT string_agg(DISTINCT split_part(t.is_synthetic_ring_id,'|',1), ',')
                    FROM cluster_members m2
                    JOIN transactions t ON t.customer_entity_id = m2.entity_id
                    WHERE m2.cluster_id = c.id
                      AND t.is_synthetic_ring_id IS NOT NULL) AS truth
            FROM clusters c
            LEFT JOIN LATERAL (
                SELECT suggested_action FROM case_files
                WHERE cluster_id = c.id ORDER BY generated_at DESC LIMIT 1
            ) cf ON TRUE
            ORDER BY c.score DESC
            """
        )
    ).mappings().all()

    print("\n" + "=" * 72)
    print("ON SCREEN NOW")
    print("=" * 72)
    for row in rows:
        ring = (row["truth"] or "").split(",")[0]
        title, note = RING_ROLES.get(ring, ("", ""))
        print(f"\n  {row['score']:.3f}  {row['status']:<13}{row['cadence']:<13}"
              f"Claude: {row['suggested'] or '—'}")
        if title:
            print(f"  {title}")
        print(f"    {(row['headline'] or '')[:68]}")
        if note:
            for line in _wrap(note, 66):
                print(f"    {line}")
        print(f"    ground truth: {ring or 'unlabelled'} "
              f"(you are the only one who sees this line)")

    print("\n" + "-" * 72)
    print("  HONEST NARRATION NOTE")
    print("  All three are genuine seeded rings. There is no true false positive")
    print("  in this corpus - the detector has not produced one. So if you dismiss")
    print("  the third cluster on camera, say so: 'the detector flagged it, told")
    print("  you it was unsure, Claude leaned false-positive, and a human still")
    print("  got it wrong - which is exactly why the audit log records who decided")
    print("  and why.' That lands better than implying a clean false positive.")
    print("-" * 72)


def _wrap(body: str, width: int) -> list[str]:
    words, lines, current = body.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset the console to a curated 3-cluster demo state."
    )
    parser.add_argument(
        "--no-case-files",
        action="store_true",
        help="skip Claude calls (about 20s faster; clusters appear without case files)",
    )
    args = parser.parse_args()

    started = time.monotonic()
    print("RingSentinel demo reset")
    print(f"  showing: {', '.join(DEMO_RINGS)}")
    print("  audit_log is NOT wiped - it is append-only, and that is the point.\n")

    db = SessionLocal()
    try:
        removed = wipe_clusters()
        print(f"  {OK} cleared {removed} cluster(s); transactions untouched")

        excluded = transactions_outside(db, DEMO_RINGS)
        run = run_detection(
            db,
            config=DetectorConfig(),
            exclude_transaction_ids=excluded,
            persist=True,
            scope_label="demo",
        )
        db.commit()

        cluster_ids = list(run.persisted_ids.values())
        print(f"  {OK} detected {len(cluster_ids)} cluster(s) in {run.elapsed_seconds:.2f}s "
              f"({len(excluded)} out-of-scope transactions hidden)")

        if len(cluster_ids) != 3:
            print(f"  {FAIL} expected 3 clusters, got {len(cluster_ids)}. "
                  "Adjust DEMO_RINGS at the top of this script.")

        if args.no_case_files:
            print(f"  {OK} skipped case files (--no-case-files)")
        elif cluster_ids:
            print(f"  ... writing {len(cluster_ids)} case files concurrently", flush=True)
            written, failures = asyncio.run(generate_all(cluster_ids))
            print(f"  {OK} {written} case file(s) written")
            for line in failures:
                print(f"  {FAIL} {line}")

        briefing(db)

        elapsed = time.monotonic() - started
        print(f"\n{OK} ready in {elapsed:.1f}s — open http://localhost:3000/console")
        if elapsed > 30:
            print(f"  note: over the 30s target. Re-runs are faster once the "
                  f"prompt cache is warm.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
