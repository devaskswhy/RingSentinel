"""The unit of output from the generator: a planned, not-yet-created order.

The generator is deliberately split into *planning* and *execution*:

  plan  -> pure, deterministic, no network. Fully reproducible from the seed.
  exec  -> calls Razorpay, which assigns ids we cannot predict.

Keeping them apart means the corpus can be inspected, diffed, and unit-tested
without spending a single API call, and it makes the seed resumable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

#: What the executor should create at Razorpay for this row.
INTENT_ORDER = "order"
INTENT_PAYMENT_LINK = "payment_link"


@dataclass(frozen=True)
class PlannedTransaction:
    """One synthetic order, fully specified before any API call is made."""

    seq: int
    occurred_at: datetime
    amount_paise: int
    currency: str

    customer_ref: str
    device_ref: str | None
    address_ref: str | None
    instrument_ref: str | None

    #: Ground truth. None for uncorrelated background traffic. Written to
    #: `transactions.is_synthetic_ring_id` and never read by the detector.
    ring_label: str | None

    #: Human-readable provenance, carried in Razorpay `notes` for traceability.
    archetype: str
    cadence: str | None
    split: str

    intent: str = INTENT_ORDER

    #: Extra archetype-specific colour (promo code tried, refund flag, ...).
    #: Goes into Razorpay notes and is useful when eyeballing the corpus.
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def receipt(self) -> str:
        """Deterministic, <=40 chars, unique per planned row.

        Razorpay caps `receipt` at 40 characters. Deriving it from the seed
        position makes a run traceable back to the plan that produced it.
        """
        return f"rs-{self.split[:4]}-{self.seq:06d}"

    def razorpay_notes(self) -> dict[str, str]:
        """Notes sent to Razorpay and echoed back on the webhook event.

        This is how entity references survive the round trip: the ingestion
        pipeline reads them back off the event rather than the generator writing
        to Postgres directly.

        Razorpay allows at most 15 note keys, each up to 256 characters.
        """
        notes: dict[str, str] = {
            "rs_customer_ref": self.customer_ref,
            "rs_archetype": self.archetype,
            "rs_split": self.split,
            "rs_seq": str(self.seq),
            # The synthetic event time, carried through Razorpay and back so the
            # ingest can use it for `transactions.created_at`. Without this every
            # row would carry the wall-clock time of the seed run, collapsing the
            # whole corpus into a few minutes and destroying the cadence signal
            # that distinguishes human rings from agent rings.
            "rs_occurred_at": self.occurred_at.isoformat(),
        }
        if self.device_ref:
            notes["rs_device_ref"] = self.device_ref
        if self.address_ref:
            notes["rs_address_ref"] = self.address_ref
        if self.instrument_ref:
            notes["rs_instrument_ref"] = self.instrument_ref
        if self.ring_label:
            notes["rs_ring_label"] = self.ring_label
        if self.cadence:
            notes["rs_cadence"] = self.cadence

        # Archetype colour, trimmed to stay inside Razorpay's 15-key ceiling.
        # Worst case above is 10 fixed keys, leaving room for 3 here.
        for key, value in list(self.attributes.items())[:3]:
            notes[f"rs_{key}"] = str(value)[:256]

        assert len(notes) <= 15, f"too many Razorpay notes keys: {len(notes)}"
        return notes
