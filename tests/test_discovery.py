from __future__ import annotations

from app.config import get_settings
from app.db import create_job, leads_for_job
from app.discovery import SearchResult, discover_leads_for_job, discovery_queries, normalize_phone


def test_discovery_queries_follow_job_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Exterior door fitting",
        job_type="door_installation",
        description="Fit a replacement exterior door and frame.",
        location="Gasport, NY",
    )

    queries = discovery_queries(__import__("app.db").db.job_for_id(job_id))

    assert any("door installer" in query for query in queries)
    assert all("Gasport" in query or "Gasport" in query for query in queries)
    get_settings.cache_clear()


def test_normalize_phone_outputs_e164() -> None:
    assert normalize_phone("(716) 555-0199") == "+17165550199"
    assert normalize_phone("1-585-555-0101") == "+15855550101"


def test_discover_leads_for_job_adds_review_leads(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Exterior door fitting",
        job_type="door_installation",
        description="Fit a replacement exterior door and frame.",
        location="Gasport, NY",
    )

    def fake_search(query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title="WNY Door Pros",
                url="https://example.com/door",
                snippet="Exterior door installation. Call (716) 555-0199 or email quotes@example.com.",
            )
        ]

    monkeypatch.setattr("app.discovery.search_contractors", fake_search)
    monkeypatch.setattr("app.discovery.travel_from_gasport", lambda address: None)

    result = discover_leads_for_job(job_id, query="door installer Gasport NY")
    leads = leads_for_job(job_id)

    assert result["created"] == 1
    assert result["searched"] == 1
    assert leads[0]["name"] == "WNY Door Pros"
    assert leads[0]["phone"] == "+17165550199"
    assert leads[0]["email"] == "quotes@example.com"
    assert leads[0]["status"] == "review"
    get_settings.cache_clear()
