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


def page_check(pdf_path: Path, max_pages: int) -> dict[str, Any]:
    """Compare a PDF's page count against max_pages. Overflow is a SELECTION
    problem (cut an entry / trim bullets), not a layout problem — say so."""
    pages = pdf_page_count(pdf_path)
    if pages is None:
        return {"ok": True, "pages": None, "max_pages": max_pages,
                "note": "page count unavailable (pypdf missing?) — skipped"}
    ok = pages <= max_pages
    result: dict[str, Any] = {"ok": ok, "pages": pages, "max_pages": max_pages}
    if not ok:
        result["message"] = (
            f"Resume is {pages} pages but the limit is {max_pages}. Fix by "
            "CUTTING the lowest-relevance included entry or trimming highlights "
            "(consult the relevance review), NOT by shrinking margins/font — "
            "recruiters notice that."
        )
    return result


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
