from __future__ import annotations


def test_fastapi_app_imports() -> None:
    from app.main import app

    assert app.title == "Contractor Relief"


def test_landing_page_is_public() -> None:
    from app.main import root

    response = root()

    assert "Stop chasing contractors." in response
    assert "Start a job" in response


def test_signup_creates_account_and_captures_project_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_AUTH_SECRET", "test-secret")

    from app.config import get_settings
    from app.main import signup

    get_settings.cache_clear()

    class FakeUrl:
        scheme = "https"
        hostname = "contractorrelief.ai"

    class FakeRequest:
        headers = {}
        url = FakeUrl()

    response = signup(
        request=FakeRequest(),
        display_name="Owner",
        email="owner@example.com",
        password="long-password-123",
        project_type="Fence repair",
        location="Buffalo, NY",
        notes="Nobody calls back.",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/contractor/billing"
    assert "contractor_session" in response.headers["set-cookie"]

    from app.db import connect

    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", ("owner@example.com",)).fetchone()
        row = conn.execute("SELECT * FROM signups WHERE email = ?", ("owner@example.com",)).fetchone()
    assert user is not None
    assert row is not None
    assert row["project_type"] == "Fence repair"
    assert row["source"] == "account_signup"
