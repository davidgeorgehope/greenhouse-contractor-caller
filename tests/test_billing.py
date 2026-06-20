from __future__ import annotations

import sys
from types import SimpleNamespace


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


def test_owner_checkout_uses_stripe_test_key_and_price(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_real")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_live_base")
    monkeypatch.setenv("STRIPE_TEST_SECRET_KEY", "sk_test_owner")
    monkeypatch.setenv("STRIPE_TEST_PRICE_ID", "price_test_base")

    from app.auth import create_user, authenticate_user
    from app.billing import create_checkout_session
    from app.config import get_settings

    get_settings.cache_clear()
    created: list[dict[str, object]] = []

    class FakeCheckoutSession:
        @staticmethod
        def create(**kwargs):
            created.append({"api_key": fake_stripe.api_key, **kwargs})
            return SimpleNamespace(url="https://checkout.stripe.test/session")

    fake_stripe = SimpleNamespace(
        api_key="",
        checkout=SimpleNamespace(Session=FakeCheckoutSession),
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    create_user(email="email.djhope@gmail.com", password="long-password-123", display_name="David")
    user = authenticate_user("email.djhope@gmail.com", "long-password-123")
    assert user is not None

    assert create_checkout_session(user) == "https://checkout.stripe.test/session"

    assert created[0]["api_key"] == "sk_test_owner"
    assert created[0]["line_items"] == [{"price": "price_test_base", "quantity": 1}]
    assert created[0]["metadata"]["billing_mode"] == "test"


def test_customer_checkout_uses_live_key_and_price(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_real")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_live_base")
    monkeypatch.setenv("STRIPE_TEST_SECRET_KEY", "sk_test_owner")
    monkeypatch.setenv("STRIPE_TEST_PRICE_ID", "price_test_base")

    from app.auth import create_user, authenticate_user
    from app.billing import create_checkout_session
    from app.config import get_settings

    get_settings.cache_clear()
    created: list[dict[str, object]] = []

    class FakeCheckoutSession:
        @staticmethod
        def create(**kwargs):
            created.append({"api_key": fake_stripe.api_key, **kwargs})
            return SimpleNamespace(url="https://checkout.stripe.live/session")

    fake_stripe = SimpleNamespace(
        api_key="",
        checkout=SimpleNamespace(Session=FakeCheckoutSession),
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    create_user(email="customer@example.com", password="long-password-123", display_name="Customer")
    user = authenticate_user("customer@example.com", "long-password-123")
    assert user is not None

    assert create_checkout_session(user) == "https://checkout.stripe.live/session"

    assert created[0]["api_key"] == "sk_live_real"
    assert created[0]["line_items"] == [{"price": "price_live_base", "quantity": 1}]
    assert created[0]["metadata"]["billing_mode"] == "live"
