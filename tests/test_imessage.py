from __future__ import annotations

import subprocess

from app.config import get_settings
from app.imessage import send_imessage


def test_send_imessage_records_manual_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    monkeypatch.setattr("app.imessage.shutil.which", lambda name: "/opt/homebrew/bin/imsg")

    calls = []

    def fake_run(args, check, capture_output, text):
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="sent", stderr="")

    monkeypatch.setattr("app.imessage.subprocess.run", fake_run)

    message_id = send_imessage("+17165550100", "Greenhouse details")

    assert message_id == 1
    assert calls == [
        ["imsg", "send", "--to", "+17165550100", "--text", "Greenhouse details", "--service", "auto"]
    ]
    get_settings.cache_clear()
