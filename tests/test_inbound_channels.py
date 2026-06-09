from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db import calls_for_job, create_job, emails_for_job, leads_for_job, sms_for_job, update_job_status, upsert_lead
from app.main import inbound_email, incoming, sms


class FakeFormRequest:
    def __init__(self, form: dict[str, str]) -> None:
        self._form = form

    async def form(self) -> dict[str, str]:
        return self._form


class FakeJsonRequest:
    def __init__(self, headers: dict[str, str], payload: dict[str, str]) -> None:
        self.headers = headers
        self._payload = payload

    async def json(self) -> dict[str, str]:
        return self._payload


def test_inbound_callback_matches_lead_and_streams_to_realtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("APP_HOST", "https://contractor.msg.engineer")
    get_settings.cache_clear()
    job_id = create_job(title="Door fitting", job_type="door", description="Fit an exterior door.", location="Gasport")
    upsert_lead(
        job_id=job_id,
        name="Door Person",
        phone="+17165550123",
        category="door",
        source_url="https://example.com",
        notes="",
        priority=80,
    )

    response = asyncio.run(
        incoming(FakeFormRequest({"From": "(716) 555-0123", "To": "+17165550100", "CallSid": "CA123"}))
    )

    body = response.body.decode("utf-8")
    calls = calls_for_job(job_id)
    assert response.media_type == "application/xml"
    assert "wss://contractor.msg.engineer/greenhouse/stream/" in body
    assert calls[0]["direction"] == "inbound"
    assert calls[0]["twilio_sid"] == "CA123"
    get_settings.cache_clear()


def test_unknown_inbound_sms_gets_linked_to_active_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    update_job_status(1, "done")
    job_id = create_job(title="Door fitting", job_type="door", description="Fit an exterior door.", location="Gasport")

    asyncio.run(sms(FakeFormRequest({"From": "716-555-0199", "To": "+17165550100", "Body": "I can quote this."})))

    leads = leads_for_job(job_id)
    texts = sms_for_job(job_id)
    assert leads[0]["phone"] == "+17165550199"
    assert texts[0]["body"] == "I can quote this."
    assert texts[0]["lead_name"] == "+17165550199"
    get_settings.cache_clear()


def test_unknown_inbound_email_gets_linked_to_active_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_EMAIL_INGEST_SECRET", "secret")
    get_settings.cache_clear()
    update_job_status(1, "done")
    job_id = create_job(title="Door fitting", job_type="door", description="Fit an exterior door.", location="Gasport")

    response = asyncio.run(
        inbound_email(
            FakeJsonRequest(
                {"authorization": "Bearer secret"},
                {
                    "from": "quotes@example.com",
                    "to": "contractors@msg.engineer",
                    "subject": "Door quote",
                    "text": "Send photos and I can price it.",
                    "message_id": "<quote@example.com>",
                },
            )
        )
    )

    emails = emails_for_job(job_id)
    assert response == {"ok": "true"}
    assert emails[0]["lead_email"] == "quotes@example.com"
    assert emails[0]["body"] == "Send photos and I can price it."
    get_settings.cache_clear()


def test_unknown_inbound_sms_is_not_guessed_when_multiple_jobs_are_open(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    greenhouse_job_id = create_job(
        title="Greenhouse assembly",
        job_type="greenhouse",
        description="Assemble greenhouse.",
        location="Gasport",
    )
    door_job_id = create_job(title="Door fitting", job_type="door", description="Fit an exterior door.", location="Gasport")

    asyncio.run(sms(FakeFormRequest({"From": "716-555-0199", "To": "+17165550100", "Body": "Can call later."})))

    assert leads_for_job(greenhouse_job_id) == []
    assert leads_for_job(door_job_id) == []
    assert sms_for_job(greenhouse_job_id) == []
    assert sms_for_job(door_job_id) == []
    get_settings.cache_clear()
