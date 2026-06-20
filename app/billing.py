from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import sqlite3

from .config import get_settings
from .db import (
    active_job_count,
    billing_is_active,
    consume_call_credit,
    ensure_user_entitlements,
    get_user_billing,
    grant_period_call_credits,
    lead_count_for_job,
    upsert_user_billing,
    upsert_user_billing_by_customer,
)


ACTIVE_BILLING_STATUSES = {"active", "trialing"}


def _is_test_billing_user(user: sqlite3.Row) -> bool:
    settings = get_settings()
    email = str(user["email"]).strip().lower()
    owner_email = settings.stripe_test_owner_email.strip().lower()
    if email == owner_email:
        return True
    if "@" not in email or "@" not in owner_email:
        return False
    local, domain = email.split("@", 1)
    owner_local, owner_domain = owner_email.split("@", 1)
    return domain == owner_domain and local.startswith(f"{owner_local}+")


def _stripe_config_for_user(user: sqlite3.Row, *, credit_pack: bool = False) -> tuple[str, str, str]:
    settings = get_settings()
    if _is_test_billing_user(user) and settings.stripe_test_secret_key:
        price_id = settings.stripe_test_credit_price_id if credit_pack else settings.stripe_test_price_id
        return settings.stripe_test_secret_key, price_id, "test"
    price_id = settings.stripe_credit_price_id if credit_pack else settings.stripe_price_id
    return settings.stripe_secret_key, price_id, "live"


def billing_configured() -> bool:
    settings = get_settings()
    return bool(settings.stripe_secret_key and settings.stripe_price_id)


def billing_configured_for_user(user: sqlite3.Row) -> bool:
    secret_key, price_id, _mode = _stripe_config_for_user(user)
    return bool(secret_key and price_id)


def credit_checkout_configured() -> bool:
    settings = get_settings()
    return bool(settings.stripe_secret_key and settings.stripe_credit_price_id)


def credit_checkout_configured_for_user(user: sqlite3.Row) -> bool:
    secret_key, price_id, _mode = _stripe_config_for_user(user, credit_pack=True)
    return bool(secret_key and price_id)


def can_use_paid_workflows(user_id: int) -> bool:
    settings = get_settings()
    if not settings.contractor_billing_required:
        return True
    return billing_is_active(user_id)


def sync_default_entitlements(user_id: int) -> None:
    settings = get_settings()
    ensure_user_entitlements(
        user_id,
        active_jobs_limit=settings.contractor_plan_active_jobs,
        leads_per_job_limit=settings.contractor_plan_leads_per_job,
        call_credits_per_period=settings.contractor_plan_call_credits,
    )


def call_credits_remaining(user_id: int) -> int:
    billing = get_user_billing(user_id)
    if not billing:
        return 0
    return int(billing["call_credits_remaining"] or 0)


def can_create_paid_job(user_id: int) -> bool:
    if not can_use_paid_workflows(user_id):
        return False
    billing = get_user_billing(user_id)
    limit = int(billing["plan_active_jobs_limit"] if billing else get_settings().contractor_plan_active_jobs)
    return active_job_count(user_id) < limit


def can_add_paid_lead(user_id: int, job_id: int) -> bool:
    if not can_use_paid_workflows(user_id):
        return False
    billing = get_user_billing(user_id)
    limit = int(billing["plan_leads_per_job_limit"] if billing else get_settings().contractor_plan_leads_per_job)
    return lead_count_for_job(job_id) < limit


def reserve_call_credit(user_id: int | None) -> bool:
    settings = get_settings()
    if not settings.contractor_billing_required:
        return True
    if user_id is None:
        return False
    return consume_call_credit(user_id)


def create_checkout_session(user: sqlite3.Row) -> str:
    secret_key, price_id, mode = _stripe_config_for_user(user)
    if not secret_key or not price_id:
        raise RuntimeError("Stripe billing is not configured")
    sync_default_entitlements(int(user["id"]))

    import stripe

    stripe.api_key = secret_key
    settings = get_settings()
    base_url = settings.app_host.rstrip("/")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=str(user["email"]),
        client_reference_id=str(user["id"]),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/contractor/billing?checkout=success",
        cancel_url=f"{base_url}/contractor/billing?checkout=cancelled",
        metadata={"user_id": str(user["id"]), "billing_mode": mode},
    )
    if not session.url:
        raise RuntimeError("Stripe did not return a checkout URL")
    return str(session.url)


def create_credit_checkout_session(user: sqlite3.Row) -> str:
    secret_key, price_id, mode = _stripe_config_for_user(user, credit_pack=True)
    if not secret_key or not price_id:
        raise RuntimeError("Stripe credit checkout is not configured")

    import stripe

    stripe.api_key = secret_key
    settings = get_settings()
    base_url = settings.app_host.rstrip("/")
    credit_amount = settings.contractor_credit_pack_size
    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=str(user["email"]),
        client_reference_id=str(user["id"]),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/contractor/billing?credits=success",
        cancel_url=f"{base_url}/contractor/billing?credits=cancelled",
        metadata={
            "user_id": str(user["id"]),
            "purchase_type": "call_credits",
            "credit_amount": str(credit_amount),
            "billing_mode": mode,
        },
    )
    if not session.url:
        raise RuntimeError("Stripe did not return a checkout URL")
    return str(session.url)


def parse_stripe_event(payload: bytes, signature: str | None) -> Any:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")

    import stripe

    if settings.stripe_webhook_secret or settings.stripe_test_webhook_secret:
        if not signature:
            raise ValueError("Missing Stripe signature")
        last_error: Exception | None = None
        for api_key, webhook_secret in (
            (settings.stripe_secret_key, settings.stripe_webhook_secret),
            (settings.stripe_test_secret_key, settings.stripe_test_webhook_secret),
        ):
            if not api_key or not webhook_secret:
                continue
            stripe.api_key = api_key
            try:
                return stripe.Webhook.construct_event(payload, signature, webhook_secret)
            except Exception as exc:
                last_error = exc
        if last_error:
            raise ValueError(str(last_error)) from last_error
        raise ValueError("No Stripe webhook secret is configured")
    stripe.api_key = settings.stripe_secret_key
    return stripe.Event.construct_from(json.loads(payload.decode("utf-8")), stripe.api_key)


def _timestamp_to_iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _stripe_object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def handle_stripe_event(event: Any) -> None:
    event_type = event["type"]
    data = _stripe_object_to_dict(event["data"]["object"])

    if event_type == "checkout.session.completed":
        user_id_raw = data.get("client_reference_id") or data.get("metadata", {}).get("user_id")
        if not user_id_raw:
            return
        metadata = data.get("metadata", {})
        if metadata.get("purchase_type") == "call_credits":
            if data.get("payment_status") in {"paid", "no_payment_required"}:
                from .db import add_call_credits

                try:
                    credits = int(metadata.get("credit_amount") or get_settings().contractor_credit_pack_size)
                except (TypeError, ValueError):
                    credits = get_settings().contractor_credit_pack_size
                add_call_credits(int(user_id_raw), credits)
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
        if status in ACTIVE_BILLING_STATUSES:
            settings = get_settings()
            grant_period_call_credits(
                int(user_id_raw),
                period_end=f"checkout:{subscription_id or data.get('id') or 'checkout'}",
                credits=settings.contractor_plan_call_credits,
                active_jobs_limit=settings.contractor_plan_active_jobs,
                leads_per_job_limit=settings.contractor_plan_leads_per_job,
            )
        return

    if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        customer_id = data.get("customer")
        if not customer_id:
            return
        status = str(data.get("status") or "inactive")
        current_period_end = _timestamp_to_iso(data.get("current_period_end"))
        updated = upsert_user_billing_by_customer(
            stripe_customer_id=str(customer_id),
            stripe_subscription_id=str(data.get("id")) if data.get("id") else None,
            status=status,
            current_period_end=current_period_end,
        )
        if updated and status in ACTIVE_BILLING_STATUSES:
            settings = get_settings()
            user_id = _user_id_for_customer(str(customer_id))
            if user_id is not None:
                subscription_id = str(data.get("id")) if data.get("id") else None
                if subscription_id and _checkout_credit_grant_already_applied(user_id, subscription_id):
                    _mark_credit_grant_period(user_id, current_period_end or subscription_id)
                else:
                    grant_period_call_credits(
                        user_id,
                        period_end=current_period_end or subscription_id,
                        credits=settings.contractor_plan_call_credits,
                        active_jobs_limit=settings.contractor_plan_active_jobs,
                        leads_per_job_limit=settings.contractor_plan_leads_per_job,
                    )


def _user_id_for_customer(stripe_customer_id: str) -> int | None:
    from .db import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_billing WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        ).fetchone()
        return int(row["user_id"]) if row else None


def _checkout_credit_grant_already_applied(user_id: int, subscription_id: str) -> bool:
    billing = get_user_billing(user_id)
    return bool(billing and billing["last_credit_grant_period_end"] == f"checkout:{subscription_id}")


def _mark_credit_grant_period(user_id: int, period_end: str) -> None:
    from .db import connect

    with connect() as conn:
        conn.execute(
            """
            UPDATE user_billing
            SET last_credit_grant_period_end = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (period_end, user_id),
        )
