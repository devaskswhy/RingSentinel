"""Generate Claude case files for flagged clusters.

    docker compose exec backend python -m scripts.generate_case_files --help

Skips clusters that already have a valid cached case file, so re-running is
cheap and safe. A case file is invalidated by a change to the prompt version or
to the cluster's score - retuning the detector means the old explanation no
longer explains the current number.

This script cannot change any cluster's status. Nothing here can: the database
rejects a status change outside a human review transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid

from sqlalchemy import text

from app.case_files import CaseFileError, generate_case_file
from app.db import SessionLocal

OK = "[ok]"
FAIL = "[FAIL]"
SKIP = "[skip]"


def clusters_needing_files(
    db, status_filter: str | None, limit: int | None
) -> list[tuple[uuid.UUID, float, str]]:
    rows = db.execute(
        text(
            """
            SELECT c.id, c.score, c.status::text AS status
            FROM clusters c
            WHERE (CAST(:status AS text) IS NULL OR c.status::text = CAST(:status AS text))
            ORDER BY c.score DESC
            """
        ),
        {"status": status_filter},
    ).all()
    if limit:
        rows = rows[:limit]
    return [(r.id, float(r.score), r.status) for r in rows]


async def run(args: argparse.Namespace) -> int:
    db = SessionLocal()
    generated = reused = failed = 0
    failures: list[str] = []

    try:
        targets = clusters_needing_files(db, args.status, args.limit)
        if not targets:
            print("No clusters matched. Run scripts.detect first.")
            return 0

        print(f"Generating case files for {len(targets)} cluster(s)")
        print("  (each new one is a real Claude call and takes ~15-25s)\n")

        started = time.monotonic()
        for index, (cluster_id, score, status) in enumerate(targets, start=1):
            label = f"  {index}/{len(targets)}  {str(cluster_id)[:8]}  score {score:.3f}"
            try:
                outcome = await generate_case_file(db, cluster_id, force=args.force)
                db.commit()
                if outcome.reused:
                    reused += 1
                    print(f"{label}  {SKIP} cached")
                else:
                    generated += 1
                    action = db.execute(
                        text(
                            "SELECT suggested_action::text FROM case_files "
                            "WHERE id = :cf"
                        ),
                        {"cf": str(outcome.case_file_id)},
                    ).scalar_one()
                    print(f"{label}  {OK} generated -> {action}")
            except CaseFileError as exc:
                db.rollback()
                failed += 1
                failures.append(f"{cluster_id}: {exc}")
                print(f"{label}  {FAIL} {str(exc)[:90]}")

        elapsed = time.monotonic() - started

        print("\n" + "=" * 58)
        print(f"  generated : {generated}")
        print(f"  cached    : {reused}")
        print(f"  failed    : {failed}")
        print(f"  elapsed   : {elapsed:.1f}s")
        if failures:
            print("\n  failures:")
            for line in failures[:5]:
                print(f"    - {line}")

        print(
            f"\n{OK} case files are recommendations only. Every cluster still "
            "needs a human decision."
        )
        return 1 if failed else 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Claude case files.")
    parser.add_argument(
        "--status", default="pending", help="cluster status to target (default: pending)"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--force", action="store_true", help="regenerate even when cached"
    )
    args = parser.parse_args()
    if args.status.lower() == "all":
        args.status = None
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
