from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import get_settings
from .db import job_for_id, upsert_lead
from .geo import USER_AGENT, travel_from_gasport


PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-()]*)?(?:\(?([2-9]\d{2})\)?[\s.\-]*)"
    r"([2-9]\d{2})[\s.\-]*(\d{4})(?!\d)"
)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


def discovery_queries(job) -> list[str]:
    title = str(job["title"])
    job_type = str(job["job_type"] or "contractor").replace("_", " ")
    description = str(job["description"] or "")
    location = str(job["location"] or "Gasport NY")
    nearby = "Gasport Lockport Niagara County Buffalo NY"
    terms = [title, job_type]
    if "door" in f"{title} {job_type} {description}".lower():
        terms.extend(["door installer", "handyman exterior door", "carpenter"])
    if "greenhouse" in f"{title} {job_type} {description}".lower():
        terms.extend(["greenhouse installer", "handyman assembly", "general contractor"])
    seen: set[str] = set()
    queries: list[str] = []
    for term in terms:
        query = f"{term} contractor {nearby}"
        if query not in seen:
            seen.add(query)
            queries.append(query)
    if location and "Gasport" not in location:
        queries.append(f"{title} contractor near {location}")
    return queries[:4]


def normalize_phone(value: str) -> str | None:
    match = PHONE_RE.search(value)
    if match is None:
        return None
    return "+1" + "".join(match.groups())


def phones_from_text(value: str) -> list[str]:
    phones: list[str] = []
    seen: set[str] = set()
    for match in PHONE_RE.finditer(value):
        phone = "+1" + "".join(match.groups())
        if phone not in seen:
            seen.add(phone)
            phones.append(phone)
    return phones


def emails_from_text(value: str) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_RE.finditer(value):
        email = match.group(0).lower()
        if email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def _open_url(url: str, *, headers: dict[str, str] | None = None, timeout: int = 12) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text" not in content_type and "json" not in content_type and "html" not in content_type:
            return ""
        return response.read(750_000).decode("utf-8", errors="ignore")


def _brave_search(query: str) -> list[SearchResult]:
    settings = get_settings()
    if not settings.brave_search_api_key:
        return []
    params = urllib.parse.urlencode({"q": query, "count": settings.discovery_results_per_query, "country": "us"})
    payload = _open_url(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_search_api_key},
    )
    data = json.loads(payload)
    results = data.get("web", {}).get("results", [])
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("description") or ""),
        )
        for item in results
        if item.get("url")
    ]


def _duckduckgo_search(query: str) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query})
    payload = _open_url(f"https://duckduckgo.com/html/?{params}")
    results: list[SearchResult] = []
    for match in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        payload,
        re.S,
    ):
        raw_url = html.unescape(match.group(1))
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.path == "/l/":
            qs = urllib.parse.parse_qs(parsed.query)
            raw_url = qs.get("uddg", [raw_url])[0]
        title = re.sub(r"<[^>]+>", "", match.group(2))
        results.append(SearchResult(title=html.unescape(title).strip(), url=raw_url))
        if len(results) >= get_settings().discovery_results_per_query:
            break
    return results


def search_contractors(query: str) -> list[SearchResult]:
    brave_results = _brave_search(query)
    if brave_results:
        return brave_results
    return _duckduckgo_search(query)


def _page_text(url: str) -> str:
    try:
        payload = _open_url(url, timeout=10)
    except Exception:
        return ""
    payload = re.sub(r"(?is)<(script|style).*?</\1>", " ", payload)
    payload = re.sub(r"(?s)<[^>]+>", " ", payload)
    return html.unescape(re.sub(r"\s+", " ", payload))


def _category_for_job(job) -> str:
    job_type = str(job["job_type"] or "contractor").strip().lower().replace(" ", "_")
    return job_type or "contractor"


def discover_leads_for_job(job_id: int, query: str | None = None, user_id: int | None = None) -> dict[str, object]:
    job = job_for_id(job_id, user_id) if user_id is not None else job_for_id(job_id)
    if job is None:
        return {"created": 0, "searched": 0, "errors": ["Job not found."], "queries": []}

    queries = [query.strip()] if query and query.strip() else discovery_queries(job)
    created = 0
    searched = 0
    errors: list[str] = []
    seen_urls: set[str] = set()
    seen_phones: set[str] = set()
    category = _category_for_job(job)

    for search_query in queries:
        try:
            results = search_contractors(search_query)
        except Exception as exc:
            errors.append(f"{search_query}: {exc}")
            continue
        searched += len(results)
        for result in results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            combined = f"{result.title} {result.snippet}"
            phones = phones_from_text(combined)
            emails = emails_from_text(combined)
            page_text = ""
            if not phones or not emails:
                page_text = _page_text(result.url)
                if not phones:
                    phones = phones_from_text(page_text)
                if not emails:
                    emails = emails_from_text(page_text)
            if not phones:
                continue
            phone = phones[0]
            if phone in seen_phones:
                continue
            seen_phones.add(phone)
            title = result.title or urllib.parse.urlparse(result.url).netloc
            location_hint = "Gasport, NY"
            travel = None
            try:
                travel = travel_from_gasport(title + " " + location_hint)
            except Exception:
                travel = None
            origin_address = ""
            distance_miles = None
            drive_minutes = None
            origin_lat = None
            origin_lng = None
            if travel is not None:
                coords, distance_miles, drive_minutes = travel
                origin_lat = coords.lat
                origin_lng = coords.lng
                origin_address = title
            notes = f"Discovered from search query: {search_query}. Review fit before executing outreach."
            if result.snippet:
                notes += f" Snippet: {result.snippet[:280]}"
            upsert_lead(
                job_id=job_id,
                name=title[:160],
                phone=phone,
                email=emails[0] if emails else "",
                category=category,
                source_url=result.url,
                origin_address=origin_address,
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                distance_miles=distance_miles,
                drive_minutes=drive_minutes,
                service_area="",
                notes=notes,
                priority=60,
                status="review",
            )
            created += 1
    return {"created": created, "searched": searched, "errors": errors, "queries": queries}
