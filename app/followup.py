from __future__ import annotations

import sqlite3

from .db import create_outreach_action, outreach_for_job


def _has_call_followup(job_id: int, call_id: int, channel: str) -> bool:
    marker = f"call_id={call_id}"
    return any(
        action["channel"] == channel and marker in (action["notes"] or "")
        for action in outreach_for_job(job_id, limit=100)
    )


def _body_for_text(lead: sqlite3.Row, summary: str) -> str:
    job_title = lead["job_title"] if "job_title" in lead.keys() and lead["job_title"] else "the contractor job"
    return (
        f"Hi, this is Sam, the customer's assistant. I just called about {job_title}. "
        f"Could you let us know if this is something you can help with, plus rough availability/pricing? {summary}"
    ).strip()


def _body_for_email(lead: sqlite3.Row, summary: str) -> str:
    job_title = lead["job_title"] if "job_title" in lead.keys() and lead["job_title"] else "Contractor job"
    job_description = (
        lead["job_description"]
        if "job_description" in lead.keys() and lead["job_description"]
        else "The customer is looking for help with a contractor job."
    )
    job_location = lead["job_location"] if "job_location" in lead.keys() and lead["job_location"] else "Gasport, NY"
    return f"""Subject: {job_title} near {job_location}

Hi,

This is Sam, the customer's assistant. I called about this job and wanted to send the details in writing.

Job: {job_title}
Location: {job_location}
Scope: {job_description}

Could you let us know whether this is something you can help with, your rough availability, and how you usually quote this kind of work?

Call note: {summary}

Thanks,
Sam
""".strip()


def create_call_followups(
    *,
    call_id: int,
    lead: sqlite3.Row,
    call_status: str = "",
    outcome: str = "",
    summary: str = "",
    transcript: str = "",
) -> list[int]:
    """Create next actions from a call result.

    This decides the channel and content. A separate executor owns delivery so
    call handling stays deterministic.
    """
    job_id = int(lead["job_id"]) if "job_id" in lead.keys() and lead["job_id"] is not None else None
    lead_id = int(lead["id"]) if "id" in lead.keys() else None
    if job_id is None or lead_id is None:
        return []

    lowered = f"{call_status} {outcome} {summary} {transcript}".lower()
    has_email = bool("email" in lead.keys() and lead["email"])
    has_phone = bool("phone" in lead.keys() and lead["phone"])
    created: list[int] = []
    base_note = f"Auto-created from call_id={call_id}; outcome={outcome or call_status}."

    wants_email = any(word in lowered for word in ["email", "e-mail", "send details", "send photos", "send instructions"])
    wants_text = any(word in lowered for word in ["text", "sms", "message me"])
    missed = call_status in {"no-answer", "busy", "failed", "canceled"} or outcome in {"voicemail", "ivr", "no_transcript"}

    if has_email and (wants_email or (missed and not has_phone)):
        if not _has_call_followup(job_id, call_id, "email"):
            created.append(
                create_outreach_action(
                    job_id=job_id,
                    lead_id=lead_id,
                    channel="email",
                    status="draft",
                    body=_body_for_email(lead, summary or "No call summary captured."),
                    notes=base_note,
                )
            )

    if has_phone and (wants_text or missed):
        if not _has_call_followup(job_id, call_id, "text"):
            created.append(
                create_outreach_action(
                    job_id=job_id,
                    lead_id=lead_id,
                    channel="text",
                    status="draft",
                    body=_body_for_text(lead, summary or "No call summary captured."),
                    notes=base_note,
                )
            )

    if has_email and "photos" in lowered and not _has_call_followup(job_id, call_id, "email"):
        created.append(
            create_outreach_action(
                job_id=job_id,
                lead_id=lead_id,
                channel="email",
                status="draft",
                body=_body_for_email(lead, summary or "Contractor asked for photos or written details."),
                notes=base_note,
            )
        )

    return created
