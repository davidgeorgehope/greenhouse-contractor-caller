from __future__ import annotations

import smtplib
import json
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from .config import get_settings
from .db import create_email_message


def split_subject_body(body: str) -> tuple[str, str]:
    lines = body.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip() or "Contractor job"
        return subject, "\n".join(lines[1:]).lstrip()
    return "Contractor job", body.strip()


def send_email(to_email: str, body: str) -> str:
    settings = get_settings()
    sender = (
        settings.resend_from
        if settings.resend_api_key and settings.resend_from
        else settings.cloudflare_email_from
        if settings.cloudflare_account_id and settings.cloudflare_email_token and settings.cloudflare_email_from
        else settings.smtp_from
        if settings.smtp_host and settings.smtp_from
        else ""
    )
    subject, message_body = split_subject_body(body)
    if settings.resend_api_key and settings.resend_from:
        receipt = _send_resend(to_email, body, settings.resend_api_key, settings.resend_from)
    elif settings.cloudflare_account_id and settings.cloudflare_email_token and settings.cloudflare_email_from:
        receipt = _send_cloudflare(
            to_email,
            body,
            settings.cloudflare_account_id,
            settings.cloudflare_email_token,
            settings.cloudflare_email_from,
        )
    elif settings.smtp_host and settings.smtp_from:
        message = EmailMessage()
        message["To"] = to_email
        message["From"] = settings.smtp_from
        message["Subject"] = subject
        message.set_content(message_body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username or settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)

        receipt = message["Message-ID"] or f"smtp:{to_email}"
    else:
        raise RuntimeError("Missing email sender settings")

    create_email_message(
        direction="outbound",
        from_email=sender,
        to_email=to_email,
        subject=subject,
        body=message_body,
        message_id=receipt,
        status="sent",
    )
    return receipt


def _sender_value(sender: str) -> str | dict[str, str]:
    name, address = parseaddr(sender)
    if not address:
        return sender.strip()
    if name:
        return {"address": address, "name": name}
    return address


def _send_cloudflare(to_email: str, body: str, account_id: str, api_token: str, from_email: str) -> str:
    subject, message_body = split_subject_body(body)
    payload = json.dumps(
        {
            "to": to_email,
            "from": _sender_value(from_email),
            "subject": subject,
            "text": message_body,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Cloudflare email failed with HTTP {exc.code}: {detail[:500]}") from exc
    if not response_body.get("success"):
        raise RuntimeError(f"Cloudflare email failed: {response_body}")
    return str(response_body.get("result", {}).get("id") or f"cloudflare:{to_email}")


def _send_resend(to_email: str, body: str, api_key: str, from_email: str) -> str:
    subject, message_body = split_subject_body(body)
    payload = json.dumps(
        {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": message_body,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Resend email failed with HTTP {exc.code}: {detail[:500]}") from exc
    return str(response_body.get("id") or f"resend:{to_email}")
