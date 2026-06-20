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
