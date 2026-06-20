from __future__ import annotations

import argparse
import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .auth import create_user
from .billing import call_credits_remaining, handle_stripe_event
from .config import get_settings
from .db import (
    append_event,
    connect,
    create_call,
    create_email_message,
    create_job,
    create_outreach_action,
    create_signup,
    create_sms_message,
    job_for_id,
    leads_for_job,
    mark_lead_status,
    update_call,
    update_outreach_action,
    upsert_lead,
)
from .test_harness import _parse_realtime_result, _run_realtime_contractor_scenario


@dataclass(frozen=True)
class LeadInput:
    name: str
    phone: str
    email: str
    source_url: str
    notes: str = ""


def parse_lead(value: str) -> LeadInput:
    parts = [part.strip() for part in value.split("|")]
    if len(parts) < 4:
        raise argparse.ArgumentTypeError("lead must be NAME|PHONE|EMAIL|SOURCE_URL|NOTES")
    while len(parts) < 5:
        parts.append("")
    return LeadInput(*parts[:5])


def _unique_email(prefix: str = "contractorrelief-e2e") -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"email.djhope+{prefix}-{stamp}-{suffix}@gmail.com"


def _create_test_subscription(user_id: int, email: str) -> dict[str, str]:
    settings = get_settings()
    if not settings.stripe_test_secret_key or not settings.stripe_test_price_id:
        raise RuntimeError("Missing STRIPE_TEST_SECRET_KEY or STRIPE_TEST_PRICE_ID")

    import stripe

    stripe.api_key = settings.stripe_test_secret_key
    payment_method = stripe.PaymentMethod.create(type="card", card={"token": "tok_visa"})
    customer = stripe.Customer.create(
        email=email,
        payment_method=payment_method.id,
        invoice_settings={"default_payment_method": payment_method.id},
    )
    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": settings.stripe_test_price_id}],
        default_payment_method=payment_method.id,
    )
    handle_stripe_event(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user_id),
                    "customer": customer.id,
                    "subscription": subscription.id,
                    "payment_status": "paid",
                    "metadata": {"user_id": str(user_id), "billing_mode": "test"},
                }
            },
        }
    )
    return {"customer_id": str(customer.id), "subscription_id": str(subscription.id)}


def _lead_by_phone(job_id: int, phone: str) -> Any:
    for lead in leads_for_job(job_id):
        if str(lead["phone"]) == phone:
            return lead
    raise RuntimeError(f"Lead was not inserted: {phone}")


async def _run_fake_realtime_call(job_id: int, user_id: int, lead_id: int, scenario: str) -> int:
    from .billing import reserve_call_credit

    job = job_for_id(job_id, user_id)
    if job is None:
        raise RuntimeError("Job not found")
    if not reserve_call_credit(user_id):
        raise RuntimeError("No call credits remaining")

    call_id = create_call(lead_id, direction="test_realtime_agent")
    now = datetime.now(UTC).isoformat()
    update_call(call_id, twilio_sid=f"E2E_REALTIME_{call_id}", status="in_progress", started_at=now)
    append_event(call_id, "e2e_realtime_fake_contractor_started", {"scenario": scenario, "user_id": user_id})

    raw_response = await _run_realtime_contractor_scenario(
        job_title=str(job["title"]),
        job_description=str(job["description"]),
        job_location=str(job["location"]),
        scenario=scenario,
    )
    transcript, summary, outcome = _parse_realtime_result(raw_response, str(job["title"]), scenario)
    ended = datetime.now(UTC).isoformat()
    update_call(
        call_id,
        status="completed",
        outcome=outcome,
        summary=summary,
        transcript=transcript,
        ended_at=ended,
    )
    mark_lead_status(lead_id, "called")
    append_event(call_id, "e2e_realtime_fake_contractor_completed", {"raw_response": raw_response})
    return call_id


def _execute_mock_outreach(job_id: int) -> dict[str, int]:
    sent = 0
    with connect() as conn:
        actions = list(
            conn.execute(
                """
                SELECT outreach_actions.*, leads.phone AS lead_phone, leads.email AS lead_email
                FROM outreach_actions
                LEFT JOIN leads ON leads.id = outreach_actions.lead_id
                WHERE outreach_actions.job_id = ?
                  AND outreach_actions.status IN ('draft', 'queued')
                ORDER BY outreach_actions.id
                """,
                (job_id,),
            )
        )
    for action in actions:
        action_id = int(action["id"])
        channel = str(action["channel"])
        body = str(action["body"] or "")
        receipt = f"mock-{channel}-{action_id}"
        if channel == "text":
            create_sms_message(
                direction="outbound",
                from_number=get_settings().twilio_from or "+10000000000",
                to_number=str(action["lead_phone"] or "+15005550006"),
                body=body,
                twilio_sid=receipt,
                status="sent",
                raw_payload={"e2e_mock": True},
            )
        elif channel == "email":
            create_email_message(
                direction="outbound",
                from_email=get_settings().cloudflare_email_from or "test@contractorrelief.ai",
                to_email=str(action["lead_email"] or "contractor@example.com"),
                subject="Contractor Relief test follow-up",
                body=body,
                message_id=receipt,
                status="sent",
                raw_payload={"e2e_mock": True},
            )
        else:
            update_outreach_action(action_id, status="blocked", notes=f"Unsupported channel: {channel}")
            continue
        update_outreach_action(
            action_id,
            status="sent",
            notes=f"E2E mock send receipt: {receipt}",
            completed_at=datetime.now(UTC).isoformat(),
        )
        sent += 1
    return {"sent": sent, "blocked": 0, "failed": 0}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    email = args.email or _unique_email()
    password_generated = not bool(args.password)
    password = args.password or f"E2E-{secrets.token_urlsafe(18)}"
    display_name = "Contractor Relief E2E"
    user_id = create_user(email=email, password=password, display_name=display_name)
    create_signup(
        email=email,
        display_name=display_name,
        project_type="Greenhouse assembly",
        location="Gasport, NY",
        notes="E2E test signup. No real contractors should be contacted.",
        source="e2e_harness",
    )

    stripe_result = _create_test_subscription(user_id, email)
    credits_before = call_credits_remaining(user_id)
    job_id = create_job(
        title=args.job_title,
        job_type="assembly",
        description=args.job_description,
        location=args.location,
        user_id=user_id,
    )

    inserted_leads: list[dict[str, Any]] = []
    for index, lead in enumerate(args.leads, start=1):
        upsert_lead(
            job_id=job_id,
            name=lead.name,
            phone=lead.phone,
            email=lead.email,
            category="real_contractor_e2e",
            source_url=lead.source_url,
            notes=lead.notes or "Real contractor/source captured for E2E; outbound routed to fake contractor.",
            priority=100 - index,
            service_area="Western New York",
            status="pending",
        )
        row = _lead_by_phone(job_id, lead.phone)
        inserted_leads.append({"id": int(row["id"]), "name": row["name"], "phone": row["phone"], "email": row["email"]})

    if not inserted_leads:
        raise RuntimeError("At least one --lead is required")

    call_id = await _run_fake_realtime_call(
        job_id=job_id,
        user_id=user_id,
        lead_id=int(inserted_leads[0]["id"]),
        scenario=args.scenario,
    )
    credits_after_call = call_credits_remaining(user_id)

    create_outreach_action(
        job_id=job_id,
        lead_id=int(inserted_leads[0]["id"]),
        channel="text",
        status="queued",
        body="Hi, this is Sam with Contractor Relief. Thanks for the call. Can you send rough availability and what you need to quote this greenhouse assembly?",
    )
    create_outreach_action(
        job_id=job_id,
        lead_id=int(inserted_leads[0]["id"]),
        channel="email",
        status="queued",
        body=(
            "Subject: Greenhouse assembly near Gasport\n\n"
            "Hi, this is Sam with Contractor Relief. Following up on the greenhouse assembly job near Gasport. "
            "Can you reply with availability, rough price range, and what details you need next?"
        ),
    )
    outreach_result = _execute_mock_outreach(job_id)

    with connect() as conn:
        call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        sms_count = conn.execute("SELECT COUNT(*) FROM sms_messages WHERE raw_payload_json LIKE '%e2e_mock%'" ).fetchone()[0]
        email_count = conn.execute("SELECT COUNT(*) FROM email_messages WHERE raw_payload_json LIKE '%e2e_mock%'" ).fetchone()[0]

    return {
        "ok": True,
        "email": email,
        "password_generated": password_generated,
        "user_id": user_id,
        "stripe": stripe_result,
        "credits_before_call": credits_before,
        "credits_after_call": credits_after_call,
        "job_id": job_id,
        "leads": inserted_leads,
        "call": {
            "id": call_id,
            "status": call["status"],
            "outcome": call["outcome"],
            "summary": call["summary"],
            "transcript": call["transcript"],
        },
        "outreach": outreach_result,
        "mock_sms_rows_total": sms_count,
        "mock_email_rows_total": email_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a safe Contractor Relief end-to-end test.")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--job-title", default="10x10 greenhouse assembly")
    parser.add_argument("--job-description", default="Assemble a 10x10 Janssens/Exaco greenhouse kit near Gasport, NY.")
    parser.add_argument("--location", default="Gasport, NY")
    parser.add_argument("--scenario", default="needs_photos")
    parser.add_argument("--lead", dest="leads", action="append", type=parse_lead, default=[])
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
