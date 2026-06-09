from __future__ import annotations

import asyncio
import base64
import json

import websockets
from fastapi import WebSocket

from .config import get_settings
from .db import append_event, create_outreach_action, job_for_id, lead_for_call, update_call
from .followup import create_call_followups
from .prompts import contractor_prompt


def _summarize_transcript(transcript: str, *, job_title: str = "contractor job") -> tuple[str, str]:
    lowered = transcript.lower()
    if not transcript:
        return "no_transcript", "Call connected but no Realtime transcript was captured."
    if (
        "voicemail" in lowered
        or "leave a message" in lowered
        or "leave your message" in lowered
        or "sorry to miss you" in lowered
        or "at the tone" in lowered
    ):
        return "voicemail", f"Reached voicemail or a voicemail-like flow; left the {job_title} request and callback details."
    if "press" in lowered and ("menu" in lowered or "option" in lowered or "connected" in lowered):
        return "ivr", "Reached a phone menu/IVR; transcript captured, but keypad navigation is not available in the current bridge."
    if "not able" in lowered or "don't" in lowered or "cannot" in lowered:
        return "likely_no", "Conversation captured; review transcript for a likely no or limitation."
    return "conversation", "Conversation captured; review transcript for details."


REALTIME_TOOLS = [
    {
        "type": "function",
        "name": "lookup_job",
        "description": "Look up the current contractor job details and call goals.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "lookup_contractor",
        "description": "Look up the contractor or business matched to this call.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "record_quote",
        "description": "Record quote, availability, requirements, or other important contractor details from the conversation.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "price": {"type": "string"},
                "availability": {"type": "string"},
                "needs_followup": {"type": "boolean"},
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "queue_followup",
        "description": "Queue a text or email follow-up for this contractor.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["text", "email"]},
                "body": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["channel", "body"],
            "additionalProperties": False,
        },
    },
]


def _row_value(row, key: str, default: object = "") -> object:
    return row[key] if key in row.keys() and row[key] is not None else default


def _tool_result(name: str, arguments: dict[str, object], lead, call_id: int) -> dict[str, object]:
    job_id = int(_row_value(lead, "job_id", 0) or 0)
    if name == "lookup_job":
        job = job_for_id(job_id) if job_id else None
        return {
            "job": dict(job) if job is not None else None,
            "call_goals": [
                "follow the job brief exactly",
                "confirm fit for the specific job",
                "ask only questions present in the job brief or needed to clarify an answer",
                "ask for a useful local referral if they cannot help",
            ],
        }
    if name == "lookup_contractor":
        return {
            "lead": {
                "name": _row_value(lead, "name"),
                "phone": _row_value(lead, "phone"),
                "email": _row_value(lead, "email"),
                "category": _row_value(lead, "category"),
                "notes": _row_value(lead, "notes"),
                "service_area": _row_value(lead, "service_area"),
                "distance_miles": _row_value(lead, "distance_miles", None),
                "drive_minutes": _row_value(lead, "drive_minutes", None),
            }
        }
    if name == "record_quote":
        append_event(
            call_id,
            "realtime_tool_record_quote",
            {
                "summary": str(arguments.get("summary", "")),
                "price": str(arguments.get("price", "")),
                "availability": str(arguments.get("availability", "")),
                "needs_followup": bool(arguments.get("needs_followup", False)),
            },
        )
        return {"recorded": True}
    if name == "queue_followup":
        if not job_id:
            return {"queued": False, "error": "No job matched to this call."}
        action_id = create_outreach_action(
            job_id=job_id,
            lead_id=int(_row_value(lead, "id", 0) or 0) or None,
            channel=str(arguments.get("channel", "text")),
            body=str(arguments.get("body", "")),
            notes=f"Queued by Sam during call_id={call_id}: {arguments.get('reason', '')}",
            status="queued",
        )
        return {"queued": True, "action_id": action_id}
    return {"error": f"Unknown tool: {name}"}


async def _send_session_update(openai_ws, lead, *, direction: str) -> None:
    settings = get_settings()
    await openai_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": contractor_prompt(lead),
                    "tools": REALTIME_TOOLS,
                    "tool_choice": "auto",
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},
                            "turn_detection": {"type": "server_vad"},
                            "transcription": {"model": "gpt-4o-mini-transcribe"},
                        },
                        "output": {
                            "format": {"type": "audio/pcmu"},
                            "voice": settings.openai_realtime_voice,
                        },
                    },
                },
            }
        )
    )
    if direction == "inbound":
        opening = (
            "You are answering an inbound callback from this contractor. Say: "
            "'Hi, this is Sam, the customer's assistant. Thanks for calling back. "
            "I have the job details in front of me. Are you calling about the contractor job in Gasport?'"
        )
    else:
        job_title = str(_row_value(lead, "job_title", "a contractor job"))
        job_location = str(_row_value(lead, "job_location", "Gasport"))
        opening = (
            "You are connected to the business now. Say: "
            f"'Hi, this is Sam calling for the customer. They are looking for help with {job_title} "
            f"near {job_location}. Is that something you can help with?'"
        )
    await openai_ws.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {
                    "instructions": opening,
                },
            }
        )
    )


async def bridge_call(call_id: int, twilio_ws: WebSocket) -> None:
    settings = get_settings()
    lead = lead_for_call(call_id)
    if lead is None:
        await twilio_ws.close()
        return
    if not settings.openai_api_key:
        append_event(call_id, "error", {"message": "missing OpenAI API key"})
        await twilio_ws.close()
        return

    uri = f"wss://api.openai.com/v1/realtime?model={settings.openai_realtime_model}"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    stream_sid: str | None = None
    transcript_parts: list[str] = []

    direction = str(_row_value(lead, "direction", "outbound"))

    async with websockets.connect(uri, additional_headers=headers) as openai_ws:
        await _send_session_update(openai_ws, lead, direction=direction)

        async def twilio_to_openai() -> None:
            nonlocal stream_sid
            while True:
                message = await twilio_ws.receive_text()
                data = json.loads(message)
                event = data.get("event")
                if event == "start":
                    stream_sid = data.get("start", {}).get("streamSid")
                    append_event(call_id, "twilio_start", data.get("start", {}))
                elif event == "media":
                    payload = data.get("media", {}).get("payload")
                    if payload:
                        await openai_ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": payload}))
                elif event == "stop":
                    append_event(call_id, "twilio_stop", data.get("stop", {}))
                    await openai_ws.close()
                    break

        async def openai_to_twilio() -> None:
            async for raw in openai_ws:
                data = json.loads(raw)
                event_type = data.get("type", "")
                if event_type in {"response.output_audio_transcript.done", "response.audio_transcript.done"}:
                    text = str(data.get("transcript") or "")
                    if text:
                        transcript_parts.append(f"assistant: {text}\n")
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    text = str(data.get("transcript") or "")
                    if text:
                        transcript_parts.append(f"contractor: {text}\n")
                elif event_type in {"response.output_audio.delta", "response.audio.delta"} and stream_sid:
                    audio = data.get("delta")
                    if audio:
                        # Validate it is base64 before handing it to Twilio.
                        base64.b64decode(audio)
                        await twilio_ws.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": audio},
                                }
                            )
                        )
                elif event_type == "error":
                    append_event(call_id, "openai_error", data)
                elif event_type == "response.function_call_arguments.done":
                    name = str(data.get("name", ""))
                    tool_call_id = str(data.get("call_id", ""))
                    try:
                        arguments = json.loads(str(data.get("arguments") or "{}"))
                    except json.JSONDecodeError:
                        arguments = {}
                    result = _tool_result(name, arguments, lead, call_id)
                    append_event(call_id, "realtime_tool_call", {"name": name, "arguments": arguments, "result": result})
                    if tool_call_id:
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": tool_call_id,
                                        "output": json.dumps(result, sort_keys=True),
                                    },
                                }
                            )
                        )
                        await openai_ws.send(json.dumps({"type": "response.create"}))

        try:
            await asyncio.gather(twilio_to_openai(), openai_to_twilio())
        finally:
            transcript = "".join(transcript_parts).strip()
            outcome, summary = _summarize_transcript(transcript, job_title=str(_row_value(lead, "job_title", "contractor job")))
            update_call(call_id, transcript=transcript, outcome=outcome, summary=summary)
            create_call_followups(
                call_id=call_id,
                lead=lead,
                call_status="completed",
                outcome=outcome,
                summary=summary,
                transcript=transcript,
            )
