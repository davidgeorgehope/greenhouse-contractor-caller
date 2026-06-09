from __future__ import annotations

from app.caller import place_test_call
from app.config import get_settings
from app.db import calls_for_job, create_job


class FakeCall:
    sid = "CA_TEST"
    status = "queued"


class FakeCalls:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return FakeCall()


class FakeClient:
    last = None

    def __init__(self, account_sid: str, auth_token: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.calls = FakeCalls()
        FakeClient.last = self


def test_place_test_call_uses_selected_job_realtime_twiml(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("CALLER_DISABLED", "0")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_TEST")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("TWILIO_FROM", "+17165550100")
    monkeypatch.setenv("APP_HOST", "https://contractor.msg.engineer")
    get_settings.cache_clear()
    monkeypatch.setattr("app.caller.Client", FakeClient)
    job_id = create_job(title="Door fitting", job_type="door", description="Fit a door.", location="Gasport")

    receipt = place_test_call(job_id=job_id, to_number="716-555-0199")

    calls = calls_for_job(job_id)
    created = FakeClient.last.calls.created[0]
    assert "CA_TEST" in receipt
    assert calls[0]["direction"] == "test"
    assert created["to"] == "+17165550199"
    assert created["from_"] == "+17165550100"
    assert created["url"] == f"https://contractor.msg.engineer/greenhouse/twiml/{calls[0]['id']}"
    assert created["status_callback"] == f"https://contractor.msg.engineer/greenhouse/status/{calls[0]['id']}"
    get_settings.cache_clear()
