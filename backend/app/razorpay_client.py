"""Razorpay TEST-MODE client wrapper.

Three jobs, none of which the bare SDK does for us:

1. **Test-mode enforcement.** A key that is not `rzp_test_...` is refused at
   construction. Invariant #5 in CLAUDE.md is not a matter of remembering.

2. **Rate limiting.** A token bucket paces outbound calls. Razorpay does not
   publish a hard public number for standard API limits, so the rate is
   configurable and defaults deliberately low.

3. **Real 429 handling.** The SDK throws away the HTTP status code - it maps
   errors purely by Razorpay's `code` string, so a 429 arrives as a generic
   `ServerError` with no `Retry-After`. We attach a `requests` response hook to
   observe the true status and retry header *before* the SDK swallows them,
   then back off accordingly. The SDK's own retry only covers ConnectionError.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import razorpay
from razorpay.errors import BadRequestError, GatewayError, ServerError

log = logging.getLogger(__name__)

TEST_KEY_PREFIX = "rzp_test_"
LIVE_KEY_PREFIX = "rzp_live_"


class LiveKeyRefused(RuntimeError):
    """Raised when anything other than a test-mode key is supplied."""


@dataclass
class CallStats:
    """Counters surfaced in the seed summary."""

    calls: int = 0
    retries: int = 0
    rate_limited: int = 0
    failures: int = 0
    failure_samples: list[str] = field(default_factory=list)

    def record_failure(self, message: str) -> None:
        self.failures += 1
        if len(self.failure_samples) < 5:
            self.failure_samples.append(message[:200])


class _TokenBucket:
    """Simple thread-safe token bucket for outbound call pacing."""

    def __init__(self, rate_per_second: float, burst: int) -> None:
        self._rate = rate_per_second
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = (1.0 - self._tokens) / self._rate
            time.sleep(deficit)


class RazorpayTestClient:
    """Test-mode-only Razorpay client with pacing and 429-aware retries."""

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        rate_per_second: float = 4.0,
        burst: int = 8,
        max_attempts: int = 6,
        base_backoff: float = 0.6,
        max_backoff: float = 30.0,
    ) -> None:
        if not key_id:
            raise LiveKeyRefused("RAZORPAY_KEY_ID is not set.")
        if key_id.startswith(LIVE_KEY_PREFIX):
            raise LiveKeyRefused(
                "A live Razorpay key was supplied. RingSentinel is test-mode only "
                "(CLAUDE.md invariant #5). Refusing to continue."
            )
        if not key_id.startswith(TEST_KEY_PREFIX):
            raise LiveKeyRefused(
                f"RAZORPAY_KEY_ID must start with {TEST_KEY_PREFIX!r}; got "
                f"{key_id[:9]!r}..."
            )
        if not key_secret:
            raise LiveKeyRefused("RAZORPAY_KEY_SECRET is not set.")

        self._client = razorpay.Client(auth=(key_id, key_secret))
        self._client.set_app_details({"title": "RingSentinel", "version": "0.2.0"})

        self._bucket = _TokenBucket(rate_per_second, burst)
        self._max_attempts = max_attempts
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self.stats = CallStats()

        # Observe the raw HTTP response before the SDK maps it to an exception.
        self._last_status: int | None = None
        self._last_retry_after: float | None = None
        self._client.session.hooks.setdefault("response", [])
        self._client.session.hooks["response"].append(self._on_response)

    # -- internals --------------------------------------------------------

    def _on_response(self, response, *args, **kwargs):  # noqa: ANN001
        self._last_status = response.status_code
        retry_after = response.headers.get("Retry-After")
        self._last_retry_after = None
        if retry_after:
            try:
                self._last_retry_after = float(retry_after)
            except ValueError:
                self._last_retry_after = None
        return response

    def _sleep_for_attempt(self, attempt: int) -> None:
        if self._last_retry_after is not None:
            delay = min(self._last_retry_after, self._max_backoff)
        else:
            delay = min(self._base_backoff * (2**attempt), self._max_backoff)
        # Full jitter, so parallel callers do not resynchronise on retry.
        time.sleep(random.uniform(0.0, delay) + 0.05)

    def _call(self, description: str, fn, *args, **kwargs) -> dict[str, Any]:
        """Invoke an SDK method with pacing, retry, and 429 awareness."""
        last_error: Exception | None = None

        for attempt in range(self._max_attempts):
            self._bucket.take()
            self._last_status = None
            self._last_retry_after = None
            try:
                self.stats.calls += 1
                return fn(*args, **kwargs)
            except (ServerError, GatewayError, BadRequestError) as exc:
                last_error = exc
                status = self._last_status

                if status == 429:
                    self.stats.rate_limited += 1
                    self.stats.retries += 1
                    log.warning(
                        "429 from Razorpay on %s (attempt %d/%d); backing off",
                        description,
                        attempt + 1,
                        self._max_attempts,
                    )
                    self._sleep_for_attempt(attempt)
                    continue

                # 5xx is worth retrying; a genuine 4xx validation error is not.
                if status is not None and 500 <= status < 600:
                    self.stats.retries += 1
                    self._sleep_for_attempt(attempt)
                    continue

                self.stats.record_failure(f"{description}: {exc}")
                raise
            except Exception as exc:  # transport-level problems
                last_error = exc
                self.stats.retries += 1
                self._sleep_for_attempt(attempt)

        self.stats.record_failure(f"{description}: exhausted retries: {last_error}")
        raise RuntimeError(
            f"{description} failed after {self._max_attempts} attempts"
        ) from last_error

    # -- public API -------------------------------------------------------

    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        notes: dict[str, str],
    ) -> dict[str, Any]:
        """Create a real test-mode order. Amount is integer paise."""
        if not isinstance(amount_paise, int):
            raise TypeError("amount must be integer paise, never a float")
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt[:40],
            "notes": notes,
            "payment_capture": 1,
        }
        return self._call("orders.create", self._client.order.create, data=payload)

    def create_payment_link(
        self,
        *,
        amount_paise: int,
        currency: str,
        reference_id: str,
        notes: dict[str, str],
    ) -> dict[str, Any]:
        """Create a real test-mode payment link."""
        if not isinstance(amount_paise, int):
            raise TypeError("amount must be integer paise, never a float")
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "reference_id": reference_id[:40],
            "description": "RingSentinel synthetic corpus (test mode)",
            "notes": notes,
            "accept_partial": False,
        }
        return self._call(
            "payment_link.create", self._client.payment_link.create, payload
        )

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        return self._call("orders.fetch", self._client.order.fetch, order_id)
