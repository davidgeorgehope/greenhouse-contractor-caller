from __future__ import annotations

import time

from twilio.rest import Client

from .config import get_settings
from .contact import normalize_phone
from .db import create_call, leads_for_job, mark_lead_status, next_pending_leads, update_call, upsert_lead
from .followup import create_call_followups

TERMINAL_CALL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


def _create_twilio_call(client: Client, *, to_number: str, call_id: int) -> object:
    settings = get_settings()
    twiml_url = f"{settings.app_host}/greenhouse/twiml/{call_id}"
    status_url = f"{settings.app_host}/greenhouse/status/{call_id}"
    return client.calls.create(
        to=to_number,
        from_=settings.twilio_from,
        url=twiml_url,
        method="POST",
        status_callback=status_url,
        status_callback_event=["initiated", "ringing", "answered", "completed"],
        status_callback_method="POST",
        record=False,
    )


def _wait_for_call(client: Client, call_sid: str, max_wait_seconds: int) -> str:
    deadline = time.monotonic() + max_wait_seconds
    status = "queued"
    while time.monotonic() < deadline:
        call = client.calls(call_sid).fetch()
        status = str(call.status)
        if status in TERMINAL_CALL_STATUSES:
            return status
        time.sleep(5)
    return status


def place_calls(*, job_id: int | None = None, include_unknown_travel: bool = False) -> list[str]:
    settings = get_settings()
    if settings.caller_disabled:
        print("caller disabled; set CALLER_DISABLED=0 to place calls")
        return []
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise RuntimeError("Missing Twilio credentials")

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    placed: list[str] = []
    for lead in next_pending_leads(
        settings.max_calls_per_run,
        max_drive_minutes=settings.max_drive_minutes,
        max_distance_miles=settings.max_distance_miles,
        job_id=job_id,
        include_unknown_travel=include_unknown_travel,
    ):
        call_id = create_call(int(lead["id"]))
        call = _create_twilio_call(client, to_number=str(lead["phone"]), call_id=call_id)
        update_call(call_id, twilio_sid=call.sid, status="placed")
        mark_lead_status(int(lead["id"]), "calling")
        line = f"placed: call_id={call_id}, lead={lead['name']}, twilio_sid={call.sid}, status={call.status}"
        print(line)
        placed.append(line)
        final_status = _wait_for_call(client, call.sid, settings.max_call_wait_seconds)
        if final_status not in TERMINAL_CALL_STATUSES:
            client.calls(call.sid).update(status="completed")
            final_status = "completed"
        update_call(call_id, status=final_status)
        if final_status == "completed":
            mark_lead_status(int(lead["id"]), "called")
        elif final_status in TERMINAL_CALL_STATUSES:
            mark_lead_status(int(lead["id"]), "failed")
            create_call_followups(
                call_id=call_id,
                lead=lead,
                call_status=final_status,
                summary="The call did not connect. Follow up in writing if the lead still looks useful.",
            )
        print(f"finished: call_id={call_id}, lead={lead['name']}, status={final_status}")
        if settings.call_spacing_seconds:
            time.sleep(settings.call_spacing_seconds)
    if not placed:
        print("no pending leads")
    return placed


def place_test_call(*, job_id: int, to_number: str) -> str:
    settings = get_settings()
    if settings.caller_disabled:
        raise RuntimeError("Caller is disabled; set CALLER_DISABLED=0 to place test calls")
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise RuntimeError("Missing Twilio credentials")

    phone = normalize_phone(to_number)
    upsert_lead(
        job_id=job_id,
        name="David test call",
        phone=phone,
        email="",
        category="test_call",
        source_url="dashboard",
        notes="Dashboard test call target. Safe to reuse; not a contractor candidate.",
        priority=1,
        status="test",
    )
    lead = next((row for row in leads_for_job(job_id) if row["phone"] == phone), None)
    if lead is None:
        raise RuntimeError("Could not create test-call lead")

    call_id = create_call(int(lead["id"]), direction="test")
    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    call = _create_twilio_call(client, to_number=phone, call_id=call_id)
    update_call(call_id, twilio_sid=call.sid, status="placed")
    return f"placed: call_id={call_id}, target={phone}, twilio_sid={call.sid}, status={call.status}"


def main() -> None:
    place_calls()


if __name__ == "__main__":
    main()
