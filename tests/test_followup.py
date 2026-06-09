from __future__ import annotations

from app.config import get_settings
from app.db import create_job, next_pending_leads, outreach_for_job, upsert_lead
from app.followup import create_call_followups


def test_missed_call_creates_text_followup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Door fitting",
        job_type="door_installation",
        description="Fit an exterior door.",
        location="Gasport, NY",
    )
    upsert_lead(
        job_id=job_id,
        name="Door Person",
        phone="+17165550107",
        category="door_installer",
        source_url="https://example.com/door",
        notes="good fit",
        priority=80,
    )
    lead = next_pending_leads(
        1,
        max_drive_minutes=90,
        max_distance_miles=75,
        job_id=job_id,
        include_unknown_travel=True,
    )[0]

    created = create_call_followups(call_id=123, lead=lead, call_status="no-answer", summary="No answer.")
    actions = outreach_for_job(job_id)

    assert len(created) == 1
    assert actions[0]["channel"] == "text"
    assert actions[0]["status"] == "draft"
    assert "call_id=123" in actions[0]["notes"]
    get_settings.cache_clear()


def test_transcript_request_for_email_creates_email_followup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Door fitting",
        job_type="door_installation",
        description="Fit an exterior door.",
        location="Gasport, NY",
    )
    upsert_lead(
        job_id=job_id,
        name="Door Person",
        phone="+17165550108",
        email="quotes@example.com",
        category="door_installer",
        source_url="https://example.com/door",
        notes="good fit",
        priority=80,
    )
    lead = next_pending_leads(
        1,
        max_drive_minutes=90,
        max_distance_miles=75,
        job_id=job_id,
        include_unknown_travel=True,
    )[0]

    created = create_call_followups(
        call_id=456,
        lead=lead,
        call_status="completed",
        outcome="conversation",
        summary="Contractor asked for details by email.",
        transcript="contractor: Can you email me the details and photos?",
    )
    actions = outreach_for_job(job_id)

    assert len(created) == 1
    assert actions[0]["channel"] == "email"
    assert actions[0]["status"] == "draft"
    assert "Subject: Door fitting" in actions[0]["body"]
    get_settings.cache_clear()
