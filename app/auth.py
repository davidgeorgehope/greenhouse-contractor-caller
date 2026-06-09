from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status

from .config import get_settings
from .db import connect

PASSWORD_ITERATIONS = 260_000
SESSION_DAYS = 14


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256$%s$%s$%s" % (PASSWORD_ITERATIONS, _b64(salt), _b64(digest))


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw + "=" * (-len(salt_raw) % 4))
        expected = base64.urlsafe_b64decode(digest_raw + "=" * (-len(digest_raw) % 4))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _hash_token(token: str) -> str:
    secret = get_settings().contractor_auth_secret
    if not secret:
        raise RuntimeError("CONTRACTOR_AUTH_SECRET is required for dashboard authentication")
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def has_users() -> bool:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return bool(row and int(row["count"]) > 0)


def create_user(*, email: str, password: str, display_name: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash, display_name) VALUES (?, ?, ?)",
            (email.strip().lower(), _hash_password(password), display_name.strip()),
        )
        return int(cur.lastrowid)


def authenticate_user(email: str, password: str) -> sqlite3.Row | None:
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if user is None or not _verify_password(password, str(user["password_hash"])):
            return None
        conn.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (int(user["id"]),))
        return user


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions(user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, _hash_token(token), expires_at.isoformat()),
        )
    return token, expires_at


def delete_session(token: str | None) -> None:
    if not token:
        return
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


def current_user(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(get_settings().contractor_session_cookie)
    if not token:
        return None
    now = datetime.now(UTC).isoformat()
    with connect() as conn:
        user = conn.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (_hash_token(token), now),
        ).fetchone()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        return user


def require_user(request: Request) -> sqlite3.Row:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/contractor/login"})
    return user
