from __future__ import annotations

import json
from datetime import UTC, datetime

import websockets

from .billing import reserve_call_credit
from .config import get_settings
from .db import (
    add_call_credits,
    append_event,
    connect,
    create_call,
    grant_period_call_credits,
    job_for_id,
    leads_for_job,
    mark_lead_status,
    update_call,
    upsert_lead,
    upsert_user_billing,
)


TEST_CUSTOMER_PREFIX = "cus_test_local_"
TEST_SUBSCRIPTION_PREFIX = "sub_test_local_"
REALTIME_TEST_CONTRACTOR_NAME = "Realtime test contractor"


def activate_test_subscription(user_id: int) -> bool:
    settings = get_settings()
    with connect() as conn:
        billing = conn.execute("SELECT * FROM user_billing WHERE user_id = ?", (user_id,)).fetchone()
        existing_customer = str(billing["stripe_customer_id"] or "") if billing else ""
        if existing_customer and not existing_customer.startswith(TEST_CUSTOMER_PREFIX):
            return False
    upsert_user_billing(
        user_id=user_id,
        stripe_customer_id=f"{TEST_CUSTOMER_PREFIX}{user_id}",
        stripe_subscription_id=f"{TEST_SUBSCRIPTION_PREFIX}{user_id}",
        status="active",
        current_period_end="test-current-period",
    )
    grant_period_call_credits(
        user_id,
        period_end="test-current-period",
        credits=settings.contractor_plan_call_credits,
        active_jobs_limit=settings.contractor_plan_active_jobs,
        leads_per_job_limit=settings.contractor_plan_leads_per_job,
    )
    return True


def add_test_call_credits(user_id: int, credits: int | None = None) -> int:
    amount = credits or get_settings().contractor_credit_pack_size
    add_call_credits(user_id, amount)
    return amount


def reset_local_test_billing(user_id: int) -> bool:
    with connect() as conn:
        billing = conn.execute("SELECT * FROM user_billing WHERE user_id = ?", (user_id,)).fetchone()
        if not billing or not str(billing["stripe_customer_id"] or "").startswith(TEST_CUSTOMER_PREFIX):
            return False
        conn.execute(
            """
            UPDATE user_billing
            SET status='inactive',
                call_credits_remaining=0,
                stripe_customer_id=NULL,
                stripe_subscription_id=NULL,
                current_period_end=NULL,
                last_credit_grant_period_end=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?
            """,
            (user_id,),
        )
        return True


def simulate_test_contractor_call(*, job_id: int, user_id: int, scenario: str = "available") -> int:
    job = job_for_id(job_id, user_id)
    if job is None:
        raise ValueError("Job not found for user")
    if not reserve_call_credit(user_id):
        raise RuntimeError("No call credits remaining")

    phone = "+17165550199"
    upsert_lead(
        job_id=job_id,
        name="Test contractor agent",
        phone=phone,
        email="test-contractor@example.com",
        category="test_call",
        source_url="local-test-harness",
        notes="Deterministic fake contractor used by the owner-only test harness.",
        priority=99,
        status="pending",
    )
    lead = next((row for row in leads_for_job(job_id) if str(row["phone"]) == phone), None)
    if lead is None:
        raise RuntimeError("Could not create test contractor lead")

    call_id = create_call(int(lead["id"]), direction="test_agent")
    now = datetime.now(UTC).isoformat()
    transcript, summary, outcome = _scenario_result(str(job["title"]), scenario)
    update_call(
        call_id,
        twilio_sid=f"TEST_AGENT_{call_id}",
        status="completed",
        outcome=outcome,
        summary=summary,
        transcript=transcript,
        started_at=now,
        ended_at=now,
    )
    mark_lead_status(int(lead["id"]), "called")
    append_event(
        call_id,
        "test_agent_simulation",
        {
            "scenario": scenario,
            "job_id": job_id,
            "user_id": user_id,
            "consumed_call_credit": True,
        },
    )
    return call_id


async def simulate_realtime_test_contractor_call(*, job_id: int, user_id: int, scenario: str = "available") -> int:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("Missing OpenAI API key for Realtime test contractor")

    job = job_for_id(job_id, user_id)
    if job is None:
        raise ValueError("Job not found for user")
    if not reserve_call_credit(user_id):
        raise RuntimeError("No call credits remaining")

    phone = "+17165550198"
    upsert_lead(
        job_id=job_id,
        name=REALTIME_TEST_CONTRACTOR_NAME,
        phone=phone,
        email="realtime-test-contractor@example.com",
        category="test_call",
        source_url="realtime-test-harness",
        notes="GPT Realtime fake contractor used by the owner-only end-to-end test harness.",
        priority=98,
        status="pending",
    )
    lead = next((row for row in leads_for_job(job_id) if str(row["phone"]) == phone), None)
    if lead is None:
        raise RuntimeError("Could not create Realtime test contractor lead")

    call_id = create_call(int(lead["id"]), direction="test_realtime_agent")
    now = datetime.now(UTC).isoformat()
    update_call(call_id, twilio_sid=f"TEST_REALTIME_{call_id}", status="in_progress", started_at=now)
    append_event(
        call_id,
        "realtime_test_agent_started",
        {
            "scenario": scenario,
            "job_id": job_id,
            "user_id": user_id,
            "model": settings.openai_realtime_model,
            "consumed_call_credit": True,
        },
    )

    raw_response = await _run_realtime_contractor_scenario(
        job_title=str(job["title"]),
        job_description=str(job["description"]),
        job_location=str(job["location"]),
        scenario=scenario,
    )
    transcript, summary, outcome = _parse_realtime_result(raw_response, str(job["title"]), scenario)
    ended = datetime.now(UTC).isoformat()
    update_call(
        call_id,
        status="completed",
        outcome=outcome,
        summary=summary,
        transcript=transcript,
        ended_at=ended,
    )
    mark_lead_status(int(lead["id"]), "called")
    append_event(call_id, "realtime_test_agent_completed", {"raw_response": raw_response})
    return call_id


async def _run_realtime_contractor_scenario(
    *, job_title: str, job_description: str, job_location: str, scenario: str
) -> str:
    settings = get_settings()
    uri = f"wss://api.openai.com/v1/realtime?model={settings.openai_realtime_model}"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    text_parts: list[str] = []
    instructions = (
        "You are a fake contractor used by Contractor Relief's automated test harness. "
        "Stay in character as a real local contractor. Return only compact JSON with keys "
        "transcript, summary, and outcome. The transcript should show both Sam and Contractor lines. "
        "Outcome must be one of conversation, likely_no, voicemail, or ivr."
    )
    scenario_prompt = (
        f"Scenario: {scenario}\n"
        f"Job title: {job_title}\n"
        f"Job location: {job_location}\n"
        f"Job description: {job_description}\n"
        "Sam opens with: Hi, this is Sam calling for the customer. "
        f"They are looking for help with {job_title} near {job_location}. "
        "Is that something you can help with?\n"
        "Generate the contractor side and the resulting short transcript."
    )

    async with websockets.connect(uri, additional_headers=headers) as openai_ws:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "instructions": instructions,
                        "output_modalities": ["text"],
                    },
                }
            )
        )
        await openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": scenario_prompt}],
                    },
                }
            )
        )
        await openai_ws.send(json.dumps({"type": "response.create", "response": {"output_modalities": ["text"]}}))
        async for raw in openai_ws:
            data = json.loads(raw)
            event_type = str(data.get("type", ""))
            if event_type in {"response.output_text.delta", "response.text.delta"}:
                text_parts.append(str(data.get("delta") or ""))
            elif event_type in {"response.output_text.done", "response.text.done"}:
                if not text_parts:
                    text_parts.append(str(data.get("text") or ""))
            elif event_type == "response.done":
                if not text_parts:
                    output = data.get("response", {}).get("output", [])
                    for item in output if isinstance(output, list) else []:
                        for content in item.get("content", []) if isinstance(item, dict) else []:
                            if isinstance(content, dict) and content.get("text"):
                                text_parts.append(str(content["text"]))
                break
            elif event_type == "error":
                raise RuntimeError(f"Realtime test contractor failed: {data}")
    return "".join(text_parts).strip()


def _parse_realtime_result(raw_response: str, job_title: str, scenario: str) -> tuple[str, str, str]:
    raw_response = _extract_json_object(raw_response)
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        parsed = {}
    transcript = str(parsed.get("transcript") or raw_response).strip()
    summary = str(parsed.get("summary") or "").strip()
    outcome = str(parsed.get("outcome") or "").strip()
    if transcript and summary and outcome:
        return transcript, summary, outcome
    fallback_transcript, fallback_summary, fallback_outcome = _scenario_result(job_title, scenario)
    if transcript:
        fallback_transcript = transcript
    if summary:
        fallback_summary = summary
    if outcome:
        fallback_outcome = outcome
    return fallback_transcript, fallback_summary, fallback_outcome


def _extract_json_object(raw_response: str) -> str:
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    if start == -1:
        return text
    decoder = json.JSONDecoder()
    try:
        _, end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        return text
    return text[start : start + end]


def _scenario_result(job_title: str, scenario: str) -> tuple[str, str, str]:
    normalized = scenario.strip().lower()
    if normalized == "busy":
        transcript = (
            "Sam: Hi, this is Sam calling for a customer about "
            f"{job_title}.\n"
            "Contractor: We are booked out six weeks and cannot take this one. "
            "Try a smaller handyman shop."
        )
        return transcript, "Test contractor declined because they are booked out six weeks.", "likely_no"
    if normalized == "needs_photos":
        transcript = (
            "Sam: Hi, this is Sam calling for a customer about "
            f"{job_title}.\n"
            "Contractor: We may be able to help. Text or email photos and the site address, "
            "then we can give a rough estimate."
        )
        return transcript, "Test contractor may be available but needs photos and the site address.", "conversation"
    transcript = (
        "Sam: Hi, this is Sam calling for a customer about "
        f"{job_title}.\n"
        "Contractor: Yes, we can help. We have availability next week. "
        "A small job like that usually starts around $250, depending on site conditions."
    )
    return transcript, "Test contractor is available next week; rough starting price is $250.", "conversation"
