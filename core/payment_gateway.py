"""Razorpay payment integration for B2B fleet pass monetization."""

from __future__ import annotations

import os
import time
import importlib
from typing import Dict
from core.secret_manager import get_manager


FLEET_PASS_AMOUNT_RUPEES = 999
FLEET_PASS_AMOUNT_PAISE = FLEET_PASS_AMOUNT_RUPEES * 100
FLEET_PASS_CURRENCY = "INR"


class PaymentGatewayError(RuntimeError):
    """Raised when the Razorpay client is unavailable or misconfigured."""


class SignatureVerificationError(ValueError):
    """Raised when webhook signature verification fails."""


def _get_razorpay_client():
    try:
        razorpay = importlib.import_module("razorpay")
    except ImportError as exc:
        raise PaymentGatewayError(
            "razorpay package is not installed. Install with: pip install razorpay"
        ) from exc

    sm = get_manager(strict_mode=False)
    key_id = sm.get("RAZORPAY_KEY_ID")
    key_secret = sm.get("RAZORPAY_KEY_SECRET")
    
    if not key_id or not key_secret:
        raise PaymentGatewayError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set as environment variables"
        )

    return razorpay.Client(auth=(key_id, key_secret))


def create_fleet_pass_order(customer_email: str) -> Dict:
    """Create a Razorpay order for a 24-hour premium API pass priced at INR 999."""
    if not customer_email or "@" not in customer_email:
        raise PaymentGatewayError("customer_email must be a valid email address")

    client = _get_razorpay_client()
    order_payload = {
        "amount": FLEET_PASS_AMOUNT_PAISE,
        "currency": FLEET_PASS_CURRENCY,
        "receipt": f"fleetpass_{int(time.time())}",
        "notes": {
            "customer_email": customer_email,
            "product": "24-hour-fleet-api-pass",
        },
    }
    return client.order.create(data=order_payload)


def verify_razorpay_signature(payload: str, signature: str) -> bool:
    """Verify Razorpay webhook signature using webhook secret from SecretManager."""
    sm = get_manager(strict_mode=False)
    webhook_secret = sm.get("RAZORPAY_WEBHOOK_SECRET")
    
    if not webhook_secret:
        raise PaymentGatewayError(
            "RAZORPAY_WEBHOOK_SECRET must be set as environment variable"
        )

    client = _get_razorpay_client()
    try:
        client.utility.verify_webhook_signature(payload, signature, webhook_secret)
        return True
    except Exception as exc:  # pragma: no cover - SDK raises generic exception
        raise SignatureVerificationError("Invalid Razorpay signature") from exc
