"""Run the real detector over real payment data it did not generate.

Every headline number in this repo comes from a corpus this project seeded, and
that corpus is separable by construction: its busiest benign attribute is shared
by 3 accounts, while rings reach 9. The IEEE-CIS Fraud Detection dataset is
590,540 genuine transactions with a 3.50% fraud rate and a single card carrying
14,112 of them. It is the environment the seeded corpus is not.

WHAT THIS CAN AND CANNOT MEASURE — read before quoting anything from it.

  It CANNOT measure ring recall. The dataset labels *transactions* as
  fraudulent; it does not say which accounts were working together, so there is
  no ring to recall. Any precision or recall figure computed here would be
  answering a different question than the one the seeded corpus answers, and
  putting them side by side would be dishonest.

  It CAN measure LIFT: whether the clusters the detector flags carry a
  materially higher fraud rate than the 3.50% population base rate. That is a
  real result on data this project did not create, and it is the honest claim.

⚠ THE ACCOUNT PROXY IS AN ASSUMPTION, AND THE WHOLE RESULT RESTS ON IT.

  IEEE-CIS has no customer column. There is no account in this data. So one is
  constructed — card1 plus addr1 — and every "account" here is that construct
  rather than an observed entity. Two rows share an account when they share a
  card and a billing address.

  The consequence has to be stated: because the proxy contains card1, accounts
  that "share an instrument" necessarily differ in address, and accounts that
  "share an address" necessarily differ in card. That is a reasonable reading
  of coordinated behaviour, and it is still a modelling choice this project
  made rather than a fact the data reports.

The detector itself is untouched. Rows go into the same tables through the same
schema, the fraud label goes into `is_synthetic_ring_id` — the ground-truth
column the detector's view excludes — and `run_detection` is the same function
the seeded corpus uses. Everything is rolled back afterwards.
"""

from __future__ import annotations

import csv
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "ieee"
TRANSACTIONS_CSV = DATA_DIR / "train_transaction.csv"
IDENTITY_CSV = DATA_DIR / "train_identity.csv"

#: IEEE-CIS timestamps are seconds from an unpublished reference date. The
#: absolute date is irrelevant — only the gaps between transactions matter to
#: the timing signals — so an arbitrary epoch is used and said to be arbitrary.
REFERENCE_EPOCH = datetime(2017, 12, 1, tzinfo=timezone.utc)

#: The card identity. IEEE splits one instrument across six columns.
CARD_COLUMNS = ("card1", "card2", "card3", "card5", "card4", "card6")


#: Entity and transaction ids are derived from their reference rather than
#: minted fresh, so a run is reproducible. With uuid4 the ids changed every run
#: and Louvain — which is seeded, but whose output still depends on node
#: identity — returned slightly different communities each time, moving the
#: measured lift between runs. A number that moves when nothing changed cannot
#: be argued with.
IEEE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "ringsentinel/ieee-cis")


def _stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(IEEE_NAMESPACE, f"{kind}:{value}")


def _ref(kind: str, value: str) -> str:
    """Opaque token, same shape the seeded corpus uses. No raw values stored."""
    digest = hashlib.sha256(f"ieee|{kind}|{value}".encode()).hexdigest()[:20]
    return f"{kind}_ieee_{digest}"


def _blank(v: str | None) -> bool:
    return v is None or v == "" or v == "NaN"


@dataclass
class IeeeRow:
    transaction_id: str
    is_fraud: bool
    occurred_at: datetime
    amount_paise: int
    customer_ref: str
    instrument_ref: str | None
    address_ref: str | None
    device_ref: str | None


#: ⚠ IEEE-CIS `addr1` is a COARSE BILLING REGION, not a delivery address.
#: Its median is 4 accounts and its maximum is 299 in a 20k slice, because it
#: identifies an area rather than a household. Mapping it onto RingSentinel's
#: `address` entity — which means "the same delivery address" — connected every
#: account in a region to every other and produced 282-account clusters. That
#: was an error in this adapter, not in the detector: the two fields carry the
#: same name and completely different meanings. Off by default for that reason.
MAP_ADDR1_AS_ADDRESS = False


@dataclass
class IeeeCorpus:
    rows: list[IeeeRow] = field(default_factory=list)
    skipped_no_account: int = 0

    @property
    def fraud(self) -> int:
        return sum(1 for r in self.rows if r.is_fraud)

    @property
    def base_rate(self) -> float:
        return self.fraud / len(self.rows) if self.rows else 0.0


def load_identity(limit: int | None = None) -> dict[str, str]:
    """TransactionID -> DeviceInfo, for the rows that carry one."""
    if not IDENTITY_CSV.exists():
        return {}
    out: dict[str, str] = {}
    with IDENTITY_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            info = row.get("DeviceInfo")
            if not _blank(info):
                out[row["TransactionID"]] = info
    return out


def load_corpus(
    limit: int | None = 100_000, map_address: bool = MAP_ADDR1_AS_ADDRESS
) -> IeeeCorpus:
    """Stream the CSV into rows. Never loads the whole file into memory."""
    devices = load_identity()
    corpus = IeeeCorpus()

    with TRANSACTIONS_CSV.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if limit and i >= limit:
                break

            card = "|".join(row.get(c, "") for c in CARD_COLUMNS)
            addr = f"{row.get('addr1','')}|{row.get('addr2','')}"

            # The account proxy. Without both halves there is no account to
            # speak of, and inventing one would manufacture graph structure.
            if _blank(row.get("card1")) or _blank(row.get("addr1")):
                corpus.skipped_no_account += 1
                continue

            device = devices.get(row["TransactionID"])
            try:
                amount = int(round(float(row["TransactionAmt"]) * 100))
                seconds = int(float(row["TransactionDT"]))
            except (TypeError, ValueError):
                corpus.skipped_no_account += 1
                continue

            corpus.rows.append(
                IeeeRow(
                    transaction_id=row["TransactionID"],
                    is_fraud=row["isFraud"] == "1",
                    occurred_at=REFERENCE_EPOCH + timedelta(seconds=seconds),
                    amount_paise=max(0, amount),
                    customer_ref=_ref("cust", f"{row['card1']}|{row.get('addr1','')}"),
                    instrument_ref=_ref("inst", card),
                    address_ref=_ref("addr", addr) if map_address else None,
                    device_ref=_ref("dev", device) if device else None,
                )
            )
    return corpus


def insert_corpus(db: Session, corpus: IeeeCorpus) -> set[uuid.UUID]:
    """Write the rows into the real schema. Returns the transaction ids added.

    Bulk SQL rather than the webhook path: 100,000 signed webhooks would take
    hours and would exercise HMAC verification, which is not what is being
    measured here. The tables, constraints and the detector are the real ones.
    """
    entity_ids: dict[tuple[str, str], uuid.UUID] = {}

    def entity(kind: str, ref: str) -> uuid.UUID:
        etype = {"cust": "customer", "inst": "instrument",
                 "addr": "address", "dev": "device"}[kind]
        key = (etype, ref)
        if key not in entity_ids:
            entity_ids[key] = _stable_id(etype, ref)
        return entity_ids[key]

    tx_rows = []
    for r in corpus.rows:
        cid = entity("cust", r.customer_ref)
        iid = entity("inst", r.instrument_ref) if r.instrument_ref else None
        aid = entity("addr", r.address_ref) if r.address_ref else None
        did = entity("dev", r.device_ref) if r.device_ref else None
        tx_rows.append(
            {
                "id": _stable_id("tx", r.transaction_id),
                "razorpay_order_id": f"ieee_{r.transaction_id}",
                "customer_entity_id": cid,
                "device_entity_id": did,
                "address_entity_id": aid,
                "instrument_entity_id": iid,
                "amount": r.amount_paise,
                "currency": "USD",
                "created_at": r.occurred_at,
                # The evaluation label, in the column the detector's view
                # excludes. The detector cannot read this.
                "is_synthetic_ring_id": "ieee|fraud" if r.is_fraud else None,
            }
        )

    ent_rows = [
        {"id": eid, "type": etype, "external_ref": ref, "first_seen_at": REFERENCE_EPOCH}
        for (etype, ref), eid in entity_ids.items()
    ]

    CHUNK = 5_000
    for i in range(0, len(ent_rows), CHUNK):
        db.execute(
            text(
                "INSERT INTO entities (id, type, external_ref, first_seen_at) "
                "VALUES (:id, CAST(:type AS entity_type), :external_ref, :first_seen_at) "
                "ON CONFLICT DO NOTHING"
            ),
            ent_rows[i : i + CHUNK],
        )
    for i in range(0, len(tx_rows), CHUNK):
        db.execute(
            text(
                "INSERT INTO transactions (id, razorpay_order_id, customer_entity_id,"
                " device_entity_id, address_entity_id, instrument_entity_id, amount,"
                " currency, created_at, is_synthetic_ring_id) VALUES (:id,"
                " :razorpay_order_id, :customer_entity_id, :device_entity_id,"
                " :address_entity_id, :instrument_entity_id, :amount, :currency,"
                " :created_at, :is_synthetic_ring_id)"
            ),
            tx_rows[i : i + CHUNK],
        )

    # Edges: one row per (pair, link_type, transaction), matching ingest.
    link_rows = []
    for tx in tx_rows:
        cid = tx["customer_entity_id"]
        for col, ltype in (
            ("device_entity_id", "shared_device"),
            ("address_entity_id", "shared_address"),
            ("instrument_entity_id", "shared_instrument"),
        ):
            other = tx[col]
            if not other:
                continue
            a, b = (cid, other) if str(cid) < str(other) else (other, cid)
            link_rows.append(
                {
                    "id": _stable_id("link", f"{a}|{b}|{ltype}|{tx['id']}"),
                    "entity_id_a": a,
                    "entity_id_b": b,
                    "link_type": ltype,
                    "transaction_id": tx["id"],
                    "created_at": tx["created_at"],
                }
            )
    for i in range(0, len(link_rows), CHUNK):
        db.execute(
            text(
                "INSERT INTO entity_links (id, entity_id_a, entity_id_b, link_type,"
                " transaction_id, created_at) VALUES (:id, :entity_id_a, :entity_id_b,"
                " CAST(:link_type AS link_type), :transaction_id, :created_at)"
                " ON CONFLICT DO NOTHING"
            ),
            link_rows[i : i + CHUNK],
        )

    db.flush()
    return {tx["id"] for tx in tx_rows}


@dataclass
class LiftResult:
    name: str
    clusters: int
    accounts: int
    transactions: int
    fraud_transactions: int
    base_rate: float

    @property
    def cluster_fraud_rate(self) -> float:
        return self.fraud_transactions / self.transactions if self.transactions else 0.0

    @property
    def lift(self) -> float:
        return self.cluster_fraud_rate / self.base_rate if self.base_rate else 0.0


def measure_lift(
    db: Session, name: str, customer_ids: set[uuid.UUID], base_rate: float
) -> LiftResult:
    """Fraud rate among the transactions of the flagged accounts."""
    if not customer_ids:
        return LiftResult(name, 0, 0, 0, 0, base_rate)
    row = db.execute(
        text(
            "SELECT count(*) AS n,"
            " count(*) FILTER (WHERE is_synthetic_ring_id IS NOT NULL) AS f"
            " FROM transactions WHERE customer_entity_id = ANY(:ids)"
        ),
        {"ids": list(customer_ids)},
    ).mappings().one()
    return LiftResult(
        name=name,
        clusters=0,
        accounts=len(customer_ids),
        transactions=row["n"],
        fraud_transactions=row["f"],
        base_rate=base_rate,
    )
