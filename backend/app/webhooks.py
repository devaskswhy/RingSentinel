"""Razorpay webhook receiver.

This is the real ingestion path. The seed command does not write to Postgres -
it creates genuine Razorpay test-mode records and then delivers the resulting
events here, exactly as Razorpay itself would.

Signature verification
----------------------
Razorpay signs the webhook with HMAC-SHA256 over the **raw request body**, using
the webhook secret as the key, and sends it in `X-Razorpay-Signature`. The body
must be verified before it is parsed - re-serialising parsed JSON changes the
bytes and the signature will never match. Hence `await request.body()`.

The comparison is constant-time. This is the same computation the Razorpay SDK's
`utility.verify_webhook_signature` performs, done inline so verification does not
require API credentials to be configured.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.ingest import SUPPORTED_EVENTS, IngestError, ingest_event

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 check over the raw body."""
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict:
    """Accept payment.captured / order.paid and write the entity graph."""
    settings = get_settings()
    secret = settings.razorpay_webhook_secret

    if not secret:
        # Refusing is safer than silently accepting unverified events.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "RAZORPAY_WEBHOOK_SECRET is not configured; refusing to accept "
                "unverified webhook events."
            ),
        )

    raw_body = await request.body()

    if not verify_signature(raw_body, x_razorpay_signature, secret):
        log.warning("rejected webhook with invalid signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook signature",
        )

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"malformed JSON body: {exc}",
        ) from exc

    event_name = event.get("event", "")
    if event_name not in SUPPORTED_EVENTS:
        # Acknowledge so Razorpay stops retrying an event we simply don't handle.
        return {"status": "ignored", "event": event_name}

    try:
        result = ingest_event(db, event)
        db.commit()
    except IngestError as exc:
        db.rollback()
        # A 400 tells Razorpay not to keep retrying a structurally bad event.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception:
        db.rollback()
        log.exception("ingest failed for event %s", event_name)
        raise

    return {
        "status": "ok",
        "event": event_name,
        "order_id": result.order_id,
        "transaction_id": str(result.transaction_id) if result.transaction_id else None,
        "created": result.created,
        "entities_created": result.entities_created,
        "links_created": result.links_created,
        "reason": result.reason,
    }
