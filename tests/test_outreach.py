from __future__ import annotations

from app.config import get_settings
from app.db import create_job, create_outreach_action, outreach_for_job, upsert_lead
from app.emailer import send_email
from app.emailer import _sender_value, split_subject_body
from app.outreach import execute_outreach_actions


def test_cloudflare_sender_value_parses_display_name() -> None:
    assert _sender_value("Sam <reports@msg.engineer>") == {"address": "reports@msg.engineer", "name": "Sam"}


def test_email_subject_is_split_from_body() -> None:
    subject, body = split_subject_body("Subject: Door fitting\n\nCan you quote this?")

    assert subject == "Door fitting"
    assert body == "Can you quote this?"


def test_execute_email_outreach(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
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
    lead_id = outreach_for_job(job_id)
    create_outreach_action(
        job_id=job_id,
        lead_id=1,
        channel="email",
        body="Subject: Door fitting\n\nCan you quote this?",
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("app.outreach.send_email", lambda to_email, body: sent.append((to_email, body)) or "smtp:test")

    result = execute_outreach_actions(job_id)
    actions = outreach_for_job(job_id)

    assert result == {"sent": 1, "blocked": 0, "failed": 0}
    assert sent == [("quotes@example.com", "Subject: Door fitting\n\nCan you quote this?")]
    assert actions[0]["status"] == "sent"
    get_settings.cache_clear()


def test_cloudflare_only_email_config_blocks_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_EMAIL_TOKEN", "token")
    monkeypatch.setenv("CLOUDFLARE_EMAIL_FROM", "Sam <contractors@example.com>")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    get_settings.cache_clear()

    try:
        send_email("quotes@example.com", "Subject: Door fitting\n\nCan you quote this?")
    except RuntimeError as exc:
        assert "No outbound email provider configured" in str(exc)
        assert "Cloudflare Email Routing is inbound-only" in str(exc)
    else:
        raise AssertionError("Cloudflare-only email config should not attempt outbound delivery")
    finally:
        get_settings.cache_clear()


def test_execute_text_outreach(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(title="Door fitting", job_type="door", description="Fit a door.", location="Gasport")
    upsert_lead(
        job_id=job_id,
        name="Door Person",
        phone="+17165550123",
        category="door",
        source_url="https://example.com",
        notes="",
        priority=80,
    )
    create_outreach_action(job_id=job_id, lead_id=1, channel="text", body="Can you quote this?")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("app.outreach.send_sms", lambda to_number, body: sent.append((to_number, body)) or "SMtest")

    result = execute_outreach_actions(job_id)
    actions = outreach_for_job(job_id)

    assert result == {"sent": 1, "blocked": 0, "failed": 0}
    assert sent == [("+17165550123", "Can you quote this?")]
    assert actions[0]["status"] == "sent"
    get_settings.cache_clear()
