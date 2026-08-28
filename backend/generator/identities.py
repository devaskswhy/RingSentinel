"""Deterministic synthetic identity pools.

Everything here is an opaque token by construction. We never generate a
realistic street address, card number, or personal name and then hash it -
we generate an index and derive a token from it. There is no PII to leak
because none is ever materialised. This satisfies the CLAUDE.md rule that
`entities.external_ref` holds only hashes and opaque tokens.

Token shapes mirror what a real pipeline would store:
  device      -> a browser/app fingerprint hash
  address     -> a hash of the normalised shipping address
  instrument  -> a payment instrument / bank account token
  customer    -> the merchant's own account identifier
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: Namespace so tokens from this generator can never collide with tokens from a
#: real ingest, and so a token is self-describing when read in the database.
_NAMESPACE = "ringsentinel.synthetic.v1"


def _token(kind: str, index: int, salt: str = "") -> str:
    """Derive a stable opaque token for a synthetic entity.

    Deterministic in (kind, index, salt), so the same generator seed always
    yields the same tokens and re-running the seed is idempotent at the entity
    level.
    """
    material = f"{_NAMESPACE}|{kind}|{index}|{salt}".encode()
    digest = hashlib.sha256(material).hexdigest()[:24]
    return f"{kind}_{digest}"


def customer_ref(index: int, salt: str = "") -> str:
    return _token("cust", index, salt)


def device_ref(index: int, salt: str = "") -> str:
    return _token("dev", index, salt)


def address_ref(index: int, salt: str = "") -> str:
    return _token("addr", index, salt)


def instrument_ref(index: int, salt: str = "") -> str:
    return _token("inst", index, salt)


@dataclass(frozen=True)
class RingIdentities:
    """The identity material belonging to one seeded ring.

    A ring has many customer accounts but only a small number of *pivot*
    attributes - that concentration is exactly the signal the detector is meant
    to find.
    """

    customers: tuple[str, ...]
    shared_devices: tuple[str, ...]
    shared_addresses: tuple[str, ...]
    shared_instruments: tuple[str, ...]
    #: Per-account private attributes, used when an order does not touch the
    #: shared pivot (controlled by RingSpec.density).
    private_devices: tuple[str, ...]
    private_addresses: tuple[str, ...]
    private_instruments: tuple[str, ...]


def build_ring_identities(
    ring_number: int,
    account_count: int,
    shared_device_count: int,
    shared_address_count: int,
    shared_instrument_count: int,
) -> RingIdentities:
    """Materialise the identity pool for one ring.

    The `ring_number` is folded into the salt so two rings never accidentally
    share an entity - each seeded cluster stays a distinct component unless the
    background traffic happens to bridge them.
    """
    salt = f"ring{ring_number}"
    return RingIdentities(
        customers=tuple(customer_ref(i, salt) for i in range(account_count)),
        shared_devices=tuple(
            device_ref(1000 + i, salt) for i in range(shared_device_count)
        ),
        shared_addresses=tuple(
            address_ref(1000 + i, salt) for i in range(shared_address_count)
        ),
        shared_instruments=tuple(
            instrument_ref(1000 + i, salt) for i in range(shared_instrument_count)
        ),
        private_devices=tuple(device_ref(i, salt) for i in range(account_count)),
        private_addresses=tuple(address_ref(i, salt) for i in range(account_count)),
        private_instruments=tuple(
            instrument_ref(i, salt) for i in range(account_count)
        ),
    )


@dataclass(frozen=True)
class NormalIdentities:
    """Background population. Large attribute pools keep accidental sharing rare."""

    customers: tuple[str, ...]
    devices: tuple[str, ...]
    addresses: tuple[str, ...]
    instruments: tuple[str, ...]


def build_normal_identities(
    customer_count: int,
    device_pool: int,
    address_pool: int,
    instrument_pool: int,
) -> NormalIdentities:
    salt = "normal"
    return NormalIdentities(
        customers=tuple(customer_ref(i, salt) for i in range(customer_count)),
        devices=tuple(device_ref(i, salt) for i in range(device_pool)),
        addresses=tuple(address_ref(i, salt) for i in range(address_pool)),
        instruments=tuple(instrument_ref(i, salt) for i in range(instrument_pool)),
    )
