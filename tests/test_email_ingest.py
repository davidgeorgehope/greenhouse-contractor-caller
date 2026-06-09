from __future__ import annotations

import asyncio

from starlette.responses import Response

from app.config import get_settings
from app.db import create_job, emails_for_job, upsert_lead
from app.main import inbound_email


class FakeRequest:
    def __init__(self, headers: dict[str, str], payload: dict[str, str]) -> None:
        self.headers = headers
        self._payload = payload

    async def json(self) -> dict[str, str]:
        return self._payload


def test_inbound_email_is_stored_and_matched_to_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_EMAIL_INGEST_SECRET", "secret")
    get_settings.cache_clear()
    job_id = create_job(title="Door fitting", job_type="door", description="Fit a door.", location="Gasport")
    upsert_lead(
        job_id=job_id,
        name="Door Person",
        phone="+17165550123",
        email="quotes@example.com",
        category="door",
        source_url="https://example.com",
        notes="",
        priority=80,
    )

    response = asyncio.run(
        inbound_email(
            FakeRequest(
                {"authorization": "Bearer secret"},
                {
                    "from": "quotes@example.com",
                    "to": "contractors@msg.engineer",
                    "subject": "Door fitting",
                    "text": "We can help next week.",
                    "message_id": "<test@example.com>",
                },
            )
        )
    )

    assert response == {"ok": "true"}
    emails = emails_for_job(job_id)
    assert len(emails) == 1
    assert emails[0]["lead_name"] == "Door Person"
    assert emails[0]["body"] == "We can help next week."
    get_settings.cache_clear()


def test_inbound_email_rejects_missing_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_EMAIL_INGEST_SECRET", "secret")
    get_settings.cache_clear()

    response = asyncio.run(inbound_email(FakeRequest({}, {})))

    assert isinstance(response, Response)
    assert response.status_code == 401
    get_settings.cache_clear()
