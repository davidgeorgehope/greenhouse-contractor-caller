from __future__ import annotations


def test_fastapi_app_imports() -> None:
    from app.main import app

    assert app.title == "Contractor Relief"
