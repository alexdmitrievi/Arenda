import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from app.config import settings
from app.models.subscription import (
    PLAN_PRICES_RUB,
    PLAN_PRICES_USD,
    PaymentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)

logger = logging.getLogger("tbx.payments.yookassa")

YOOKASSA_API = "https://api.yookassa.ru/v3"


def _headers(idempotency_key: str | None = None) -> dict:
    key = idempotency_key or uuid.uuid4().hex
    return {
        "Content-Type": "application/json",
        "Idempotence-Key": key,
    }


def _auth() -> tuple[str, str]:
    return (settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)


async def create_payment(
    amount: Decimal,
    description: str,
    return_url: str,
    plan: SubscriptionPlan,
    save_payment_method: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    ik = idempotency_key or uuid.uuid4().hex

    payload = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB",
        },
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "capture": True,
        "description": description,
        "save_payment_method": save_payment_method,
        "metadata": {
            "plan": plan.value,
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{YOOKASSA_API}/payments",
            json=payload,
            headers=_headers(ik),
            auth=_auth(),
            timeout=30,
        )
        data = resp.json()

        if resp.status_code not in (200, 201):
            logger.error("YooKassa create_payment failed: %s", data)
            raise ValueError(f"Payment creation failed: {data}")

    return data


async def get_payment(payment_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{YOOKASSA_API}/payments/{payment_id}",
            headers=_headers(),
            auth=_auth(),
            timeout=30,
        )
        return resp.json()


async def capture_payment(payment_id: str, idempotency_key: str | None = None) -> dict:
    ik = idempotency_key or uuid.uuid4().hex
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{YOOKASSA_API}/payments/{payment_id}/capture",
            json={},
            headers=_headers(ik),
            auth=_auth(),
            timeout=30,
        )
        return resp.json()


async def cancel_payment(payment_id: str, idempotency_key: str | None = None) -> dict:
    ik = idempotency_key or uuid.uuid4().hex
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{YOOKASSA_API}/payments/{payment_id}/cancel",
            json={},
            headers=_headers(ik),
            auth=_auth(),
            timeout=30,
        )
        return resp.json()


async def create_refund(
    payment_id: str,
    amount: Decimal,
    idempotency_key: str | None = None,
) -> dict:
    ik = idempotency_key or uuid.uuid4().hex
    payload = {
        "payment_id": payment_id,
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB",
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{YOOKASSA_API}/refunds",
            json=payload,
            headers=_headers(ik),
            auth=_auth(),
            timeout=30,
        )
        return resp.json()


async def create_auto_payment(
    payment_method_id: str,
    amount: Decimal,
    description: str,
    plan: SubscriptionPlan,
    idempotency_key: str | None = None,
) -> dict:
    ik = idempotency_key or uuid.uuid4().hex
    payload = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB",
        },
        "capture": True,
        "description": description,
        "payment_method_id": payment_method_id,
        "metadata": {
            "plan": plan.value,
            "auto": "true",
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{YOOKASSA_API}/payments",
            json=payload,
            headers=_headers(ik),
            auth=_auth(),
            timeout=30,
        )
        return resp.json()


def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    if not settings.YOOKASSA_SECRET_KEY:
        return False

    parts = signature_header.split(",")
    params = {}
    for part in parts:
        key, _, value = part.partition("=")
        params[key.strip()] = value.strip()

    alg = params.get("alg", "sha256")
    received_sig = params.get("sig", "")

    if alg == "sha256":
        expected = hmac.new(
            settings.YOOKASSA_SECRET_KEY.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received_sig)

    return False


def get_plan_price(plan: SubscriptionPlan, currency: str = "RUB") -> Decimal:
    """YooKassa charges in RUB; CryptoCloud (USDT) uses the USD price list."""
    prices = PLAN_PRICES_RUB if currency.upper() == "RUB" else PLAN_PRICES_USD
    return prices.get(plan, Decimal("0"))
