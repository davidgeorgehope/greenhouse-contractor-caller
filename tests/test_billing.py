from __future__ import annotations


def test_billing_is_open_when_not_required(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "0")

    from app.config import get_settings
    from app.billing import can_use_paid_workflows

    get_settings.cache_clear()

    assert can_use_paid_workflows(123) is True


def test_billing_blocks_until_subscription_active(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")

    from app.config import get_settings
    from app.auth import create_user
    from app.billing import can_use_paid_workflows
    from app.db import upsert_user_billing

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")

    assert can_use_paid_workflows(user_id) is False

    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        status="active",
    )

    assert can_use_paid_workflows(user_id) is True


def test_call_credits_are_consumed_when_billing_required(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")

    from app.config import get_settings
    from app.auth import create_user
    from app.billing import call_credits_remaining, reserve_call_credit
    from app.db import upsert_user_billing

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        status="active",
    )

    assert reserve_call_credit(user_id) is False

    from app.db import add_call_credits

    add_call_credits(user_id, 2)

    assert call_credits_remaining(user_id) == 2
    assert reserve_call_credit(user_id) is True
    assert call_credits_remaining(user_id) == 1
    assert reserve_call_credit(user_id) is True
    assert call_credits_remaining(user_id) == 0
    assert reserve_call_credit(user_id) is False


def test_plan_limits_block_extra_jobs_and_leads(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")

    from app.config import get_settings
    from app.auth import create_user
    from app.billing import can_add_paid_lead, can_create_paid_job
    from app.db import create_job, upsert_lead, upsert_user_billing

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        status="active",
    )

    assert can_create_paid_job(user_id) is True
    job_ids = [
        create_job(title=f"Job {index}", job_type="general", description="Work", location="Buffalo", user_id=user_id)
        for index in range(5)
    ]
    assert can_create_paid_job(user_id) is False

    job_id = job_ids[0]
    for index in range(10):
        upsert_lead(
            job_id=job_id,
            name=f"Lead {index}",
            phone=f"+17165550{index:03d}",
            category="contractor",
            source_url="https://example.com",
            notes="",
            priority=50,
        )

    assert can_add_paid_lead(user_id, job_id) is False


def test_credit_checkout_webhook_adds_call_credits(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))

    from app.config import get_settings
    from app.auth import create_user
    from app.billing import call_credits_remaining, handle_stripe_event

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")

    handle_stripe_event(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(user_id),
                    "payment_status": "paid",
                    "metadata": {"purchase_type": "call_credits", "credit_amount": "10"},
                }
            },
        }
    )

    assert call_credits_remaining(user_id) == 10
