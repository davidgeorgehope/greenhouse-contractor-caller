from __future__ import annotations


def test_local_test_billing_activation_and_reset(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")

    from app.auth import create_user
    from app.billing import call_credits_remaining, can_use_paid_workflows
    from app.config import get_settings
    from app.db import get_user_billing
    from app.test_harness import activate_test_subscription, reset_local_test_billing

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")

    assert can_use_paid_workflows(user_id) is False

    assert activate_test_subscription(user_id) is True

    billing = get_user_billing(user_id)
    assert billing is not None
    assert billing["status"] == "active"
    assert billing["stripe_customer_id"] == f"cus_test_local_{user_id}"
    assert call_credits_remaining(user_id) == 10
    assert can_use_paid_workflows(user_id) is True

    assert reset_local_test_billing(user_id) is True
    billing = get_user_billing(user_id)
    assert billing is not None
    assert billing["status"] == "inactive"
    assert billing["call_credits_remaining"] == 0


def test_reset_refuses_non_test_billing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))

    from app.auth import create_user
    from app.config import get_settings
    from app.db import get_user_billing, upsert_user_billing
    from app.test_harness import reset_local_test_billing

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id="cus_live_real",
        stripe_subscription_id="sub_live_real",
        status="active",
    )

    assert reset_local_test_billing(user_id) is False
    assert get_user_billing(user_id)["status"] == "active"


def test_activate_test_billing_refuses_real_stripe_customer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))

    from app.auth import create_user
    from app.config import get_settings
    from app.db import get_user_billing, upsert_user_billing
    from app.test_harness import activate_test_subscription

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id="cus_live_real",
        stripe_subscription_id="sub_live_real",
        status="active",
    )

    assert activate_test_subscription(user_id) is False
    billing = get_user_billing(user_id)
    assert billing["stripe_customer_id"] == "cus_live_real"
    assert billing["stripe_subscription_id"] == "sub_live_real"


def test_test_contractor_agent_consumes_credit_and_writes_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")

    from app.auth import create_user
    from app.billing import call_credits_remaining
    from app.config import get_settings
    from app.db import call_for_id, create_job
    from app.test_harness import activate_test_subscription, simulate_test_contractor_call

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    assert activate_test_subscription(user_id) is True
    job_id = create_job(
        title="Greenhouse assembly",
        job_type="assembly",
        description="Assemble greenhouse.",
        location="Gasport",
        user_id=user_id,
    )

    call_id = simulate_test_contractor_call(job_id=job_id, user_id=user_id, scenario="needs_photos")

    call = call_for_id(call_id)
    assert call is not None
    assert call["direction"] == "test_agent"
    assert call["status"] == "completed"
    assert call["outcome"] == "conversation"
    assert "needs photos" in call["summary"].lower()
    assert "Test contractor" in call["lead_name"]
    assert call_credits_remaining(user_id) == 9


def test_test_contractor_agent_blocks_without_credits(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")

    import pytest

    from app.auth import create_user
    from app.config import get_settings
    from app.db import create_job, upsert_user_billing
    from app.test_harness import simulate_test_contractor_call

    get_settings.cache_clear()
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id="cus_test_local_1",
        stripe_subscription_id="sub_test_local_1",
        status="active",
    )
    job_id = create_job(title="Door", job_type="door", description="Fix door.", location="Buffalo", user_id=user_id)

    with pytest.raises(RuntimeError):
        simulate_test_contractor_call(job_id=job_id, user_id=user_id)


def test_realtime_test_contractor_agent_uses_gpt_realtime_and_consumes_credit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_BILLING_REQUIRED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2")

    import asyncio
    import json

    from app.auth import create_user
    from app.billing import call_credits_remaining
    from app.config import get_settings
    from app.db import call_for_id, create_job
    from app.test_harness import activate_test_subscription, simulate_realtime_test_contractor_call

    get_settings.cache_clear()
    sent_messages: list[dict[str, object]] = []
    connect_calls: list[tuple[str, dict[str, object]]] = []

    class FakeRealtime:
        def __init__(self) -> None:
            self._done = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def send(self, message: str) -> None:
            sent_messages.append(json.loads(message))

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return json.dumps(
                {
                    "type": "response.done",
                    "response": {
                        "output": [
                            {
                                "content": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "transcript": "Sam: Can you help?\nContractor: Yes, send photos.",
                                                "summary": "Realtime test contractor needs photos before quoting.",
                                                "outcome": "conversation",
                                            }
                                        )
                                    }
                                ]
                            }
                        ]
                    },
                }
            )

    def fake_connect(uri: str, **kwargs):
        connect_calls.append((uri, kwargs))
        return FakeRealtime()

    monkeypatch.setattr("app.test_harness.websockets.connect", fake_connect)
    user_id = create_user(email="owner@example.com", password="long-password-123", display_name="Owner")
    assert activate_test_subscription(user_id) is True
    job_id = create_job(
        title="Greenhouse assembly",
        job_type="assembly",
        description="Assemble greenhouse.",
        location="Gasport",
        user_id=user_id,
    )

    call_id = asyncio.run(
        simulate_realtime_test_contractor_call(job_id=job_id, user_id=user_id, scenario="needs_photos")
    )

    call = call_for_id(call_id)
    assert call is not None
    assert call["direction"] == "test_realtime_agent"
    assert call["twilio_sid"] == f"TEST_REALTIME_{call_id}"
    assert call["status"] == "completed"
    assert call["outcome"] == "conversation"
    assert "needs photos" in call["summary"].lower()
    assert "Realtime test contractor" in call["lead_name"]
    assert call_credits_remaining(user_id) == 9
    assert connect_calls[0][0] == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"
    assert sent_messages[0]["session"]["output_modalities"] == ["text"]
