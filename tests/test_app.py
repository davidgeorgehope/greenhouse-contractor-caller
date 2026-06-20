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


def test_dashboard_test_tools_are_owner_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_AUTH_SECRET", "test-secret")

    from app.auth import create_session, create_user
    from app.config import get_settings
    from app.db import create_job
    from app.main import contractor_dashboard

    get_settings.cache_clear()

    class FakeUrl:
        scheme = "https"
        hostname = "contractorrelief.ai"

    class FakeRequest:
        headers = {}
        url = FakeUrl()

        def __init__(self, token: str) -> None:
            self.cookies = {"contractor_session": token}

    customer_id = create_user(email="customer@example.com", password="long-password-123", display_name="Customer")
    customer_token, _ = create_session(customer_id)
    create_job(title="Fence repair", job_type="fence", description="Fix fence.", location="Buffalo", user_id=customer_id)

    customer_page = contractor_dashboard(FakeRequest(customer_token))

    assert "Launch outreach" in customer_page
    assert "Test call David" not in customer_page
    assert "Clean test calls" not in customer_page

    owner_id = create_user(email="email.djhope@gmail.com", password="long-password-123", display_name="David")
    owner_token, _ = create_session(owner_id)
    create_job(title="Greenhouse", job_type="assembly", description="Assemble greenhouse.", location="Gasport", user_id=owner_id)

    owner_page = contractor_dashboard(FakeRequest(owner_token))

    assert "Test call David" in owner_page
    assert "Clean test calls" in owner_page


def test_test_call_endpoint_is_owner_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_AUTH_SECRET", "test-secret")

    import pytest
    from fastapi import HTTPException

    from app.auth import create_session, create_user
    from app.config import get_settings
    from app.db import create_job
    from app.main import run_test_call

    get_settings.cache_clear()

    class FakeUrl:
        scheme = "https"
        hostname = "contractorrelief.ai"

    class FakeRequest:
        headers = {}
        url = FakeUrl()

        def __init__(self, token: str) -> None:
            self.cookies = {"contractor_session": token}

    class FakeBackgroundTasks:
        def add_task(self, *args, **kwargs) -> None:
            raise AssertionError("Non-owner should not queue test calls")

    customer_id = create_user(email="customer@example.com", password="long-password-123", display_name="Customer")
    token, _ = create_session(customer_id)
    job_id = create_job(title="Fence repair", job_type="fence", description="Fix fence.", location="Buffalo", user_id=customer_id)

    with pytest.raises(HTTPException) as exc:
        run_test_call(FakeRequest(token), FakeBackgroundTasks(), job_id)

    assert exc.value.status_code == 403


def test_test_billing_endpoint_is_owner_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "contractor.sqlite3"))
    monkeypatch.setenv("CONTRACTOR_AUTH_SECRET", "test-secret")

    import pytest
    from fastapi import HTTPException

    from app.auth import create_session, create_user
    from app.config import get_settings
    from app.main import activate_test_billing

    get_settings.cache_clear()

    class FakeUrl:
        scheme = "https"
        hostname = "contractorrelief.ai"

    class FakeRequest:
        headers = {}
        url = FakeUrl()

        def __init__(self, token: str) -> None:
            self.cookies = {"contractor_session": token}

    customer_id = create_user(email="customer@example.com", password="long-password-123", display_name="Customer")
    token, _ = create_session(customer_id)

    with pytest.raises(HTTPException) as exc:
        activate_test_billing(FakeRequest(token))

    assert exc.value.status_code == 403
