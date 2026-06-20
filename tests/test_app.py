from __future__ import annotations


def test_fastapi_app_imports() -> None:
    from app.main import app

    assert app.title == "Contractor Relief"


def test_landing_page_is_public() -> None:
    from app.main import root

    response = root()

    assert "Stop chasing contractors." in response
    assert "Join early access" in response


def test_signup_captures_early_access(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))

    from app.config import get_settings
    from app.db import connect
    from app.main import signup

    get_settings.cache_clear()

    response = signup(
        display_name="Owner",
        email="owner@example.com",
        project_type="Fence repair",
        location="Buffalo, NY",
        notes="Nobody calls back.",
    )

    assert "early access list" in response
    with connect() as conn:
        row = conn.execute("SELECT * FROM signups WHERE email = ?", ("owner@example.com",)).fetchone()
    assert row is not None
    assert row["project_type"] == "Fence repair"
