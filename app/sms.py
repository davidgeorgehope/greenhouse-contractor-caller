from __future__ import annotations

import argparse

from twilio.rest import Client

from .config import get_settings
from .db import create_sms_message


def send_sms(to_number: str, body: str) -> str:
    settings = get_settings()
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise RuntimeError("Missing Twilio credentials")

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    status_callback = f"{settings.app_host.rstrip('/')}/greenhouse/sms/status"
    message = client.messages.create(
        to=to_number,
        from_=settings.twilio_from,
        body=body,
        status_callback=status_callback,
    )
    create_sms_message(
        direction="outbound",
        from_number=settings.twilio_from,
        to_number=to_number,
        body=body,
        twilio_sid=message.sid,
        status=message.status,
    )
    return str(message.sid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a greenhouse contractor SMS from the Twilio project number.")
    parser.add_argument("to_number")
    parser.add_argument("body")
    args = parser.parse_args()
    sid = send_sms(args.to_number, args.body)
    print(f"sent {sid}")


if __name__ == "__main__":
    main()
