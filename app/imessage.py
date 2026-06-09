from __future__ import annotations

import argparse
import shutil
import subprocess

from .config import get_settings
from .db import create_sms_message


def send_imessage(to_number: str, body: str) -> int:
    if shutil.which("imsg") is None:
        raise RuntimeError("Missing imsg CLI; install steipete/tap/imsg and confirm Messages.app access")

    result = subprocess.run(
        ["imsg", "send", "--to", to_number, "--text", body, "--service", "auto"],
        check=True,
        capture_output=True,
        text=True,
    )
    settings = get_settings()
    return create_sms_message(
        direction="outbound",
        from_number=settings.imsg_from_label,
        to_number=to_number,
        body=body,
        status="imsg_sent",
        raw_payload={"stdout": result.stdout.strip(), "stderr": result.stderr.strip()},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a greenhouse contractor text from the operator's Messages.app account."
    )
    parser.add_argument("to_number")
    parser.add_argument("body")
    args = parser.parse_args()
    message_id = send_imessage(args.to_number, args.body)
    print(f"sent imsg message record {message_id}")


if __name__ == "__main__":
    main()
