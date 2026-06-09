from __future__ import annotations

import re
import sqlite3

from .db import active_jobs, lead_for_email, lead_for_phone, upsert_lead


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return value.strip()


def resolve_lead_for_phone(phone: str, *, fallback_name: str = "Inbound caller") -> sqlite3.Row | None:
    normalized = normalize_phone(phone)
    lead = lead_for_phone(normalized)
    if lead is not None:
        return lead

    jobs = active_jobs(limit=2)
    if len(jobs) != 1 or not normalized:
        return None
    job = jobs[0]

    upsert_lead(
        job_id=int(job["id"]),
        name=fallback_name,
        phone=normalized,
        email="",
        category=str(job["job_type"] or "contractor"),
        source_url="inbound",
        notes="Created automatically from inbound contractor contact.",
        priority=70,
        status="inbound",
    )
    return lead_for_phone(normalized)


def resolve_lead_for_email(email: str, *, fallback_name: str = "Inbound email") -> sqlite3.Row | None:
    address = (email or "").strip().lower()
    if not address:
        return None

    lead = lead_for_email(address)
    if lead is not None:
        return lead

    jobs = active_jobs(limit=2)
    if len(jobs) != 1:
        return None
    job = jobs[0]

    upsert_lead(
        job_id=int(job["id"]),
        name=fallback_name,
        phone=f"email:{address}",
        email=address,
        category=str(job["job_type"] or "contractor"),
        source_url="inbound",
        notes="Created automatically from inbound contractor email.",
        priority=70,
        status="inbound",
    )
    return lead_for_email(address)
