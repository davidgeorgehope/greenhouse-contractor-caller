from __future__ import annotations

from app.config import get_settings
from app.db import create_job, leads_for_job
from app.discovery import SearchResult, discover_leads_for_job, discovery_queries, normalize_phone, result_fit_score, search_contractors


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


def test_greenhouse_discovery_rejects_adjacent_wrong_trade(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="10x10 greenhouse assembly",
        job_type="assembly",
        description="Assemble a customer-owned Exaco Janssens greenhouse kit.",
        location="Gasport, NY",
    )
    job = __import__("app.db").db.job_for_id(job_id)

    good = SearchResult(
        title="WNY Handyman Assembly",
        url="https://example.com/handyman",
        snippet="Greenhouse, shed, and gazebo assembly near Buffalo. Call (716) 555-0199.",
    )
    bad = SearchResult(
        title="Garage Doors Buffalo",
        url="https://example.com/garage-doors",
        snippet="Overhead garage door installation and repair. Call (716) 555-0188.",
    )

    good_score, good_reasons = result_fit_score(job, good)
    bad_score, bad_reasons = result_fit_score(job, bad)

    assert good_score >= 25, good_reasons
    assert bad_score < 25, bad_reasons
    get_settings.cache_clear()


def test_discover_leads_filters_low_fit_search_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="10x10 greenhouse assembly",
        job_type="assembly",
        description="Assemble a customer-owned Exaco Janssens greenhouse kit.",
        location="Gasport, NY",
    )

    def fake_search(query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title="Garage Doors Buffalo",
                url="https://example.com/garage-doors",
                snippet="Overhead garage door installation and repair. Call (716) 555-0188.",
            ),
            SearchResult(
                title="WNY Handyman Assembly",
                url="https://example.com/handyman",
                snippet="Greenhouse, shed, and gazebo assembly near Buffalo. Call (716) 555-0199.",
            ),
        ]

    monkeypatch.setattr("app.discovery.search_contractors", fake_search)
    monkeypatch.setattr("app.discovery._page_text", lambda url: "")
    monkeypatch.setattr("app.discovery.travel_from_gasport", lambda address: None)

    result = discover_leads_for_job(job_id, query="greenhouse assembly Gasport NY")
    leads = leads_for_job(job_id)

    assert result["created"] == 1
    assert result["searched"] == 2
    assert leads[0]["name"] == "WNY Handyman Assembly"
    assert leads[0]["phone"] == "+17165550199"
    assert "Garage" not in leads[0]["name"]
    get_settings.cache_clear()


def test_search_contractors_falls_back_when_gemini_errors(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    get_settings.cache_clear()

    def broken_gemini(query: str) -> list[SearchResult]:
        raise RuntimeError("Gemini rejected grounded JSON mode")

    monkeypatch.setattr("app.discovery._gemini_grounded_search", broken_gemini)
    monkeypatch.setattr(
        "app.discovery._brave_search",
        lambda query: [
            SearchResult(
                title="WNY Handyman Assembly",
                url="https://example.com/handyman",
                snippet="Greenhouse and gazebo assembly near Buffalo. Call (716) 555-0199.",
            )
        ],
    )
    monkeypatch.setattr("app.discovery._duckduckgo_search", lambda query: [])

    results = search_contractors("greenhouse assembly Gasport NY")

    assert [result.title for result in results] == ["WNY Handyman Assembly"]
    get_settings.cache_clear()
