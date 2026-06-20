from __future__ import annotations

from .caller import place_calls
from .config import get_settings
from .db import next_pending_leads, promote_review_leads_for_job, update_job_status
from .discovery import discover_leads_for_job
from .outreach import execute_outreach_actions
from .billing import call_credits_remaining


def run_job_agent(job_id: int, user_id: int | None = None) -> dict[str, object]:
    """Run the job agent: source leads, choose candidates, then call."""
    settings = get_settings()
    update_job_status(job_id, "active")

    before_pending = next_pending_leads(
        settings.max_calls_per_run,
        max_drive_minutes=settings.max_drive_minutes,
        max_distance_miles=settings.max_distance_miles,
        job_id=job_id,
        include_unknown_travel=True,
    )

    discovery = {"created": 0, "searched": 0, "errors": [], "queries": []}
    if len(before_pending) < settings.max_calls_per_run:
        discovery = discover_leads_for_job(job_id)

    call_limit = settings.max_calls_per_run
    if user_id is not None and settings.contractor_billing_required:
        call_limit = min(call_limit, call_credits_remaining(user_id))
    promoted = promote_review_leads_for_job(job_id, call_limit)
    placed = place_calls(job_id=job_id, include_unknown_travel=True, user_id=user_id)
    outreach = execute_outreach_actions(job_id)

    return {
        "searched": discovery["searched"],
        "discovered": discovery["created"],
        "promoted": promoted,
        "calls": len(placed),
        "outreach": outreach,
        "caller_disabled": settings.caller_disabled,
    }
