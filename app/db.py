from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  title TEXT NOT NULL,
  job_type TEXT NOT NULL DEFAULT 'general',
  description TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  brief TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'planning',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS signups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  project_type TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'landing',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signups_created_at ON signups(created_at);

CREATE TABLE IF NOT EXISTS user_billing (
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  status TEXT NOT NULL DEFAULT 'inactive',
  current_period_end TEXT,
  call_credits_remaining INTEGER NOT NULL DEFAULT 0,
  plan_active_jobs_limit INTEGER NOT NULL DEFAULT 5,
  plan_leads_per_job_limit INTEGER NOT NULL DEFAULT 10,
  plan_call_credits_per_period INTEGER NOT NULL DEFAULT 10,
  last_credit_grant_period_end TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_billing_customer ON user_billing(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_user_billing_subscription ON user_billing(stripe_subscription_id);

CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER REFERENCES jobs(id),
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  email TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL,
  source_url TEXT,
  origin_address TEXT NOT NULL DEFAULT '',
  origin_lat REAL,
  origin_lng REAL,
  distance_miles REAL,
  drive_minutes INTEGER,
  service_area TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 50,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_status_priority ON leads(status, priority DESC, id);

CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id),
  direction TEXT NOT NULL DEFAULT 'outbound',
  twilio_sid TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  outcome TEXT,
  summary TEXT,
  transcript TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_calls_lead_id ON calls(lead_id);
CREATE INDEX IF NOT EXISTS idx_calls_twilio_sid ON calls(twilio_sid);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_id INTEGER,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sms_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  direction TEXT NOT NULL,
  from_number TEXT NOT NULL,
  to_number TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  twilio_sid TEXT,
  status TEXT,
  raw_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sms_messages_created_at ON sms_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_sms_messages_twilio_sid ON sms_messages(twilio_sid);

CREATE TABLE IF NOT EXISTS email_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  direction TEXT NOT NULL,
  from_email TEXT NOT NULL,
  to_email TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  message_id TEXT,
  status TEXT,
  raw_payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_email_messages_created_at ON email_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_email_messages_from_email ON email_messages(from_email);
CREATE INDEX IF NOT EXISTS idx_email_messages_message_id ON email_messages(message_id);

CREATE TABLE IF NOT EXISTS outreach_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER REFERENCES jobs(id),
  lead_id INTEGER REFERENCES leads(id),
  channel TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT 'outbound',
  status TEXT NOT NULL DEFAULT 'draft',
  body TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  due_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outreach_job_status ON outreach_actions(job_id, status, due_at, id);
"""

LEAD_COLUMNS: dict[str, str] = {
    "job_id": "INTEGER REFERENCES jobs(id)",
    "email": "TEXT NOT NULL DEFAULT ''",
    "origin_address": "TEXT NOT NULL DEFAULT ''",
    "origin_lat": "REAL",
    "origin_lng": "REAL",
    "distance_miles": "REAL",
    "drive_minutes": "INTEGER",
    "service_area": "TEXT NOT NULL DEFAULT ''",
}

CALL_COLUMNS: dict[str, str] = {
    "direction": "TEXT NOT NULL DEFAULT 'outbound'",
}

JOB_COLUMNS: dict[str, str] = {
    "user_id": "INTEGER REFERENCES users(id)",
}

USER_BILLING_COLUMNS: dict[str, str] = {
    "call_credits_remaining": "INTEGER NOT NULL DEFAULT 0",
    "plan_active_jobs_limit": "INTEGER NOT NULL DEFAULT 5",
    "plan_leads_per_job_limit": "INTEGER NOT NULL DEFAULT 10",
    "plan_call_credits_per_period": "INTEGER NOT NULL DEFAULT 10",
    "last_credit_grant_period_end": "TEXT",
}


def connect() -> sqlite3.Connection:
    settings = get_settings()
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_job_columns(conn)
    _ensure_lead_columns(conn)
    _ensure_call_columns(conn)
    _ensure_user_billing_columns(conn)
    _ensure_default_job(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_travel ON leads(status, drive_minutes, distance_miles)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_leads_job_status_priority ON leads(job_id, status, priority DESC, id)"
    )
    return conn


def _ensure_job_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for name, definition in JOB_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")


def _ensure_lead_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
    for name, definition in LEAD_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {name} {definition}")


def _ensure_call_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(calls)")}
    for name, definition in CALL_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE calls ADD COLUMN {name} {definition}")


def _ensure_user_billing_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(user_billing)")}
    for name, definition in USER_BILLING_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE user_billing ADD COLUMN {name} {definition}")


def _ensure_default_job(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM jobs ORDER BY id LIMIT 1").fetchone()
    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO jobs(title, job_type, description, location, brief, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Greenhouse assembly",
                "greenhouse_assembly",
                "Assemble a customer-owned 10x10 Janssens/Exaco Modern aluminum/glass greenhouse.",
                get_settings().project_address,
                default_job_brief(
                    "Greenhouse assembly",
                    "Assemble a customer-owned 10x10 Janssens/Exaco Modern aluminum/glass greenhouse.",
                    get_settings().project_address,
                ),
                "active",
            ),
        )
        default_job_id = int(cur.lastrowid)
    else:
        default_job_id = int(existing["id"])
    conn.execute("UPDATE leads SET job_id = COALESCE(job_id, ?)", (default_job_id,))


def default_job_brief(title: str, description: str, location: str) -> str:
    lines = [
        f"Job: {title}",
        f"Location: {location or 'Confirm location before outreach.'}",
        "",
        "Scope:",
        description or "Clarify the work, access constraints, materials, timing, and photos needed.",
        "",
        "Questions to ask contractors:",
        "- Can you do this specific job and serve the location?",
        "- How do you quote it: fixed price, hourly, site visit, or photos first?",
        "- What is the rough price range and earliest availability?",
        "- What photos, measurements, model numbers, or instructions do you need?",
        "- What is the best callback/text/email for follow-up?",
        "",
        "Red flags:",
        "- Vague service area, pressure for payment before a quote, or refusal to provide basic availability/pricing shape.",
    ]
    return "\n".join(lines)


def create_job(*, title: str, job_type: str, description: str, location: str, user_id: int | None = None) -> int:
    brief = default_job_brief(title, description, location)
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO jobs(user_id, title, job_type, description, location, brief, status)
            VALUES (?, ?, ?, ?, ?, ?, 'planning')
            """,
            (user_id, title, job_type, description, location, brief),
        )
        return int(cur.lastrowid)


def create_signup(
    *,
    email: str,
    display_name: str = "",
    project_type: str = "",
    location: str = "",
    notes: str = "",
    source: str = "landing",
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO signups(email, display_name, project_type, location, notes, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
              display_name=COALESCE(NULLIF(excluded.display_name, ''), signups.display_name),
              project_type=COALESCE(NULLIF(excluded.project_type, ''), signups.project_type),
              location=COALESCE(NULLIF(excluded.location, ''), signups.location),
              notes=COALESCE(NULLIF(excluded.notes, ''), signups.notes),
              source=excluded.source,
              updated_at=CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                email.strip().lower(),
                display_name.strip(),
                project_type.strip(),
                location.strip(),
                notes.strip(),
                source.strip() or "landing",
            ),
        )
        return int(cur.fetchone()["id"])


def get_user_billing(user_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM user_billing WHERE user_id = ?", (user_id,)).fetchone()


def ensure_user_entitlements(
    user_id: int,
    *,
    active_jobs_limit: int,
    leads_per_job_limit: int,
    call_credits_per_period: int,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_billing(
              user_id, status, plan_active_jobs_limit, plan_leads_per_job_limit, plan_call_credits_per_period
            )
            VALUES (?, 'inactive', ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              plan_active_jobs_limit=excluded.plan_active_jobs_limit,
              plan_leads_per_job_limit=excluded.plan_leads_per_job_limit,
              plan_call_credits_per_period=excluded.plan_call_credits_per_period,
              updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, active_jobs_limit, leads_per_job_limit, call_credits_per_period),
        )


def grant_period_call_credits(
    user_id: int,
    *,
    period_end: str | None,
    credits: int,
    active_jobs_limit: int,
    leads_per_job_limit: int,
) -> None:
    grant_marker = period_end or "checkout"
    with connect() as conn:
        existing = conn.execute("SELECT * FROM user_billing WHERE user_id = ?", (user_id,)).fetchone()
        if existing and existing["last_credit_grant_period_end"] == grant_marker:
            return
        conn.execute(
            """
            INSERT INTO user_billing(
              user_id, status, call_credits_remaining, plan_active_jobs_limit,
              plan_leads_per_job_limit, plan_call_credits_per_period, last_credit_grant_period_end
            )
            VALUES (?, 'active', ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              call_credits_remaining=user_billing.call_credits_remaining + excluded.call_credits_remaining,
              plan_active_jobs_limit=excluded.plan_active_jobs_limit,
              plan_leads_per_job_limit=excluded.plan_leads_per_job_limit,
              plan_call_credits_per_period=excluded.plan_call_credits_per_period,
              last_credit_grant_period_end=excluded.last_credit_grant_period_end,
              updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, credits, active_jobs_limit, leads_per_job_limit, credits, grant_marker),
        )


def add_call_credits(user_id: int, credits: int) -> None:
    if credits <= 0:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_billing(user_id, call_credits_remaining)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              call_credits_remaining=user_billing.call_credits_remaining + excluded.call_credits_remaining,
              updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, credits),
        )


def consume_call_credit(user_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE user_billing
            SET call_credits_remaining = call_credits_remaining - 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
              AND status IN ('active', 'trialing')
              AND call_credits_remaining > 0
            """,
            (user_id,),
        )
        return cur.rowcount == 1


def active_job_count(user_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM jobs WHERE user_id = ? AND status IN ('planning', 'active')",
            (user_id,),
        ).fetchone()
        return int(row["count"])


def lead_count_for_job(job_id: int) -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM leads WHERE job_id = ?", (job_id,)).fetchone()
        return int(row["count"])


def billing_is_active(user_id: int) -> bool:
    billing = get_user_billing(user_id)
    return bool(billing and billing["status"] in {"active", "trialing"})


def upsert_user_billing(
    *,
    user_id: int,
    stripe_customer_id: str | None,
    stripe_subscription_id: str | None,
    status: str,
    current_period_end: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_billing(
              user_id, stripe_customer_id, stripe_subscription_id, status, current_period_end
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              stripe_customer_id=COALESCE(excluded.stripe_customer_id, user_billing.stripe_customer_id),
              stripe_subscription_id=COALESCE(excluded.stripe_subscription_id, user_billing.stripe_subscription_id),
              status=excluded.status,
              current_period_end=COALESCE(excluded.current_period_end, user_billing.current_period_end),
              updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, stripe_customer_id, stripe_subscription_id, status, current_period_end),
        )


def upsert_user_billing_by_customer(
    *,
    stripe_customer_id: str,
    stripe_subscription_id: str | None,
    status: str,
    current_period_end: str | None = None,
) -> bool:
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE user_billing
            SET stripe_subscription_id=COALESCE(?, stripe_subscription_id),
                status=?,
                current_period_end=COALESCE(?, current_period_end),
                updated_at=CURRENT_TIMESTAMP
            WHERE stripe_customer_id=?
            """,
            (stripe_subscription_id, status, current_period_end, stripe_customer_id),
        )
        return cur.rowcount > 0


def update_job_status(job_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, job_id),
        )


def update_job_brief(
    job_id: int,
    brief: str,
    *,
    title: str | None = None,
    description: str | None = None,
    location: str | None = None,
) -> bool:
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET title = COALESCE(?, title),
                description = COALESCE(?, description),
                location = COALESCE(?, location),
                brief = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'planning'
            """,
            (
                title.strip() if title is not None else None,
                description.strip() if description is not None else None,
                location.strip() if location is not None else None,
                brief.strip(),
                job_id,
            ),
        )
        return cur.rowcount > 0


def list_jobs(user_id: int | None = None, *, include_shared: bool = False) -> list[sqlite3.Row]:
    if user_id is not None and include_shared:
        user_clause = "WHERE (jobs.user_id = ? OR jobs.user_id IS NULL)"
    elif user_id is not None:
        user_clause = "WHERE jobs.user_id = ?"
    else:
        user_clause = ""
    params: tuple[object, ...] = (user_id,) if user_id is not None else ()
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT jobs.*,
                  COUNT(leads.id) AS lead_count,
                  SUM(CASE WHEN leads.status IN ('pending', 'calling') THEN 1 ELSE 0 END) AS open_lead_count
                FROM jobs
                LEFT JOIN leads ON leads.job_id = jobs.id
                {user_clause}
                GROUP BY jobs.id
                ORDER BY jobs.updated_at DESC, jobs.id DESC
                """,
                params,
            )
        )


def job_for_id(job_id: int, user_id: int | None = None, *, include_shared: bool = False) -> sqlite3.Row | None:
    if user_id is not None and include_shared:
        user_clause = "AND (user_id = ? OR user_id IS NULL)"
    elif user_id is not None:
        user_clause = "AND user_id = ?"
    else:
        user_clause = ""
    params: tuple[object, ...] = (job_id, user_id) if user_id is not None else (job_id,)
    with connect() as conn:
        return conn.execute(f"SELECT * FROM jobs WHERE id = ? {user_clause}", params).fetchone()


def active_job() -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE status IN ('active', 'planning')
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()


def active_jobs(limit: int = 10) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE status IN ('active', 'planning')
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


def leads_for_job(job_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT leads.*,
                  (SELECT COUNT(*) FROM calls WHERE calls.lead_id = leads.id) AS call_count,
                  (SELECT summary FROM calls WHERE calls.lead_id = leads.id ORDER BY id DESC LIMIT 1) AS latest_call_summary
                FROM leads
                WHERE job_id = ?
                ORDER BY priority DESC, id ASC
                """,
                (job_id,),
            )
        )


def calls_for_job(job_id: int, limit: int = 25) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT calls.*, leads.name AS lead_name, leads.phone AS lead_phone
                FROM calls
                JOIN leads ON leads.id = calls.lead_id
                WHERE leads.job_id = ?
                ORDER BY calls.id DESC
                LIMIT ?
                """,
                (job_id, limit),
            )
        )


def call_for_id(call_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT calls.*, leads.name AS lead_name, leads.phone AS lead_phone, leads.job_id,
              jobs.title AS job_title
            FROM calls
            JOIN leads ON leads.id = calls.lead_id
            LEFT JOIN jobs ON jobs.id = leads.job_id
            WHERE calls.id = ?
            """,
            (call_id,),
        ).fetchone()


def delete_test_calls_for_job(job_id: int) -> int:
    with connect() as conn:
        rows = list(
            conn.execute(
                """
                SELECT calls.id
                FROM calls
                JOIN leads ON leads.id = calls.lead_id
                WHERE leads.job_id = ?
                  AND (calls.direction = 'test' OR leads.category = 'test_call')
                """,
                (job_id,),
            )
        )
        call_ids = [int(row["id"]) for row in rows]
        if not call_ids:
            return 0
        placeholders = ",".join("?" for _ in call_ids)
        conn.execute(f"DELETE FROM events WHERE call_id IN ({placeholders})", call_ids)
        conn.execute(f"DELETE FROM calls WHERE id IN ({placeholders})", call_ids)
        conn.execute(
            """
            DELETE FROM leads
            WHERE job_id = ?
              AND category = 'test_call'
              AND NOT EXISTS (SELECT 1 FROM calls WHERE calls.lead_id = leads.id)
            """,
            (job_id,),
        )
        return len(call_ids)


def outreach_for_job(job_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT outreach_actions.*, leads.name AS lead_name, leads.phone AS lead_phone, leads.email AS lead_email
                FROM outreach_actions
                LEFT JOIN leads ON leads.id = outreach_actions.lead_id
                WHERE outreach_actions.job_id = ?
                ORDER BY outreach_actions.completed_at IS NOT NULL, outreach_actions.due_at IS NULL, outreach_actions.due_at, outreach_actions.id DESC
                LIMIT ?
                """,
                (job_id, limit),
            )
        )


def pending_outreach_actions(job_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT outreach_actions.*, leads.name AS lead_name, leads.phone AS lead_phone, leads.email AS lead_email
                FROM outreach_actions
                LEFT JOIN leads ON leads.id = outreach_actions.lead_id
                WHERE outreach_actions.job_id = ?
                  AND outreach_actions.direction = 'outbound'
                  AND outreach_actions.status IN ('draft', 'queued')
                  AND (outreach_actions.due_at IS NULL OR outreach_actions.due_at <= CURRENT_TIMESTAMP)
                ORDER BY outreach_actions.due_at IS NULL, outreach_actions.due_at, outreach_actions.id
                LIMIT ?
                """,
                (job_id, limit),
            )
        )


def upsert_lead(
    *,
    job_id: int | None = None,
    name: str,
    phone: str,
    category: str,
    source_url: str,
    notes: str,
    priority: int,
    email: str = "",
    origin_address: str = "",
    origin_lat: float | None = None,
    origin_lng: float | None = None,
    distance_miles: float | None = None,
    drive_minutes: int | None = None,
    service_area: str = "",
    status: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO leads(
              job_id, name, phone, email, category, source_url, origin_address, origin_lat, origin_lng,
              distance_miles, drive_minutes, service_area, notes, priority, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'pending'))
            ON CONFLICT(phone) DO UPDATE SET
              job_id=COALESCE(excluded.job_id, leads.job_id),
              name=excluded.name,
              email=excluded.email,
              category=excluded.category,
              source_url=excluded.source_url,
              origin_address=excluded.origin_address,
              origin_lat=excluded.origin_lat,
              origin_lng=excluded.origin_lng,
              distance_miles=excluded.distance_miles,
              drive_minutes=excluded.drive_minutes,
              service_area=excluded.service_area,
              notes=excluded.notes,
              priority=excluded.priority,
              status=COALESCE(?, leads.status),
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                job_id,
                name,
                phone,
                email.strip(),
                category,
                source_url,
                origin_address,
                origin_lat,
                origin_lng,
                distance_miles,
                drive_minutes,
                service_area,
                notes,
                priority,
                status,
                status,
            ),
        )


def next_pending_leads(
    limit: int,
    *,
    max_drive_minutes: int,
    max_distance_miles: int,
    job_id: int | None = None,
    include_unknown_travel: bool = False,
) -> list[sqlite3.Row]:
    job_clause = "AND leads.job_id = ?" if job_id is not None else ""
    unknown_clause = "OR (drive_minutes IS NULL AND distance_miles IS NULL)" if include_unknown_travel else ""
    params: list[object] = [max_drive_minutes, max_distance_miles]
    if job_id is not None:
        params.append(job_id)
    params.append(limit)
    with connect() as conn:
        return list(
            conn.execute(
                f"""
                SELECT leads.*, jobs.title AS job_title, jobs.description AS job_description, jobs.location AS job_location, jobs.brief AS job_brief
                FROM leads
                LEFT JOIN jobs ON jobs.id = leads.job_id
                WHERE leads.status = 'pending'
                  AND COALESCE(jobs.status, 'active') IN ('active', 'planning')
                  AND (
                    leads.category = 'manufacturer_referral'
                    OR (
                      drive_minutes IS NOT NULL
                      AND drive_minutes <= ?
                    )
                    OR (
                      drive_minutes IS NULL
                      AND distance_miles IS NOT NULL
                      AND distance_miles <= ?
                    )
                    {unknown_clause}
                  )
                  {job_clause}
                ORDER BY priority DESC, id ASC
                LIMIT ?
                """,
                params,
            )
        )


def lead_for_phone(phone: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT leads.*,
              jobs.title AS job_title, jobs.description AS job_description, jobs.location AS job_location, jobs.brief AS job_brief
            FROM leads
            LEFT JOIN jobs ON jobs.id = leads.job_id
            WHERE leads.phone = ?
            ORDER BY leads.updated_at DESC, leads.id DESC
            LIMIT 1
            """,
            (phone,),
        ).fetchone()


def lead_for_email(email: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT leads.*,
              jobs.title AS job_title, jobs.description AS job_description, jobs.location AS job_location, jobs.brief AS job_brief
            FROM leads
            LEFT JOIN jobs ON jobs.id = leads.job_id
            WHERE lower(leads.email) = lower(?)
            ORDER BY leads.updated_at DESC, leads.id DESC
            LIMIT 1
            """,
            (email,),
        ).fetchone()


def create_call(lead_id: int, *, direction: str = "outbound") -> int:
    with connect() as conn:
        cur = conn.execute("INSERT INTO calls(lead_id, direction) VALUES (?, ?)", (lead_id, direction))
        return int(cur.lastrowid)


def update_call(call_id: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {"direction", "twilio_sid", "status", "outcome", "summary", "transcript", "started_at", "ended_at"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown call fields: {', '.join(sorted(unknown))}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [call_id]
    with connect() as conn:
        conn.execute(f"UPDATE calls SET {assignments} WHERE id = ?", values)


def mark_lead_status(lead_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE leads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, lead_id),
        )


def mark_job_lead_status(job_id: int, lead_id: int, status: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE leads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND job_id = ?",
            (status, lead_id, job_id),
        )
        return cur.rowcount > 0


def promote_review_leads_for_job(job_id: int, limit: int) -> int:
    with connect() as conn:
        rows = list(
            conn.execute(
                """
                SELECT id
                FROM leads
                WHERE job_id = ? AND status = 'review'
                ORDER BY priority DESC, id ASC
                LIMIT ?
                """,
                (job_id, limit),
            )
        )
        if not rows:
            return 0
        lead_ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in lead_ids)
        conn.execute(
            f"UPDATE leads SET status = 'pending', updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            lead_ids,
        )
        return len(lead_ids)


def lead_for_call(call_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            """
            SELECT calls.id AS call_id, calls.direction, calls.twilio_sid, leads.*,
              jobs.title AS job_title, jobs.description AS job_description, jobs.location AS job_location, jobs.brief AS job_brief
            FROM calls
            JOIN leads ON calls.lead_id = leads.id
            LEFT JOIN jobs ON jobs.id = leads.job_id
            WHERE calls.id = ?
            """,
            (call_id,),
        ).fetchone()


def append_event(call_id: int | None, event_type: str, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events(call_id, event_type, payload_json) VALUES (?, ?, ?)",
            (call_id, event_type, json.dumps(payload, sort_keys=True)),
        )


def create_sms_message(
    *,
    direction: str,
    from_number: str,
    to_number: str,
    body: str,
    twilio_sid: str | None = None,
    status: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO sms_messages(direction, from_number, to_number, body, twilio_sid, status, raw_payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                direction,
                from_number,
                to_number,
                body,
                twilio_sid,
                status,
                json.dumps(raw_payload or {}, sort_keys=True),
            ),
        )
        return int(cur.lastrowid)


def sms_for_job(job_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT sms_messages.*,
                  leads.name AS lead_name,
                  leads.phone AS lead_phone
                FROM sms_messages
                LEFT JOIN leads
                  ON leads.job_id = ?
                 AND (
                   leads.phone = sms_messages.from_number
                   OR leads.phone = sms_messages.to_number
                 )
                WHERE leads.id IS NOT NULL
                ORDER BY sms_messages.id DESC
                LIMIT ?
                """,
                (job_id, limit),
            )
        )


def create_email_message(
    *,
    direction: str,
    from_email: str,
    to_email: str,
    subject: str = "",
    body: str = "",
    message_id: str | None = None,
    status: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO email_messages(direction, from_email, to_email, subject, body, message_id, status, raw_payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                direction,
                from_email,
                to_email,
                subject,
                body,
                message_id,
                status,
                json.dumps(raw_payload or {}, sort_keys=True),
            ),
        )
        return int(cur.lastrowid)


def emails_for_job(job_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT email_messages.*,
                  leads.name AS lead_name,
                  leads.email AS lead_email
                FROM email_messages
                LEFT JOIN leads
                  ON leads.job_id = ?
                 AND lower(leads.email) IN (lower(email_messages.from_email), lower(email_messages.to_email))
                WHERE leads.id IS NOT NULL
                ORDER BY email_messages.id DESC
                LIMIT ?
                """,
                (job_id, limit),
            )
        )


def create_outreach_action(
    *,
    job_id: int,
    lead_id: int | None,
    channel: str,
    direction: str = "outbound",
    status: str = "draft",
    body: str = "",
    notes: str = "",
    due_at: str | None = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO outreach_actions(job_id, lead_id, channel, direction, status, body, notes, due_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, lead_id, channel, direction, status, body, notes, due_at),
        )
        return int(cur.lastrowid)


def update_outreach_action(action_id: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {"status", "notes", "completed_at"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown outreach fields: {', '.join(sorted(unknown))}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [action_id]
    with connect() as conn:
        conn.execute(
            f"UPDATE outreach_actions SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
