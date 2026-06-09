from __future__ import annotations

from app.config import get_settings
from app.db import (
    call_for_id,
    calls_for_job,
    create_call,
    create_job,
    create_sms_message,
    delete_test_calls_for_job,
    job_for_id,
    leads_for_job,
    next_pending_leads,
    sms_for_job,
    update_call,
    update_job_brief,
    update_job_status,
    upsert_lead,
)


def test_next_pending_leads_filters_by_travel_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    upsert_lead(
        name="Close Contractor",
        phone="+17165550101",
        category="handyman_assembly",
        source_url="https://example.com/close",
        notes="close",
        priority=80,
        distance_miles=20,
        drive_minutes=35,
    )
    upsert_lead(
        name="Too Far Contractor",
        phone="+17165550102",
        category="handyman_assembly",
        source_url="https://example.com/far",
        notes="far",
        priority=100,
        distance_miles=90,
        drive_minutes=125,
    )
    upsert_lead(
        name="Manufacturer Referral",
        phone="+17165550103",
        category="manufacturer_referral",
        source_url="https://example.com/referral",
        notes="referral",
        priority=70,
    )

    leads = next_pending_leads(10, max_drive_minutes=90, max_distance_miles=75)

    assert [lead["name"] for lead in leads] == ["Close Contractor", "Manufacturer Referral"]
    get_settings.cache_clear()


def test_call_for_id_returns_transcript_context(tmp_path, monkeypatch) -> None:
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
        phone="+17165550104",
        category="door_installer",
        source_url="https://example.com/door",
        notes="good fit",
        priority=80,
        distance_miles=12,
        drive_minutes=25,
    )
    lead = next_pending_leads(1, max_drive_minutes=90, max_distance_miles=75)[0]
    call_id = create_call(int(lead["id"]))
    update_call(call_id, status="completed", outcome="conversation", summary="Asked for photos.", transcript="contractor: send photos")

    call = call_for_id(call_id)

    assert call is not None
    assert call["job_title"] == "Door fitting"
    assert call["lead_name"] == "Door Person"
    assert call["transcript"] == "contractor: send photos"
    get_settings.cache_clear()


def test_delete_test_calls_for_job_keeps_real_calls(tmp_path, monkeypatch) -> None:
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
        phone="+17165550109",
        category="door_installer",
        source_url="https://example.com/door",
        notes="good fit",
        priority=80,
    )
    upsert_lead(
        job_id=job_id,
        name="Demo test call",
        phone="+17165550110",
        category="test_call",
        source_url="dashboard",
        notes="test",
        priority=1,
        status="test",
    )
    leads = next_pending_leads(
        10,
        max_drive_minutes=90,
        max_distance_miles=75,
        job_id=job_id,
        include_unknown_travel=True,
    )
    real_lead = next(lead for lead in leads if lead["name"] == "Door Person")
    test_lead = next(lead for lead in leads_for_job(job_id) if lead["name"] == "Demo test call")
    real_call_id = create_call(int(real_lead["id"]))
    test_call_id = create_call(int(test_lead["id"]), direction="test")
    update_call(real_call_id, transcript="contractor: real call")
    update_call(test_call_id, transcript="david: test call")

    assert delete_test_calls_for_job(job_id) == 1

    calls = calls_for_job(job_id)
    leads_after = leads_for_job(job_id)
    assert [call["id"] for call in calls] == [real_call_id]
    assert calls[0]["transcript"] == "contractor: real call"
    assert all(lead["category"] != "test_call" for lead in leads_after)
    get_settings.cache_clear()


def test_job_brief_updates_only_while_planning(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Door fitting",
        job_type="door_installation",
        description="Fit an exterior door.",
        location="Gasport, NY",
    )

    assert (
        update_job_brief(
            job_id,
            "New brief\nAsk about threshold.",
            title="Front door replacement",
            description="Replace the exterior front door and frame.",
            location="Gasport, NY 14067",
        )
        is True
    )
    job = job_for_id(job_id)
    assert job["title"] == "Front door replacement"
    assert job["description"] == "Replace the exterior front door and frame."
    assert job["location"] == "Gasport, NY 14067"
    assert job["brief"] == "New brief\nAsk about threshold."

    update_job_status(job_id, "active")

    assert update_job_brief(job_id, "Should not overwrite") is False
    assert job_for_id(job_id)["brief"] == "New brief\nAsk about threshold."
    get_settings.cache_clear()


def test_job_scoped_call_loop_can_include_manual_unknown_travel_leads(tmp_path, monkeypatch) -> None:
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
        name="Manual Door Lead",
        phone="+17165550105",
        category="door_installer",
        source_url="https://example.com/manual",
        notes="David added this one.",
        priority=90,
    )

    strict = next_pending_leads(10, max_drive_minutes=90, max_distance_miles=75, job_id=job_id)
    manual_ok = next_pending_leads(
        10,
        max_drive_minutes=90,
        max_distance_miles=75,
        job_id=job_id,
        include_unknown_travel=True,
    )

    assert [lead["name"] for lead in strict] == []
    assert [lead["name"] for lead in manual_ok] == ["Manual Door Lead"]
    get_settings.cache_clear()


def test_sms_for_job_matches_texts_to_lead_phone(tmp_path, monkeypatch) -> None:
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
        phone="+17165550106",
        category="door_installer",
        source_url="https://example.com/door",
        notes="good fit",
        priority=80,
    )
    create_sms_message(
        direction="inbound",
        from_number="+17165550106",
        to_number="+17165550100",
        body="Send photos.",
        status="received",
    )
    create_sms_message(
        direction="inbound",
        from_number="+17165550999",
        to_number="+17165550100",
        body="Wrong thread.",
        status="received",
    )

    texts = sms_for_job(job_id)

    assert len(texts) == 1
    assert texts[0]["lead_name"] == "Door Person"
    assert texts[0]["body"] == "Send photos."
    get_settings.cache_clear()
