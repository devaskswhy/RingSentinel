"""Assembles the full synthetic corpus plan.

Pure and deterministic: given a `GeneratorConfig`, `build_plan` always returns
the same corpus. No network, no database. The executor turns this plan into real
Razorpay test-mode records afterwards.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from random import Random

from generator.archetypes import ARCHETYPE_GENERATORS, PIVOT_COUNTS
from generator.config import (
    SPLIT_HOLDOUT,
    SPLIT_TUNING,
    GeneratorConfig,
    RingSpec,
)
from generator.identities import build_normal_identities, build_ring_identities
from generator.normal import generate_normal_traffic
from generator.planned import PlannedTransaction


@dataclass(frozen=True)
class GenerationPlan:
    """A complete, reproducible corpus, ready to be executed against Razorpay."""

    transactions: tuple[PlannedTransaction, ...]
    ring_specs: tuple[RingSpec, ...]
    config: GeneratorConfig

    # -- derived views ----------------------------------------------------

    @property
    def entity_refs(self) -> dict[str, set[str]]:
        """Every distinct entity the plan will cause to exist, by type."""
        refs: dict[str, set[str]] = {
            "customer": set(),
            "device": set(),
            "address": set(),
            "instrument": set(),
        }
        for row in self.transactions:
            refs["customer"].add(row.customer_ref)
            if row.device_ref:
                refs["device"].add(row.device_ref)
            if row.address_ref:
                refs["address"].add(row.address_ref)
            if row.instrument_ref:
                refs["instrument"].add(row.instrument_ref)
        return refs

    @property
    def entity_count(self) -> int:
        return sum(len(v) for v in self.entity_refs.values())

    def counts_by_split(self) -> Counter[str]:
        return Counter(row.split for row in self.transactions)

    def counts_by_archetype(self) -> Counter[str]:
        return Counter(row.archetype for row in self.transactions)

    def summary_lines(self) -> list[str]:
        refs = self.entity_refs
        by_split = self.counts_by_split()
        lines = [
            f"transactions planned : {len(self.transactions)}",
            f"entities planned     : {self.entity_count}"
            f"  (customer={len(refs['customer'])}, device={len(refs['device'])},"
            f" address={len(refs['address'])}, instrument={len(refs['instrument'])})",
            f"rings                : {len(self.ring_specs)}",
            f"  tuning  (1-8)      : {by_split.get(SPLIT_TUNING, 0)} transactions",
            f"  holdout (9-12)     : {by_split.get(SPLIT_HOLDOUT, 0)} transactions",
            f"  normal             : {by_split.get('normal', 0)} transactions",
        ]
        lines.append("archetype breakdown  :")
        for archetype, count in sorted(self.counts_by_archetype().items()):
            lines.append(f"  {archetype:<28} {count:>5}")
        return lines


def build_plan(config: GeneratorConfig | None = None) -> GenerationPlan:
    """Build the complete corpus. Deterministic in `config.seed`."""
    config = config or GeneratorConfig()

    # A single seeded RNG threaded through everything keeps the whole corpus
    # reproducible; each ring also gets a derived stream so adding a ring does
    # not reshuffle the ones before it.
    master = Random(config.seed)
    seq = itertools.count(1)

    window_end = datetime.now(timezone.utc)
    window_seconds = float(config.window_days * 24 * 3600)

    rows: list[PlannedTransaction] = []

    # ---- Seeded rings ---------------------------------------------------
    for spec in config.ring_specs:
        pivots = PIVOT_COUNTS[spec.pattern]
        ids = build_ring_identities(
            ring_number=spec.number,
            account_count=spec.account_count,
            shared_device_count=pivots["devices"],
            shared_address_count=pivots["addresses"],
            shared_instrument_count=pivots["instruments"],
        )

        # Derived, ring-stable seed: reordering RING_SPECS will not change a
        # given ring's contents.
        ring_rng = Random(config.seed * 1_000_003 + spec.number)

        generator = ARCHETYPE_GENERATORS[spec.archetype]
        rows.extend(
            generator(
                spec,
                ids,
                ring_rng,
                window_end,
                window_seconds,
                config.currency,
                seq,
            )
        )

    # ---- Background traffic ---------------------------------------------
    normal_ids = build_normal_identities(
        customer_count=config.normal_customer_count,
        device_pool=config.normal_device_pool,
        address_pool=config.normal_address_pool,
        instrument_pool=config.normal_instrument_pool,
    )
    rows.extend(
        generate_normal_traffic(
            normal_ids,
            transaction_count=config.normal_transaction_count,
            rng=master,
            window_end=window_end,
            window_days=config.window_days,
            currency=config.currency,
            seq=seq,
        )
    )

    # Chronological order, so the ingest sees events roughly as they would have
    # arrived in production.
    rows.sort(key=lambda r: r.occurred_at)

    return GenerationPlan(
        transactions=tuple(rows),
        ring_specs=config.ring_specs,
        config=config,
    )
