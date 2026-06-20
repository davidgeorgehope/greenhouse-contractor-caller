from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import sqlite3

from .config import get_settings
from .db import billing_is_active, upsert_user_billing, upsert_user_billing_by_customer


ACTIVE_BILLING_STATUSES = {"active", "trialing"}


def billing_configured() -> bool:
    settings = get_settings()
    return bool(settings.stripe_secret_key and settings.stripe_price_id)


def can_use_paid_workflows(user_id: int) -> bool:
    settings = get_settings()
    if not settings.contractor_billing_required:
        return True
    return billing_is_active(user_id)


def create_checkout_session(user: sqlite3.Row) -> str:
    settings = get_settings()
    if not billing_configured():
        raise RuntimeError("Stripe billing is not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    base_url = settings.app_host.rstrip("/")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=str(user["email"]),
        client_reference_id=str(user["id"]),
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{base_url}/contractor/billing?checkout=success",
        cancel_url=f"{base_url}/contractor/billing?checkout=cancelled",
        metadata={"user_id": str(user["id"])},
    )
    if not session.url:
        raise RuntimeError("Stripe did not return a checkout URL")
    return str(session.url)


def parse_stripe_event(payload: bytes, signature: str | None) -> Any:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_webhook_secret:
        if not signature:
            raise ValueError("Missing Stripe signature")
        return stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    return stripe.Event.construct_from(json.loads(payload.decode("utf-8")), stripe.api_key)


def _timestamp_to_iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def handle_stripe_event(event: Any) -> None:
    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id_raw = data.get("client_reference_id") or data.get("metadata", {}).get("user_id")
        if not user_id_raw:
            return
        subscription_id = data.get("subscription")
        customer_id = data.get("customer")
        status = "active" if data.get("payment_status") in {"paid", "no_payment_required"} else "incomplete"
        upsert_user_billing(
            user_id=int(user_id_raw),
            stripe_customer_id=str(customer_id) if customer_id else None,
            stripe_subscription_id=str(subscription_id) if subscription_id else None,
            status=status,
        )
        return

    if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        customer_id = data.get("customer")
        if not customer_id:
            return
        status = str(data.get("status") or "inactive")
        upsert_user_billing_by_customer(
            stripe_customer_id=str(customer_id),
            stripe_subscription_id=str(data.get("id")) if data.get("id") else None,
            status=status,
            current_period_end=_timestamp_to_iso(data.get("current_period_end")),
        )
