from __future__ import annotations

import re
from typing import Any

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 12.0


def _strip_html(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&[a-z#0-9]+;", " ", html, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", html).strip()


def _wikipedia_summary(company_name: str, client: httpx.Client) -> dict[str, str] | None:
    title = company_name.replace(" ", "_")
    resp = client.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
        headers={**_HEADERS, "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    extract = data.get("extract", "").strip()
    if not extract:
        return None
    page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
    return {"text": extract, "url": page_url}


def _ddg_html_search(query: str, client: httpx.Client, max_results: int = 5) -> list[dict[str, str]]:
    resp = client.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=_HEADERS,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    html = resp.text

    # Extract result URLs and snippets
    url_pattern = re.compile(r'<a[^>]+class="[^"]*result__url[^"]*"[^>]*href="([^"]+)"', re.IGNORECASE)
    snippet_pattern = re.compile(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)

    urls = url_pattern.findall(html)
    snippets = [_strip_html(s) for s in snippet_pattern.findall(html)]

    results = []
    for url, snippet in zip(urls[:max_results], snippets[:max_results]):
        if url and not url.startswith("//duckduckgo"):
            results.append({"url": url, "snippet": snippet})
    return results


def _ddg_instant(query: str, client: httpx.Client) -> dict[str, Any]:
    resp = client.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        headers=_HEADERS,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_page(url: str, client: httpx.Client, max_chars: int = 4000) -> str:
    resp = client.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return _strip_html(resp.text)[:max_chars]


def research_company_online(
    company_name: str,
    job_description: str = "",
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    sources: list[str] = []
    errors: list[str] = []

    with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
        # Wikipedia summary (most reliable source for company overviews)
        try:
            wiki = _wikipedia_summary(company_name, client)
            if wiki:
                findings.append({
                    "type": "overview",
                    "source": wiki["url"],
                    "text": wiki["text"],
                })
                if wiki["url"]:
                    sources.append(wiki["url"])
        except Exception as exc:
            errors.append(f"Wikipedia: {exc}")

        # DDG instant answer as supplemental overview if Wikipedia gave nothing
        if not any(f["type"] == "overview" for f in findings):
            try:
                data = _ddg_instant(company_name, client)
                if data.get("AbstractText"):
                    findings.append({
                        "type": "overview",
                        "source": data.get("AbstractURL", ""),
                        "text": data["AbstractText"],
                    })
                    if data.get("AbstractURL"):
                        sources.append(data["AbstractURL"])
                for topic in (data.get("RelatedTopics") or [])[:3]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        findings.append({
                            "type": "related",
                            "source": topic.get("FirstURL", ""),
                            "text": topic["Text"],
                        })
            except Exception as exc:
                errors.append(f"DDG instant: {exc}")

        # DuckDuckGo HTML search for engineering/tech context
        try:
            results = _ddg_html_search(f"{company_name} engineering technology stack", client)
            for r in results[:3]:
                if r["snippet"]:
                    findings.append({
                        "type": "tech",
                        "source": r["url"],
                        "text": r["snippet"],
                    })
        except Exception as exc:
            errors.append(f"DDG search tech: {exc}")

        # Fetch official company page if a non-Wikipedia, non-DDG URL was found
        official_url = next(
            (
                f["source"]
                for f in findings
                if f.get("source")
                and "duckduckgo" not in f["source"]
                and "wikipedia" not in f["source"]
            ),
            None,
        )
        if official_url:
            try:
                page_text = _fetch_page(official_url, client)
                if page_text:
                    findings.append({
                        "type": "webpage",
                        "source": official_url,
                        "text": page_text,
                    })
            except Exception as exc:
                errors.append(f"Fetch {official_url}: {exc}")

        # If a job description was given, search for role-specific context
        if job_description:
            domain_words = " ".join(job_description.split()[:12])
            try:
                results = _ddg_html_search(f"{company_name} {domain_words}", client, max_results=3)
                for r in results[:2]:
                    if r["snippet"]:
                        findings.append({
                            "type": "role_context",
                            "source": r["url"],
                            "text": r["snippet"],
                        })
            except Exception as exc:
                errors.append(f"DDG role context: {exc}")

    return {
        "company_name": company_name,
        "job_description_provided": bool(job_description),
        "findings": findings,
        "sources": list(dict.fromkeys(sources)),
        "errors": errors,
    }
