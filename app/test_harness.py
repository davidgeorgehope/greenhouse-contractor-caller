from __future__ import annotations

from datetime import UTC, datetime

from .billing import reserve_call_credit
from .config import get_settings
from .db import (
    add_call_credits,
    append_event,
    connect,
    create_call,
    grant_period_call_credits,
    job_for_id,
    leads_for_job,
    mark_lead_status,
    update_call,
    upsert_lead,
    upsert_user_billing,
)


TEST_CUSTOMER_PREFIX = "cus_test_local_"
TEST_SUBSCRIPTION_PREFIX = "sub_test_local_"


def activate_test_subscription(user_id: int) -> None:
    settings = get_settings()
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id=f"{TEST_CUSTOMER_PREFIX}{user_id}",
        stripe_subscription_id=f"{TEST_SUBSCRIPTION_PREFIX}{user_id}",
        status="active",
        current_period_end="test-current-period",
    )
    grant_period_call_credits(
        user_id,
        period_end="test-current-period",
        credits=settings.contractor_plan_call_credits,
        active_jobs_limit=settings.contractor_plan_active_jobs,
        leads_per_job_limit=settings.contractor_plan_leads_per_job,
    )


def add_test_call_credits(user_id: int, credits: int | None = None) -> int:
    amount = credits or get_settings().contractor_credit_pack_size
    add_call_credits(user_id, amount)
    return amount


def reset_local_test_billing(user_id: int) -> bool:
    with connect() as conn:
        billing = conn.execute("SELECT * FROM user_billing WHERE user_id = ?", (user_id,)).fetchone()
        if not billing or not str(billing["stripe_customer_id"] or "").startswith(TEST_CUSTOMER_PREFIX):
            return False
        conn.execute(
            """
            UPDATE user_billing
            SET status='inactive',
                call_credits_remaining=0,
                stripe_customer_id=NULL,
                stripe_subscription_id=NULL,
                current_period_end=NULL,
                last_credit_grant_period_end=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?
            """,
            (user_id,),
        )
        return True


def simulate_test_contractor_call(*, job_id: int, user_id: int, scenario: str = "available") -> int:
    job = job_for_id(job_id, user_id)
    if job is None:
        raise ValueError("Job not found for user")
    if not reserve_call_credit(user_id):
        raise RuntimeError("No call credits remaining")

    phone = "+17165550199"
    upsert_lead(
        job_id=job_id,
        name="Test contractor agent",
        phone=phone,
        email="test-contractor@example.com",
        category="test_call",
        source_url="local-test-harness",
        notes="Deterministic fake contractor used by the owner-only test harness.",
        priority=99,
        status="pending",
    )
    lead = next((row for row in leads_for_job(job_id) if str(row["phone"]) == phone), None)
    if lead is None:
        raise RuntimeError("Could not create test contractor lead")

    call_id = create_call(int(lead["id"]), direction="test_agent")
    now = datetime.now(UTC).isoformat()
    transcript, summary, outcome = _scenario_result(str(job["title"]), scenario)
    update_call(
        call_id,
        twilio_sid=f"TEST_AGENT_{call_id}",
        status="completed",
        outcome=outcome,
        summary=summary,
        transcript=transcript,
        started_at=now,
        ended_at=now,
    )
    mark_lead_status(int(lead["id"]), "called")
    append_event(
        call_id,
        "test_agent_simulation",
        {
            "scenario": scenario,
            "job_id": job_id,
            "user_id": user_id,
            "consumed_call_credit": True,
        },
    )
    return call_id


def _scenario_result(job_title: str, scenario: str) -> tuple[str, str, str]:
    normalized = scenario.strip().lower()
    if normalized == "busy":
        transcript = (
            "Sam: Hi, this is Sam calling for a customer about "
            f"{job_title}.\n"
            "Contractor: We are booked out six weeks and cannot take this one. "
            "Try a smaller handyman shop."
        )
        return transcript, "Test contractor declined because they are booked out six weeks.", "likely_no"
    if normalized == "needs_photos":
        transcript = (
            "Sam: Hi, this is Sam calling for a customer about "
            f"{job_title}.\n"
            "Contractor: We may be able to help. Text or email photos and the site address, "
            "then we can give a rough estimate."
        )
        return transcript, "Test contractor may be available but needs photos and the site address.", "conversation"
    transcript = (
        "Sam: Hi, this is Sam calling for a customer about "
        f"{job_title}.\n"
        "Contractor: Yes, we can help. We have availability next week. "
        "A small job like that usually starts around $250, depending on site conditions."
    )
    return transcript, "Test contractor is available next week; rough starting price is $250.", "conversation"
