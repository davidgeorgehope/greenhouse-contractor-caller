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
MAX_CREATED_LEADS_PER_JOB = 8


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
    terms = [title]
    haystack = f"{title} {job_type} {description}".lower()
    if "door" in haystack:
        terms.extend(["door installer", "handyman exterior door", "carpenter"])
    if "greenhouse" in haystack:
        terms.extend(["greenhouse installer", "greenhouse assembly handyman", "shed gazebo assembly"])
    if "fence" in haystack:
        terms.extend(["fence repair", "fence contractor"])
    if "deck" in haystack:
        terms.extend(["deck repair", "deck contractor"])
    if "drywall" in haystack:
        terms.extend(["drywall repair", "handyman drywall"])
    if "gutter" in haystack:
        terms.extend(["gutter repair", "gutter cleaning"])
    if "tv" in haystack or "television" in haystack or "mounting" in haystack:
        terms.extend(["tv mounting", "home theater installation"])
    if "dishwasher" in haystack or "appliance" in haystack:
        terms.extend(["dishwasher installation", "appliance installation"])
    if "junk" in haystack or "hauling" in haystack:
        terms.extend(["junk removal", "hauling service"])
    if not terms:
        terms.append(job_type)
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


def _job_terms(job) -> set[str]:
    haystack = f"{job['title']} {job['job_type']} {job['description']}".lower()
    terms: set[str] = set()
    if "greenhouse" in haystack:
        terms.update({"greenhouse", "assembly", "installer", "installation", "handyman", "shed", "gazebo"})
    if "door" in haystack:
        terms.update({"door", "carpenter", "installation", "installer", "handyman"})
    if "fence" in haystack:
        terms.update({"fence", "fencing", "repair", "post", "contractor"})
    if "deck" in haystack:
        terms.update({"deck", "decking", "repair", "boards", "railing", "contractor"})
    if "drywall" in haystack:
        terms.update({"drywall", "sheetrock", "patch", "paint", "repair", "handyman"})
    if "gutter" in haystack:
        terms.update({"gutter", "gutters", "cleaning", "repair", "roof"})
    if "tv" in haystack or "television" in haystack or "mounting" in haystack:
        terms.update({"tv", "television", "mounting", "installation", "installer", "home theater"})
    if "dishwasher" in haystack or "appliance" in haystack:
        terms.update({"dishwasher", "appliance", "installation", "installer", "plumbing"})
    if "junk" in haystack or "hauling" in haystack:
        terms.update({"junk", "removal", "hauling", "trash", "debris"})
    for word in re.findall(r"[a-z][a-z0-9]{3,}", haystack):
        if word not in {"contractor", "general", "need", "needs", "near", "help", "with"}:
            terms.add(word)
    return terms or {"contractor", "handyman"}


def _irrelevant_terms_for_job(job) -> set[str]:
    haystack = f"{job['title']} {job['job_type']} {job['description']}".lower()
    irrelevant = {
        "auto",
        "automotive",
        "car dealer",
        "dentist",
        "doctor",
        "lawyer",
        "restaurant",
        "hotel",
        "property management",
        "real estate",
    }
    if "greenhouse" in haystack:
        irrelevant.update(
            {
                "garage door",
                "overhead door",
                "roofing",
                "siding",
                "gutter",
                "hvac",
                "plumbing",
                "electrician",
                "pest control",
                "lawn care",
                "snow removal",
            }
        )
    if "door" in haystack and "garage" not in haystack:
        irrelevant.update({"garage door", "overhead door", "garage doors"})
    if "fence" in haystack:
        irrelevant.update({"deck", "roofing", "siding", "gutter", "garage door"})
    if "deck" in haystack:
        irrelevant.update({"roofing", "siding", "gutter", "fence installation only"})
    if "drywall" in haystack:
        irrelevant.update({"roofing", "siding", "gutter", "concrete", "paving"})
    if "tv" in haystack or "television" in haystack or "mounting" in haystack:
        irrelevant.update({"cell phone", "broadcast", "tv station", "provider", "spectrum", "drywall repair", "drywall contractor", "sheetrock"})
    return irrelevant


def result_fit_score(job, result: SearchResult, page_text: str = "") -> tuple[int, list[str]]:
    primary_text = f"{result.title} {result.snippet} {result.url}".lower()
    text = f"{primary_text} {page_text[:4000]}".lower()
    url = result.url.lower()
    score = 0
    reasons: list[str] = []

    for term in sorted(_job_terms(job), key=len, reverse=True):
        if term and term in text:
            score += 18 if term in {"greenhouse", "door"} else 8
            reasons.append(f"matched:{term}")

    contractor_markers = {
        "contractor",
        "handyman",
        "installer",
        "installation",
        "assembly",
        "repair",
        "construction",
        "carpentry",
        "home improvement",
    }
    for marker in contractor_markers:
        if marker in text:
            score += 7
            reasons.append(f"trade:{marker}")
            break

    local_markers = {"buffalo", "gasport", "lockport", "niagara", "wny", "western new york"}
    if any(marker in text for marker in local_markers) or any(marker.replace(" ", "") in url for marker in local_markers):
        score += 10
        reasons.append("local")

    if phones_from_text(text):
        score += 5
        reasons.append("phone")
    if emails_from_text(text):
        score += 2
        reasons.append("email")

    for bad in _irrelevant_terms_for_job(job):
        if bad in primary_text:
            score -= 35
            reasons.append(f"irrelevant:{bad}")

    directory_hosts = (
        "yelp.",
        "angi.",
        "thumbtack.",
        "homeadvisor.",
        "bbb.",
        "mapquest.",
        "yellowpages.",
        "procore.com/network",
        "porch.com/",
        "localprobook.com/",
    )
    if any(host in url for host in directory_hosts):
        score -= 70
        reasons.append("directory")
    directory_phrases = ("find contractors", "best 10", "quicklink category", "members/ql", "near me")
    if any(phrase in primary_text for phrase in directory_phrases):
        score -= 70
        reasons.append("directory-list")

    return score, reasons


def normalize_phone(value: str) -> str | None:
    match = PHONE_RE.search(value)
    if match is None:
        return None
    return "+1" + "".join(match.groups())


def _is_placeholder_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    national = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
    return national in {"5555555555", "0000000000", "1111111111"} or len(set(national)) == 1


def _is_placeholder_email(email: str) -> bool:
    return email.lower() in {"mymail@mailservice.com", "email@example.com", "test@example.com"}


def phones_from_text(value: str) -> list[str]:
    phones: list[str] = []
    seen: set[str] = set()
    for match in PHONE_RE.finditer(value):
        phone = "+1" + "".join(match.groups())
        if _is_placeholder_phone(phone):
            continue
        if phone not in seen:
            seen.add(phone)
            phones.append(phone)
    return phones


def emails_from_text(value: str) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_RE.finditer(value):
        email = match.group(0).lower()
        if _is_placeholder_email(email):
            continue
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


def _extract_json_array(value: str) -> list[object]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("[")
        end = value.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(value[start : end + 1])
        except json.JSONDecodeError:
            return []
    return data if isinstance(data, list) else []


def _gemini_grounded_search(query: str) -> list[SearchResult]:
    settings = get_settings()
    if not settings.gemini_api_key:
        return []
    prompt = (
        "Find local or clearly relevant contractor businesses for this home-service job search. "
        "Prefer individual business pages over directories. Return only a JSON array of objects "
        "with title, url, and snippet. Include no markdown. Search query: "
        f"{query}"
    )
    model = urllib.parse.quote(settings.gemini_search_model, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.2,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read(1_000_000).decode("utf-8", errors="ignore"))
    text_parts: list[str] = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                text_parts.append(str(part["text"]))
    results: list[SearchResult] = []
    for item in _extract_json_array("\n".join(text_parts)):
        if not isinstance(item, dict) or not item.get("url"):
            continue
        results.append(
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("snippet") or ""),
            )
        )
    return results[: settings.discovery_results_per_query]


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
    settings = get_settings()
    results: list[SearchResult] = []
    if settings.gemini_api_key:
        try:
            results.extend(_gemini_grounded_search(query))
        except Exception:
            pass
    brave_results = _brave_search(query)
    if brave_results:
        results.extend(brave_results)
    if not results:
        results.extend(_duckduckgo_search(query))
    deduped: list[SearchResult] = []
    seen: set[str] = set()
    for result in results:
        key = result.url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


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
            if created >= MAX_CREATED_LEADS_PER_JOB:
                break
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            combined = f"{result.title} {result.snippet}"
            phones = phones_from_text(combined)
            emails = emails_from_text(combined)
            page_text = ""
            initial_score, _ = result_fit_score(job, result)
            if initial_score < 25 or not phones or not emails:
                page_text = _page_text(result.url)
            fit_score, fit_reasons = result_fit_score(job, result, page_text)
            if any(reason.startswith("irrelevant:") for reason in fit_reasons):
                continue
            if any(reason in {"directory", "directory-list"} for reason in fit_reasons):
                continue
            if fit_score < 25:
                continue
            if not phones:
                phones = phones_from_text(page_text)
            if not emails:
                emails = emails_from_text(page_text)
            if not phones:
                continue
            if fit_score < 35 and not emails:
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
            notes = (
                f"Discovered from search query: {search_query}. "
                f"Fit score {fit_score} ({', '.join(fit_reasons[:6])}). "
                "Review fit before executing outreach."
            )
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
                priority=max(10, min(95, fit_score)),
                status="review",
            )
            created += 1
    return {"created": created, "searched": searched, "errors": errors, "queries": queries}
