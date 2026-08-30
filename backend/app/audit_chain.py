"""Verify the audit log's hash chain.

The append-only trigger *blocks* tampering. The chain makes tampering
*detectable*, which is a stronger claim: someone with raw database access can
drop a trigger and rewrite a row, but they cannot make every subsequent hash
still add up. Any alteration, deletion, or reordering breaks the chain from that
point onward, and this says exactly where.

The hash is recomputed here in SQL using the same
`ringsentinel_audit_payload()` function the insert trigger uses, so the check
and the thing being checked cannot drift apart. Recomputing it in Python would
mean two definitions of "the canonical row", and the two would eventually
disagree over a timezone or a JSON key order.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class ChainResult:
    intact: bool
    rows_checked: int
    first_broken_id: int | None = None
    reason: str = ""

    def summary(self) -> str:
        if self.rows_checked == 0:
            return "audit log is empty - nothing to verify"
        if self.intact:
            return (
                f"{self.rows_checked} audit rows verified; the chain is intact "
                "from the first row to the last"
            )
        return (
            f"chain broken at row {self.first_broken_id} "
            f"of {self.rows_checked}: {self.reason}"
        )


def verify_chain(db: Session) -> ChainResult:
    """Walk the whole audit log and confirm every link still holds.

    Checks three things per row: that its recorded hash matches a fresh hash of
    its own contents, that its `prev_hash` matches the previous row's
    `row_hash`, and that no row is missing a hash entirely.
    """
    rows = db.execute(
        text(
            """
            SELECT id,
                   prev_hash,
                   row_hash,
                   encode(
                       sha256(convert_to(
                           coalesce(prev_hash, '') || ringsentinel_audit_payload(
                               id, actor::text, action, target_type, target_id,
                               detail_json, created_at
                           ), 'UTF8')
                       ), 'hex') AS recomputed
            FROM audit_log
            ORDER BY id
            """
        )
    ).mappings().all()

    if not rows:
        return ChainResult(intact=True, rows_checked=0)

    expected_prev = ""
    for row in rows:
        if row["row_hash"] is None:
            return ChainResult(
                False, len(rows), row["id"],
                "row has no hash - it was written before chaining was enabled, "
                "or the insert trigger is missing",
            )
        if (row["prev_hash"] or "") != expected_prev:
            return ChainResult(
                False, len(rows), row["id"],
                "this row's prev_hash does not match the previous row's hash - "
                "a row was deleted, reordered, or inserted out of band",
            )
        if row["row_hash"] != row["recomputed"]:
            return ChainResult(
                False, len(rows), row["id"],
                "the row's contents no longer hash to its recorded hash - it "
                "was altered after it was written",
            )
        expected_prev = row["row_hash"]

    return ChainResult(intact=True, rows_checked=len(rows))


def chain_slice(db: Session, target_type: str, target_id: str) -> list[dict]:
    """The audit rows for one target, with their chain links.

    Included in an evidence pack so a reader can verify that slice against the
    rest of the log rather than taking the bundle's word for it.
    """
    rows = db.execute(
        text(
            """
            SELECT id, actor::text AS actor, action, detail_json, created_at,
                   prev_hash, row_hash
            FROM audit_log
            WHERE target_type = :t AND target_id = :i
            ORDER BY id
            """
        ),
        {"t": target_type, "i": target_id},
    ).mappings().all()

    return [
        {
            "audit_id": r["id"],
            "actor": r["actor"],
            "action": r["action"],
            "at": r["created_at"].isoformat(),
            "detail": r["detail_json"],
            "prev_hash": r["prev_hash"],
            "row_hash": r["row_hash"],
        }
        for r in rows
    ]
