from __future__ import annotations

from datetime import datetime, timezone

from .db import pending_outreach_actions, update_outreach_action
from .emailer import send_email
from .sms import send_sms


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def execute_outreach_actions(job_id: int, limit: int = 50) -> dict[str, int]:
    sent = 0
    blocked = 0
    failed = 0

    for action in pending_outreach_actions(job_id, limit=limit):
        action_id = int(action["id"])
        channel = str(action["channel"]).lower()
        body = action["body"] or ""
        try:
            if channel == "text":
                target = action["lead_phone"]
                if not target:
                    raise RuntimeError("Missing lead phone")
                receipt = send_sms(str(target), body)
            elif channel == "email":
                target = action["lead_email"]
                if not target:
                    raise RuntimeError("Missing lead email")
                receipt = send_email(str(target), body)
            else:
                blocked += 1
                update_outreach_action(action_id, status="blocked", notes=f"Unsupported channel: {channel}")
                continue
        except RuntimeError as exc:
            blocked += 1
            update_outreach_action(action_id, status="blocked", notes=str(exc))
            continue
        except Exception as exc:
            failed += 1
            update_outreach_action(action_id, status="failed", notes=str(exc))
            continue

        sent += 1
        update_outreach_action(action_id, status="sent", notes=f"Sent via {channel}: {receipt}", completed_at=_now())

    return {"sent": sent, "blocked": blocked, "failed": failed}
