from __future__ import annotations

from app.agent import run_job_agent
from app.config import get_settings
from app.db import create_job, job_for_id, leads_for_job, upsert_lead


def test_job_agent_activates_job_promotes_reviews_and_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    monkeypatch.setenv("CALLER_DISABLED", "0")
    get_settings.cache_clear()
    job_id = create_job(
        title="Door fitting",
        job_type="door_installation",
        description="Fit an exterior door.",
        location="Gasport, NY",
    )
    upsert_lead(
        job_id=job_id,
        name="Review Door Lead",
        phone="+17165550101",
        category="door_installer",
        source_url="https://example.com/door",
        notes="Looks relevant.",
        priority=80,
        status="review",
    )

    def fake_discover(job_id: int) -> dict[str, object]:
        return {"created": 0, "searched": 0, "errors": [], "queries": []}

    placed_calls: list[tuple[int | None, bool]] = []

    def fake_place_calls(*, job_id: int | None = None, include_unknown_travel: bool = False) -> list[str]:
        placed_calls.append((job_id, include_unknown_travel))
        return ["placed"]

    monkeypatch.setattr("app.agent.discover_leads_for_job", fake_discover)
    monkeypatch.setattr("app.agent.place_calls", fake_place_calls)

    result = run_job_agent(job_id)
    leads = leads_for_job(job_id)

    assert job_for_id(job_id)["status"] == "active"
    assert leads[0]["status"] == "pending"
    assert placed_calls == [(job_id, True)]
    assert result["promoted"] == 1
    assert result["calls"] == 1
    get_settings.cache_clear()
