from __future__ import annotations

from app.config import get_settings
from app.db import create_sms_message


def test_create_sms_message_records_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()

    sms_id = create_sms_message(
        direction="inbound",
        from_number="+17165550100",
        to_number="+17165550100",
        body="Can you send photos?",
        twilio_sid="SMtest",
        status="received",
        raw_payload={"Body": "Can you send photos?"},
    )

    assert sms_id == 1
    get_settings.cache_clear()
