"""Server-side workflow state for the mandatory tailoring loop.

The tailoring loop (rank -> generate -> critique -> revise) used to be enforced
only by prose in CLAUDE.md and by Claude Code hooks. Prose is advisory and hooks
only run in Claude Code (Cursor/Desktop/ChatGPT ignore them), so any client could
skip the recruiter reviews. This module records which review gates have been
satisfied for a given (company, job_description) so generate_resume and
finalize_resume can enforce the loop in code — the server holds the artifact, so
the main agent can't merely claim a review happened.

State lives in output/.state/<job_key>.json (gitignored via output/).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from resume_mcp_server import paths

RELEVANCE_REVIEW = "relevance_review"


def job_key(company: str, job_description: str) -> str:
    """Stable short key for a (company, job_description) pair, whitespace- and
    case-insensitive so trivial reformatting doesn't invalidate a review."""
    norm_company = " ".join(company.split()).lower()
    norm_jd = " ".join(job_description.split()).lower()
    digest = hashlib.sha256(f"{norm_company}\x00{norm_jd}".encode())
    return digest.hexdigest()[:16]


def _state_dir() -> Path:
    d = paths.OUTPUT_DIR / ".state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(key: str) -> Path:
    return _state_dir() / f"{key}.json"


def load(company: str, job_description: str) -> dict[str, Any]:
    path = _state_path(job_key(company, job_description))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save(key: str, state: dict[str, Any]) -> None:
    _state_path(key).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_relevance_review(
    company: str, job_description: str, results: str
) -> dict[str, Any]:
    key = job_key(company, job_description)
    state = load(company, job_description)
    state["company"] = company
    state["job_key"] = key
    state[RELEVANCE_REVIEW] = {"submitted_at": _now(), "results": results}
    _save(key, state)
    return state


def has_relevance_review(company: str, job_description: str) -> bool:
    return RELEVANCE_REVIEW in load(company, job_description)


def record_critique(
    name: str, company: str, job_description: str, findings: str
) -> dict[str, Any]:
    key = job_key(company, job_description)
    state = load(company, job_description)
    state.setdefault("company", company)
    state["job_key"] = key
    critiques = state.setdefault("critiques", {})
    critiques[name] = {"submitted_at": _now(), "findings": findings}
    _save(key, state)
    return state


def has_critique(name: str, company: str, job_description: str) -> bool:
    return name in load(company, job_description).get("critiques", {})


def record_generation(
    name: str, company: str, job_description: str, results: dict[str, Any]
) -> dict[str, Any]:
    """Record the deterministic checks from the latest generate_resume for `name`.

    finalize_resume receives only a name, and the rendered .tex carries no entry
    ids — so a content-level check like experience coverage cannot be recomputed
    at finalize time. Recording it here lets the finalize gate see the last
    known result instead of trusting the agent's word.
    """
    key = job_key(company, job_description)
    state = load(company, job_description)
    state.setdefault("company", company)
    state["job_key"] = key
    generations = state.setdefault("generations", {})
    generations[name] = {"generated_at": _now(), **results}
    _save(key, state)
    return state


def last_generation(
    name: str, company: str, job_description: str
) -> dict[str, Any] | None:
    """The recorded checks from the most recent generate_resume for `name`, or
    None if there is no record (e.g. a resume generated before this existed)."""
    return load(company, job_description).get("generations", {}).get(name)
