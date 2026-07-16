"""Deterministic (no-LLM) resume checks.

Anything mechanically verifiable belongs here rather than in a sub-agent: it is
free, infallible, and client-agnostic. Covers forbidden characters (dashes),
PDF page count, and a basic ATS text-extraction sanity check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Dash characters that either crash Tectonic (no glyph in cmr/cfr-lm) or violate
# the house style (no em-dashes). U+2014 em, U+2015 horizontal bar, U+2012 figure
# dash, U+2E3A/B two-and three-em dashes. En dash (U+2013) is allowed as a range
# separator and is handled by the renderer, so it is intentionally NOT here.
FORBIDDEN_DASHES = {
    "—": "em dash (U+2014)",
    "―": "horizontal bar (U+2015)",
    "‒": "figure dash (U+2012)",
    "⸺": "two-em dash (U+2E3A)",
    "⸻": "three-em dash (U+2E3B)",
}


def find_forbidden_dashes(value: Any) -> list[str]:
    """Recursively scan a content value (dict/list/str) for forbidden dashes.

    Returns a list of human-readable findings, e.g.
    ["em dash (U+2014) in: 'Led team—shipped fast'"]. Empty list == clean.
    """
    findings: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for ch, label in FORBIDDEN_DASHES.items():
                if ch in node:
                    snippet = node.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    findings.append(f"{label} in: {snippet!r}")
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(value)
    return findings


def pdf_page_count(pdf_path: Path) -> int | None:
    """Number of pages in a PDF, or None if it can't be determined (e.g. pypdf
    not installed or file unreadable)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return None


def pdf_text(pdf_path: Path) -> str | None:
    """Extract all text from a PDF, or None if unavailable."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def page_check(
    pdf_path: Path, max_pages: int, target_pages: int | None = None
) -> dict[str, Any]:
    """Compare a PDF's page count against the configured page window.

    `max_pages` is a hard ceiling; optional `target_pages` is a floor. Both
    failures are SELECTION problems, not layout problems — overflow means cut an
    entry, underfill means add the next-best one. Say so, because the tempting
    fix (margins/font) is the wrong one in both directions.
    """
    pages = pdf_page_count(pdf_path)
    result: dict[str, Any] = {"ok": True, "pages": pages, "max_pages": max_pages}
    if target_pages is not None:
        result["target_pages"] = target_pages
    if pages is None:
        result["note"] = "page count unavailable (pypdf missing?) — skipped"
        return result
    if pages > max_pages:
        result["ok"] = False
        result["message"] = (
            f"Resume is {pages} pages but the limit is {max_pages}. Fix by "
            "CUTTING the lowest-relevance included entry or trimming highlights "
            "(consult the relevance review), NOT by shrinking margins/font "
            "(recruiters notice that)."
        )
    elif target_pages is not None and pages < target_pages:
        result["ok"] = False
        result["message"] = (
            f"Resume is {pages} pages but the target is {target_pages}. There is "
            "room being wasted: ADD the next-highest-relevance entries from the "
            "relevance review, or expand the highlights of the entries already "
            "included. Do NOT pad with fluff, filler bullets, or unsupported "
            "claims, and do NOT stretch margins/font — if the catalogue "
            "genuinely has nothing more worth adding, say so rather than "
            "inventing material."
        )
    return result


def _item_label(item: dict[str, Any]) -> str:
    return (
        item.get("title")
        or item.get("name")
        or item.get("degree")
        or item.get("company")
        or ""
    )


def coverage_check(
    content: dict[str, Any], personal_info: dict[str, Any], sections: list[str]
) -> dict[str, Any]:
    """Every catalogue `id` in each of `sections` must appear in the content.

    For ui_guidelines.selection.require_all_from (and the older
    include_all_experience): some markets (and some candidates) expect a
    complete history, where silently dropping an entry reads as a gap. Older
    entries may be compressed to a heading with 0-1 bullets — but never dropped.

    `sections` is a list of catalogue keys rather than a hardcoded "experience"
    so a config can demand full coverage of, say, education or voluntary_work
    too.
    """
    per_section: dict[str, Any] = {}
    missing_any = False
    messages: list[str] = []

    for section in sections:
        catalogue = [
            it for it in (personal_info.get(section) or []) if isinstance(it, dict)
        ]
        included = {
            it.get("id")
            for it in (content.get(section) or [])
            if isinstance(it, dict)
        }
        missing = [
            {"id": it.get("id", ""), "label": _item_label(it)}
            for it in catalogue
            if it.get("id") and it.get("id") not in included
        ]
        per_section[section] = {
            "ok": not missing,
            "catalogue_entries": len(catalogue),
            "included_entries": len(included),
        }
        if missing:
            missing_any = True
            per_section[section]["missing_ids"] = [m["id"] for m in missing]
            named = ", ".join(
                m["id"] + (f" ({m['label']})" if m["label"] else "") for m in missing
            )
            messages.append(f"{section}: {named}")

    result: dict[str, Any] = {"ok": not missing_any, "sections": per_section}
    if missing_any:
        result["missing_ids"] = [
            i for s in per_section.values() for i in s.get("missing_ids", [])
        ]
        result["message"] = (
            "ui_guidelines.selection requires FULL coverage of "
            + ", ".join(sections)
            + ", so every entry in the catalogue must appear on the resume. "
            "Missing: "
            + "; ".join(messages)
            + ". Add them. An older or less relevant entry may be compressed to "
            "its heading with 0-1 highlights, but it must not be dropped."
        )
    return result


def find_banned_phrases(value: Any, phrases: list[str]) -> list[str]:
    """Recursively scan content for configured banned phrases (case-insensitive).

    Returns human-readable findings naming the phrase AND its location, e.g.
    ["'gedigen kompetens' at experience[0].highlights[1].text: '...'"]. Empty
    list (and an empty `phrases`) == clean.
    """
    wanted = [p for p in (phrases or []) if isinstance(p, str) and p.strip()]
    if not wanted:
        return []
    findings: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, str):
            lowered = node.lower()
            for phrase in wanted:
                if phrase.lower() in lowered:
                    snippet = node.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    where = path or "(root)"
                    findings.append(f"{phrase!r} at {where}: {snippet!r}")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(value, "")
    return findings


def ats_check(pdf_path: Path, content: dict[str, Any]) -> dict[str, Any]:
    """Cheap ATS parseability sanity check: does the extracted text contain the
    candidate's name and contact email, in extractable order? Multicolumn LaTeX
    layouts sometimes scramble this."""
    text = pdf_text(pdf_path)
    if text is None:
        return {"ok": True, "note": "text extraction unavailable — skipped"}
    flat = " ".join(text.split()).lower()
    missing: list[str] = []
    name = str(content.get("name", "")).strip()
    if name and name.lower() not in flat:
        missing.append(f"name ({name!r})")
    contact = content.get("contact") or {}
    email = str(contact.get("email", "")).strip()
    if email and email.lower() not in flat:
        missing.append(f"email ({email!r})")
    ok = not missing
    result: dict[str, Any] = {"ok": ok}
    if not ok:
        result["missing_from_extracted_text"] = missing
        result["message"] = (
            "These fields didn't survive text extraction — an ATS may not parse "
            "them. Check the header isn't in a construct that scrambles reading "
            "order."
        )
    return result
