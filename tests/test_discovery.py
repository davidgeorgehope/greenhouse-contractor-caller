from __future__ import annotations

from app.config import get_settings
from app.db import create_job, leads_for_job
from app.discovery import (
    SearchResult,
    _page_text,
    discover_leads_for_job,
    discovery_queries,
    normalize_phone,
    result_fit_score,
    search_contractors,
)


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

    assert any("exterior door replacement" in query for query in queries)
    assert all("Gasport" in query or "Gasport" in query for query in queries)
    get_settings.cache_clear()


def test_discovery_queries_prioritize_service_terms_for_common_jobs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()

    cases = [
        (
            "Dishwasher installation",
            "appliance_installation",
            "Install a replacement built-in dishwasher.",
            "dishwasher installation Gasport Lockport",
            "contractor",
        ),
        (
            "TV wall mounting",
            "tv_mounting",
            "Mount a 55 inch TV on drywall.",
            "tv mounting Gasport Lockport",
            "contractor",
        ),
        (
            "Junk removal from garage",
            "junk_removal",
            "Remove old furniture and garage junk.",
            "junk removal Gasport Lockport",
            "contractor",
        ),
        (
            "Fence post repair",
            "fence_repair",
            "Repair leaning wooden fence posts.",
            "fence repair contractor Gasport Lockport",
            "",
        ),
    ]

    for title, job_type, description, expected_start, unwanted in cases:
        job_id = create_job(title=title, job_type=job_type, description=description, location="Gasport, NY")
        first_query = discovery_queries(__import__("app.db").db.job_for_id(job_id))[0]
        assert first_query.startswith(expected_start)
        if unwanted:
            assert unwanted not in first_query

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


def test_page_text_keeps_mailto_and_tel_links(monkeypatch) -> None:
    def fake_open_url(url: str, *, headers=None, timeout: int = 12) -> str:
        return """
        <html>
          <a href="mailto:quotes@example.com?subject=Job">Email us</a>
          <a href="tel:+17165550199">Call</a>
        </html>
        """

    monkeypatch.setattr("app.discovery._open_url", fake_open_url)

    text = _page_text("https://example.com/contact")

    assert "quotes@example.com" in text
    assert "+17165550199" in text


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


def test_exterior_door_discovery_rejects_garage_door_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Exterior door replacement",
        job_type="door_installation",
        description="Replace a rotted exterior side door and frame.",
        location="Gasport, NY",
    )

    def fake_search(query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title="Garage Door Installation in Buffalo NY",
                url="https://example.com/garage-door",
                snippet="Overhead garage door installation. Call (716) 555-0188.",
            ),
            SearchResult(
                title="The Upgrade Guy Buffalo Handyman",
                url="https://example.com/exterior-door",
                snippet="Exterior door replacement and carpentry. Call (716) 555-0199.",
            ),
        ]

    monkeypatch.setattr("app.discovery.search_contractors", fake_search)
    monkeypatch.setattr("app.discovery._page_text", lambda url: "")
    monkeypatch.setattr("app.discovery.travel_from_gasport", lambda address: None)

    result = discover_leads_for_job(job_id, query="exterior door replacement Gasport NY")
    leads = leads_for_job(job_id)

    assert result["created"] == 1
    assert leads[0]["name"] == "The Upgrade Guy Buffalo Handyman"
    get_settings.cache_clear()


def test_discovery_rejects_job_board_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Interior door fitting",
        job_type="door_installation",
        description="Fit and hang an interior door.",
        location="Gasport, NY",
    )

    def fake_search(query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title="Niagara County, NY",
                url="https://www.niagaracounty.gov/worksource_one/job_seeker/hot_jobs.php",
                snippet=(
                    "To apply, contact the employer by telephone or email. "
                    "Carpenter job opening in Lockport. Call 716-555-0188 or email employer@example.com."
                ),
            ),
            SearchResult(
                title="WNY Door Handyman",
                url="https://example.com/door-handyman",
                snippet="Interior door installation and handyman carpentry near Buffalo. Call (716) 555-0199.",
            ),
        ]

    monkeypatch.setattr("app.discovery.search_contractors", fake_search)
    monkeypatch.setattr("app.discovery._page_text", lambda url: "")
    monkeypatch.setattr("app.discovery.travel_from_gasport", lambda address: None)

    result = discover_leads_for_job(job_id, query="carpenter contractor Gasport NY")
    leads = leads_for_job(job_id)

    assert result["created"] == 1
    assert leads[0]["name"] == "WNY Door Handyman"
    get_settings.cache_clear()


def test_discovery_rejects_placeholder_contact_details(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "greenhouse.sqlite3"))
    get_settings.cache_clear()
    job_id = create_job(
        title="Deck board replacement",
        job_type="deck_repair",
        description="Replace damaged deck boards.",
        location="Gasport, NY",
    )

    def fake_search(query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title="Deck Repair Example",
                url="https://example.com/bad-deck",
                snippet="Deck repair near Buffalo. Call (555) 555-5555 or email mymail@mailservice.com.",
            ),
            SearchResult(
                title="Buffalo Deck Repair",
                url="https://example.com/good-deck",
                snippet="Deck repair near Buffalo. Call (716) 555-0199 or email quotes@example.com.",
            ),
        ]

    monkeypatch.setattr("app.discovery.search_contractors", fake_search)
    monkeypatch.setattr("app.discovery._page_text", lambda url: "")
    monkeypatch.setattr("app.discovery.travel_from_gasport", lambda address: None)

    result = discover_leads_for_job(job_id, query="deck repair Gasport NY")
    leads = leads_for_job(job_id)

    assert result["created"] == 1
    assert leads[0]["name"] == "Buffalo Deck Repair"
    assert leads[0]["phone"] == "+17165550199"
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


def test_search_contractors_falls_back_when_brave_errors(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave")
    get_settings.cache_clear()

    def broken_brave(query: str) -> list[SearchResult]:
        raise RuntimeError("Brave rate limited")

    monkeypatch.setattr("app.discovery._brave_search", broken_brave)
    monkeypatch.setattr(
        "app.discovery._duckduckgo_search",
        lambda query: [
            SearchResult(
                title="Buffalo Deck Repair",
                url="https://example.com/deck",
                snippet="Deck repair near Buffalo. Call (716) 555-0199.",
            )
        ],
    )

    results = search_contractors("deck repair Gasport NY")

    assert [result.title for result in results] == ["Buffalo Deck Repair"]
    get_settings.cache_clear()


def test_search_contractors_returns_empty_when_all_providers_error(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave")
    get_settings.cache_clear()

    monkeypatch.setattr("app.discovery._gemini_grounded_search", lambda query: (_ for _ in ()).throw(RuntimeError("gemini down")))
    monkeypatch.setattr("app.discovery._brave_search", lambda query: (_ for _ in ()).throw(RuntimeError("brave down")))
    monkeypatch.setattr("app.discovery._duckduckgo_search", lambda query: (_ for _ in ()).throw(RuntimeError("ddg down")))

    assert search_contractors("deck repair Gasport NY") == []
    get_settings.cache_clear()
