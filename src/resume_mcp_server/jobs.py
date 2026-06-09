"""Platsbanken job search via the JobTech Dev JobSearch API.

This is the public API behind Arbetsförmedlingen's Platsbanken job board
(https://jobsearch.api.jobtechdev.se). No API key is required. The server only
fetches and normalizes ads — it never calls an LLM and never decides whether the
candidate is qualified; that judgement runs as a fresh sub-agent (see
``critic.build_qualification_check_prompt``) and is enforced by a PostToolUse hook.

Two helpers:

- ``search_jobs`` — freetext ``GET /search`` returning a compact, normalized list.
- ``fetch_ad`` — ``GET /ad/{id}`` returning one full ad (untrimmed description plus
  the API's structured ``must_have``/``nice_to_have`` qualification blocks), used by
  the qualification step for accuracy.

Network calls are wrapped so the tools degrade gracefully (errors collected, never
raised) the way ``research.py`` does, since the MCP client should not hard-fail on a
transient network problem.
"""

from __future__ import annotations

from typing import Any

import httpx

_BASE_URL = "https://jobsearch.api.jobtechdev.se"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ResumeMCPServer/1.0 (+https://jobtechdev.se)",
}
_TIMEOUT = 15.0
_DESCRIPTION_LIMIT = 3000


def _location_str(workplace_address: dict[str, Any] | None) -> str:
    """Build a human-readable location from a hit's workplace_address block."""
    addr = workplace_address or {}
    parts = [
        addr.get("city"),
        addr.get("municipality"),
        addr.get("region"),
        addr.get("country"),
    ]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return ", ".join(seen)


def _normalize_hit(hit: dict[str, Any], *, full_description: bool = False) -> dict[str, Any]:
    """Reduce a JobSearch ad object to the fields the agent actually needs."""
    description = (hit.get("description") or {}).get("text") or ""
    if not full_description and len(description) > _DESCRIPTION_LIMIT:
        description = description[:_DESCRIPTION_LIMIT] + "\n…(truncated; use get_job_ad for full text)"

    normalized: dict[str, Any] = {
        "id": hit.get("id"),
        "headline": hit.get("headline"),
        "employer": (hit.get("employer") or {}).get("name"),
        "location": _location_str(hit.get("workplace_address")),
        "employment_type": (hit.get("employment_type") or {}).get("label"),
        "working_hours_type": (hit.get("working_hours_type") or {}).get("label"),
        "occupation": (hit.get("occupation") or {}).get("label"),
        "deadline": hit.get("application_deadline"),
        "url": hit.get("webpage_url"),
        "description": description,
    }

    if full_description:
        # The structured requirement blocks are the most reliable signal for the
        # qualification check, so surface them explicitly when fetching one ad.
        must_have = hit.get("must_have") or {}
        nice_to_have = hit.get("nice_to_have") or {}
        normalized["must_have"] = must_have
        normalized["nice_to_have"] = nice_to_have

    return normalized


def search_jobs(
    query: str,
    location: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Search Platsbanken (JobTech JobSearch API) by freetext.

    ``location`` is appended to the freetext query — JobSearch's freetext handles
    place names well, which avoids needing municipality/region taxonomy codes.
    Returns a dict with ``query``, ``total`` (matches available), ``count``
    (returned here), ``jobs`` (normalized list), and ``errors``.
    """
    freetext = " ".join(p for p in (query.strip(), location.strip()) if p)
    limit = max(1, min(limit, 100))  # API caps page size at 100
    result: dict[str, Any] = {
        "query": freetext,
        "total": 0,
        "count": 0,
        "jobs": [],
        "errors": [],
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.get(
                f"{_BASE_URL}/search",
                params={"q": freetext, "limit": limit, "offset": max(0, offset)},
                headers=_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 — degrade gracefully like research.py
        result["errors"].append(f"JobSearch /search: {exc}")
        return result

    result["total"] = (data.get("total") or {}).get("value", 0)
    hits = data.get("hits") or []
    result["jobs"] = [_normalize_hit(h) for h in hits]
    result["count"] = len(result["jobs"])
    return result


def fetch_ad(ad_id: str) -> dict[str, Any]:
    """Fetch one full Platsbanken ad by id (``GET /ad/{id}``).

    Returns the normalized ad with the FULL (untrimmed) description and the
    structured ``must_have``/``nice_to_have`` requirement blocks, or an ``error``
    key if the fetch failed.
    """
    if not ad_id or not str(ad_id).strip():
        return {"error": "ad_id is required"}

    try:
        with httpx.Client(follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.get(
                f"{_BASE_URL}/ad/{ad_id}",
                headers=_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"id": ad_id, "error": f"JobSearch /ad: {exc}"}

    return _normalize_hit(data, full_description=True)
