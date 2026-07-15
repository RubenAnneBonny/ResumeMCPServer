from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from resume_mcp_server import checks, paths
from resume_mcp_server.critic import (
    build_interview_prompt,
    build_proofread_prompt,
    build_qualification_check_prompt,
    build_red_flag_prompt,
    build_relevance_review_prompt,
    build_resume_critique_prompt,
    build_skim_prompt,
)
from resume_mcp_server import state
from resume_mcp_server.jobs import fetch_ad, search_jobs
from resume_mcp_server.latex import compile_tex, tectonic_available
from resume_mcp_server.render import render_resume
from resume_mcp_server.schemas import (
    Certification,
    Competition,
    Education,
    Experience,
    PersonalInfo,
    Project,
    UIGuidelines,
    validate_personal_info,
    validate_ui_guidelines,
)

# Sections whose items have a known schema, used to show the interviewer the
# exact shape to fill. Extra/free-form sections (schema is lax) fall back to
# "mirror the sibling entries".
_SECTION_ITEM_MODELS = {
    "experience": Experience,
    "education": Education,
    "projects": Project,
    "competitions": Competition,
    "certifications": Certification,
}

mcp = FastMCP("resume")

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _bootstrap_personal_info() -> None:
    paths.ensure_dirs()
    if paths.PERSONAL_INFO_PATH.exists():
        return
    if paths.PERSONAL_INFO_EXAMPLE_PATH.exists():
        shutil.copy2(paths.PERSONAL_INFO_EXAMPLE_PATH, paths.PERSONAL_INFO_PATH)


def _bootstrap_ui_guidelines() -> None:
    paths.ensure_dirs()
    if paths.UI_GUIDELINES_PATH.exists():
        return
    if paths.UI_GUIDELINES_EXAMPLE_PATH.exists():
        shutil.copy2(paths.UI_GUIDELINES_EXAMPLE_PATH, paths.UI_GUIDELINES_PATH)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# Fraction of existing entries a single write may drop before it is refused
# without force=True. Guards against a confused agent wiping the catalogue.
_MAX_ENTRY_LOSS_FRACTION = 0.30


def _backup_json(path: Path) -> Path | None:
    """Copy `path` to data/backups/<stem>.<timestamp>.json before it is
    overwritten. Returns the backup path, or None if there was nothing to copy.
    """
    if not path.exists():
        return None
    backups_dir = path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    dest = backups_dir / f"{path.stem}.{ts}.json"
    shutil.copy2(path, dest)
    return dest


def _list_sections(personal_info: dict[str, Any]) -> list[str]:
    """Top-level keys whose value is a list — the catalogue's entry sections."""
    return [k for k, v in personal_info.items() if isinstance(v, list)]


def _max_pages(ui: dict[str, Any]) -> int:
    """Page limit from ui_guidelines.page.max_pages (default 1). One page is the
    right default for students and Anglo/quant firms; a Swedish-market config
    can raise it to 2."""
    page = ui.get("page") if isinstance(ui, dict) else None
    if isinstance(page, dict):
        try:
            return max(1, int(page.get("max_pages", 1)))
        except (TypeError, ValueError):
            return 1
    return 1


def _count_entries(personal_info: dict[str, Any]) -> int:
    """Total number of list-section entries across the catalogue."""
    return sum(len(v) for v in personal_info.values() if isinstance(v, list))


def _guard_destructive_write(
    old: dict[str, Any], new: dict[str, Any], force: bool
) -> None:
    """Refuse a write that drops more than _MAX_ENTRY_LOSS_FRACTION of the
    existing entries unless force=True. Raises ValueError with per-section
    deltas so the caller can see exactly what would be lost.
    """
    old_n = _count_entries(old)
    if old_n == 0 or force:
        return
    new_n = _count_entries(new)
    if new_n >= old_n * (1 - _MAX_ENTRY_LOSS_FRACTION):
        return
    deltas = []
    for section in sorted(set(_list_sections(old)) | set(_list_sections(new))):
        before = len(old.get(section, []) or [])
        after = len(new.get(section, []) or [])
        if after < before:
            deltas.append(f"  {section}: {before} -> {after}")
    detail = "\n".join(deltas) or "  (entries removed across sections)"
    raise ValueError(
        f"Refusing write: it would drop {old_n - new_n} of {old_n} catalogue "
        f"entries (> {int(_MAX_ENTRY_LOSS_FRACTION * 100)}%), which looks "
        f"accidental.\n{detail}\n"
        "If this is intentional, call again with force=True. A timestamped "
        "backup of the current catalogue is always written to data/backups/ "
        "before any successful write."
    )


@mcp.tool()
def get_personal_info() -> dict[str, Any]:
    """Return the full personal-info catalogue (data/personal_info.json).

    This is the source-of-truth content store: every job, education entry, project,
    competition, and certification, with long-form narratives and many highlights
    each. It is intentionally larger than any single resume. When tailoring a resume
    to a job description, read this in full, then pick the most relevant subset of
    items per section AND the most relevant 2-4 highlights per included item.
    """
    _bootstrap_personal_info()
    return _read_json(paths.PERSONAL_INFO_PATH)


def _entry_label(item: dict[str, Any]) -> str:
    return (
        item.get("title")
        or item.get("name")
        or item.get("degree")
        or item.get("id")
        or "(untitled)"
    )


def _entry_oneliner(item: dict[str, Any]) -> str:
    narrative = (item.get("narrative") or "").strip()
    if narrative:
        first = re.split(r"(?<=[.!?])\s", narrative)[0]
        return first[:160]
    highlights = item.get("highlights") or []
    if highlights and isinstance(highlights[0], dict):
        return (highlights[0].get("text") or "")[:160]
    return ""


@mcp.tool()
def get_catalogue_index() -> dict[str, Any]:
    """Return a COMPACT index of the catalogue: ids, labels, one-line summaries.

    Use this instead of get_personal_info for the main tailoring flow — it is a
    fraction of the tokens and enough to decide what to pull in. Fetch full
    detail for the entries you actually want with get_entries(ids). (The fresh
    sub-agents that run the recruiter reviews still see the whole catalogue.)

    Returns the candidate's name/title/summary plus, per list section, a list of
    {id, label, summary} rows.
    """
    _bootstrap_personal_info()
    pi = _read_json(paths.PERSONAL_INFO_PATH)
    sections: dict[str, Any] = {}
    for section in _list_sections(pi):
        rows = [
            {
                "id": it.get("id", ""),
                "label": _entry_label(it),
                "summary": _entry_oneliner(it),
            }
            for it in pi[section]
            if isinstance(it, dict)
        ]
        sections[section] = rows
    return {
        "name": pi.get("name", ""),
        "title": pi.get("title", ""),
        "summary": pi.get("summary", ""),
        "sections": sections,
    }


@mcp.tool()
def get_entries(ids: list[str]) -> dict[str, Any]:
    """Return the FULL entries for the given ids (companion to get_catalogue_index).

    Look up ids across every list section and return the matching entries with
    all their fields, so you can pull only the entries you decided to include
    rather than loading the whole catalogue.

    Args:
        ids: entry ids from get_catalogue_index, e.g. ["alpha", "imo-2024"].

    Returns {"entries": {section: [entry, ...]}, "missing": [ids not found]}.
    """
    _bootstrap_personal_info()
    pi = _read_json(paths.PERSONAL_INFO_PATH)
    wanted = set(ids)
    found: dict[str, list[Any]] = {}
    seen: set[str] = set()
    for section in _list_sections(pi):
        matches = [
            it
            for it in pi[section]
            if isinstance(it, dict) and it.get("id") in wanted
        ]
        if matches:
            found[section] = matches
            seen.update(it.get("id") for it in matches)
    return {"entries": found, "missing": sorted(wanted - seen)}


@mcp.tool()
def get_ui_guidelines() -> dict[str, Any]:
    """Return the UI / style guidelines (data/ui_guidelines.json).

    These are knobs the LaTeX template reads: fonts, accent color, margins,
    section heading style, spacing, voice (person/tense). Pass these into
    generate_resume so the rendered PDF matches the configured style.
    """
    _bootstrap_ui_guidelines()
    return _read_json(paths.UI_GUIDELINES_PATH)


@mcp.tool()
def update_personal_info(
    content: dict[str, Any], force: bool = False
) -> dict[str, Any]:
    """Replace the WHOLE personal-info catalogue with `content` (bulk write).

    DISCOURAGED for edits: prefer the granular add_entry / patch_entry /
    delete_entry tools, which make small, auditable diffs and cannot silently
    drop an entry. Use this only for a full import/restore.

    The file is validated, a timestamped backup of the current catalogue is
    written to data/backups/ first, then the new content is written atomically
    (temp + rename). A write that would drop more than
    ~30% of existing entries is refused unless force=True.
    """
    _bootstrap_personal_info()
    validated = validate_personal_info(content)
    old = (
        _read_json(paths.PERSONAL_INFO_PATH)
        if paths.PERSONAL_INFO_PATH.exists()
        else {}
    )
    _guard_destructive_write(old, validated, force)
    _backup_json(paths.PERSONAL_INFO_PATH)
    _atomic_write_json(paths.PERSONAL_INFO_PATH, validated)
    return validated


@mcp.tool()
def update_ui_guidelines(content: dict[str, Any]) -> dict[str, Any]:
    """Replace the UI guidelines with `content` (whole-file write).

    Same pattern as update_personal_info. Validated and atomically written.
    """
    validated = validate_ui_guidelines(content)
    _atomic_write_json(paths.UI_GUIDELINES_PATH, validated)
    return validated


def _get_list_section(personal_info: dict[str, Any], section: str) -> list[Any]:
    items = personal_info.get(section)
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError(
            f"section {section!r} is not a list section. Catalogue list sections "
            f"are: {', '.join(_list_sections(personal_info)) or '(none yet)'}."
        )
    return items


def _find_entry_index(items: list[Any], entry_id: str) -> int:
    for i, it in enumerate(items):
        if isinstance(it, dict) and it.get("id") == entry_id:
            return i
    return -1


def _derive_id(section: str, item: dict[str, Any], existing: list[Any]) -> str:
    basis = (
        item.get("name")
        or item.get("title")
        or item.get("degree")
        or section
    )
    slug = re.sub(r"[^a-z0-9]+", "-", str(basis).lower()).strip("-")[:40] or section
    existing_ids = {
        it.get("id") for it in existing if isinstance(it, dict) and it.get("id")
    }
    candidate, n = slug, 2
    while candidate in existing_ids:
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


def _write_personal_info(personal_info: dict[str, Any]) -> dict[str, Any]:
    validated = validate_personal_info(personal_info)
    _backup_json(paths.PERSONAL_INFO_PATH)
    _atomic_write_json(paths.PERSONAL_INFO_PATH, validated)
    return validated


@mcp.tool()
def add_entry(section: str, item: dict[str, Any]) -> dict[str, Any]:
    """Append ONE entry to a catalogue list section (small, auditable write).

    Preferred over update_personal_info for adding content: it touches only the
    one entry, so no other entry can be dropped by mistake. The whole catalogue
    is re-validated, backed up to data/backups/, and written atomically.

    If `item` has no "id", one is derived from its name/title/degree so you can
    patch_entry / delete_entry it later.

    Args:
        section: list section, e.g. "experience", "projects", "competitions".
        item: the entry dict (shape mirrors its section; see get_resume_schema).
    """
    _bootstrap_personal_info()
    pi = _read_json(paths.PERSONAL_INFO_PATH)
    items = list(_get_list_section(pi, section))
    if isinstance(item, dict) and not item.get("id"):
        item = {**item, "id": _derive_id(section, item, items)}
    items.append(item)
    pi[section] = items
    validated = _write_personal_info(pi)
    return {
        "section": section,
        "added": item,
        "count": len(validated.get(section, [])),
    }


@mcp.tool()
def patch_entry(
    section: str, entry_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    """Shallow-merge `changes` into ONE existing entry, found by its "id".

    Only the named keys are updated; everything else on the entry is preserved.
    The catalogue is re-validated, backed up, and written atomically.

    Args:
        section: the list section the entry lives in, e.g. "projects".
        entry_id: the entry's "id".
        changes: keys to overwrite, e.g. {"title": "New title"}.
    """
    _bootstrap_personal_info()
    pi = _read_json(paths.PERSONAL_INFO_PATH)
    items = _get_list_section(pi, section)
    idx = _find_entry_index(items, entry_id)
    if idx < 0:
        raise ValueError(
            f"no entry with id={entry_id!r} in section {section!r}. "
            "Use get_personal_info or get_catalogue_index to see valid ids."
        )
    items[idx] = {**items[idx], **changes}
    validated = _write_personal_info(pi)
    return {"section": section, "patched": items[idx]}


@mcp.tool()
def delete_entry(section: str, entry_id: str) -> dict[str, Any]:
    """Remove ONE entry, found by its "id", from a catalogue list section.

    Explicit single-entry delete: it backs up to data/backups/ first and writes
    atomically. (Unlike update_personal_info, it is not subject to the >30%
    destructive-write guard, because deleting exactly one entry is the intent.)

    Args:
        section: the list section, e.g. "competitions".
        entry_id: the "id" of the entry to remove.
    """
    _bootstrap_personal_info()
    pi = _read_json(paths.PERSONAL_INFO_PATH)
    items = _get_list_section(pi, section)
    idx = _find_entry_index(items, entry_id)
    if idx < 0:
        raise ValueError(
            f"no entry with id={entry_id!r} in section {section!r}. "
            "Use get_personal_info or get_catalogue_index to see valid ids."
        )
    removed = items.pop(idx)
    validated = _write_personal_info(pi)
    return {
        "section": section,
        "deleted": removed,
        "count": len(validated.get(section, [])),
    }


@mcp.tool()
def get_resume_schema() -> dict[str, Any]:
    """Return the expected shape of the `content` argument for generate_resume.

    Returns a dict with two keys:
      - "schema": JSON Schema describing the structured content the template
        consumes (header info, summary, experience, education, projects,
        competitions, skills, certifications).
      - "guidance": notes on tailoring — how to pick items per section, how to
        rewrite bullets to match ui_guidelines.voice, and the convention that
        `narrative` fields in personal_info are agent context only and must
        never be copied verbatim into the resume.

    Use this before generate_resume so the rendered LaTeX has every slot it
    expects.
    """
    schema = PersonalInfo.model_json_schema()
    guidance = (
        "MANDATORY critical tailoring loop — do NOT skip the recruiter reviews. "
        "They exist so the resume is sharpened by an adversarial recruiter, not "
        "just rubber-stamped:\n"
        "0) RESEARCH the company yourself with the WebSearch/WebFetch tools: its "
        "mission, domain, and what it values in this role. For a small or obscure "
        "employer, fetch its own site and read the job ad closely. Use the themes "
        "to steer the summary and which highlights you emphasise.\n"
        "1) RANK (before selecting): call get_relevance_review_prompt(company, "
        "job_description) and run the returned prompt in a FRESH sub-agent (e.g. "
        "the Task tool, no inherited context). It scores every catalogue entry "
        "0-5 for this job. Cut the low-scoring ones.\n"
        "2) Survey the catalogue with get_catalogue_index() (compact: ids, "
        "labels, one-liners), then pull full detail for the entries you want "
        "with get_entries(ids). Reserve get_personal_info() for when you truly "
        "need everything. The index is the catalogue, not the resume.\n"
        "3) Using the rankings, pick the items most relevant to the JD per section "
        "(experience, education, projects, competitions, certifications). The agent "
        "decides counts — typical output is e.g. 2 of 3 jobs, 4 of 4 education "
        "entries, 5 of 8 projects, 4 of 6 competitions.\n"
        "4) For each selected item, pick the 2-4 highlights most relevant to the "
        "JD and rewrite them tightly. Obey ui_guidelines.voice: no personal "
        "pronouns, past tense, lead with a strong action verb, and NEVER use "
        "em-dashes (—) — use commas, colons, or parentheses instead.\n"
        "5) `narrative` fields in personal_info are background context for you. "
        "They must never be copied verbatim into the resume.\n"
        "6) Pass the curated, rewritten dict to generate_resume(name, content). "
        "The server merges it with current ui_guidelines and renders LaTeX.\n"
        "7) CRITIQUE (after generating): call get_resume_critique_prompt(name, "
        "company, job_description) and run it in a FRESH sub-agent. It sees the "
        "full catalogue AND the rendered resume, so it flags UNSUPPORTED claims, "
        "valuable entries you wrongly OMITTED (by id), filler to CUT, what is "
        "working, the top-5 truthful missing keywords, and per-item feedback.\n"
        "8) REVISE: remove/rephrase every unsupported claim, ADD every wrongly- "
        "omitted entry, CUT the flagged filler, fix the keywords and per-item "
        "issues, and call generate_resume again. Repeat 7-8 until 'Unsupported "
        "claims' and 'Wrongly omitted' are both empty and 'Cut or trim' is clean."
    )
    return {"schema": schema, "guidance": guidance}


@mcp.tool()
def get_relevance_review_prompt(
    company: str,
    job_description: str,
) -> dict[str, Any]:
    """Build the PRE-generation recruiter relevance-ranking prompt.

    Returns a complete, self-contained prompt that embeds the full personal-info
    catalogue and a skeptical-recruiter persona for `company`/`job_description`.
    Hand the prompt to a FRESH sub-agent (e.g. the Task tool, with no inherited
    context) so the ranking is unbiased. The sub-agent scores every catalogue
    entry 0-5 for this job; use those scores to decide what to include before
    calling generate_resume. The server does not call an LLM — the sub-agent
    runs on your own client/subscription.

    Args:
        company: the hiring company, e.g. "Citadel Securities".
        job_description: the job description text to rank entries against.

    Returns a dict with "prompt" (give this verbatim to the sub-agent) and
    "how_to_use".
    """
    _bootstrap_personal_info()
    personal_info = _read_json(paths.PERSONAL_INFO_PATH)
    return {
        "prompt": build_relevance_review_prompt(
            company, job_description, personal_info
        ),
        "how_to_use": (
            "Launch a fresh sub-agent (e.g. the Task tool, general-purpose, no "
            "inherited context) with this exact prompt. Then call "
            "submit_relevance_review(company, job_description, results) with the "
            "sub-agent's output — generate_resume is BLOCKED for this job until "
            "you do. Use the returned 0-5 rankings to choose which entries and "
            "highlights to include (drop the low-scoring ones), then build "
            "content for generate_resume."
        ),
    }


@mcp.tool()
def submit_relevance_review(
    company: str,
    job_description: str,
    results: str,
) -> dict[str, Any]:
    """Register that the PRE-generation relevance review actually ran.

    Call this after running get_relevance_review_prompt's prompt in a fresh
    sub-agent, passing that sub-agent's verbatim output as `results`. This
    UNLOCKS generate_resume for this (company, job_description): the gate exists
    so the recruiter ranking can't be silently skipped, and so the server holds
    the artifact rather than trusting a claim that it happened.

    Args:
        company: same company string you will pass to generate_resume.
        job_description: same JD text you will pass to generate_resume.
        results: the ranking sub-agent's output (0-5 scores + MUST_INCLUDE line).
    """
    state.record_relevance_review(company, job_description, results)
    return {
        "recorded": True,
        "job_key": state.job_key(company, job_description),
        "next": "generate_resume is now unlocked for this job.",
    }


def _safe_name(name: str) -> str:
    if not name or not _NAME_RE.match(name):
        raise ValueError(
            "name must be non-empty and contain only A-Z, a-z, 0-9, '_' or '-'"
        )
    return name


@mcp.tool()
def generate_resume(
    name: str,
    content: dict[str, Any],
    company: str,
    job_description: str,
    compile_pdf: bool = True,
) -> dict[str, Any]:
    """Render a tailored resume to LaTeX and (by default) compile to PDF.

    GATED: a relevance review must be registered for this (company,
    job_description) first — call get_relevance_review_prompt, run it in a fresh
    sub-agent, then submit_relevance_review. This makes the mandatory ranking
    step unbypassable in code (not just via prose/hooks). After generating, run
    the critique (get_resume_critique_prompt -> submit_resume_critique) and then
    finalize_resume.

    Args:
        name: filename stem for output, e.g. "acme_swe_2026". Must match
            [A-Za-z0-9_-]+.
        content: the curated structured dict — same shape as personal_info,
            but trimmed and rewritten for the target JD. See get_resume_schema.
        company: hiring company, e.g. "Citadel Securities". Must match the
            company passed to submit_relevance_review.
        job_description: the JD text. Must match the one passed to
            submit_relevance_review.
        compile_pdf: if True (default), runs Tectonic to produce a PDF. If
            False, only the .tex file is written, useful for iterating on
            content without paying the compile cost.

    Returns paths to the generated .tex and .pdf (when compiled), plus any
    Tectonic stdout/stderr on failure.
    """
    safe = _safe_name(name)
    if not state.has_relevance_review(company, job_description):
        raise ValueError(
            "generate_resume is blocked: no relevance review registered for "
            f"company={company!r}. Run get_relevance_review_prompt in a fresh "
            "sub-agent, then call submit_relevance_review(company, "
            "job_description, results) with the SAME company/job_description "
            "strings, then retry."
        )
    paths.ensure_dirs()
    _bootstrap_ui_guidelines()
    ui = _read_json(paths.UI_GUIDELINES_PATH)

    # Validate + fill defaults BEFORE rendering. Without this, a content dict
    # that omits a top-level key (e.g. no "title") raises a cryptic Jinja
    # UndefinedError under StrictUndefined; validation yields every top-level
    # field with a sane default and a readable pydantic error on real problems.
    content = validate_personal_info(content)

    # Reject em-dashes (and friends) server-side, so the house style holds for
    # every client — not just Claude Code, whose PreToolUse hook is one more
    # layer. The renderer would silently convert them otherwise.
    dash_findings = checks.find_forbidden_dashes(content)
    if dash_findings:
        raise ValueError(
            "content contains forbidden dash characters (use commas, colons, or "
            "parentheses instead):\n- " + "\n- ".join(dash_findings)
        )

    tex_source = render_resume("resume.tex.j2", content, ui)
    tex_path = paths.OUTPUT_DIR / f"{safe}.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    result: dict[str, Any] = {
        "name": safe,
        "tex_path": str(tex_path),
        "compiled": False,
        "next_step": (
            "Critique this resume: run get_resume_critique_prompt in a fresh "
            "sub-agent, call submit_resume_critique with its findings, revise, "
            "then finalize_resume."
        ),
    }

    if not compile_pdf:
        return result

    cr = compile_tex(tex_path)
    result["compiled"] = cr.ok
    if cr.ok and cr.pdf_path is not None:
        result["pdf_path"] = str(cr.pdf_path)
        # Deterministic post-compile checks. These surface problems in the
        # result (they don't raise) so the agent can iterate; finalize_resume
        # is the hard gate that refuses an over-length resume.
        result["page_check"] = checks.page_check(cr.pdf_path, _max_pages(ui))
        result["ats_check"] = checks.ats_check(cr.pdf_path, content)
    if cr.error:
        result["error"] = cr.error
    if cr.stdout:
        result["stdout"] = cr.stdout[-4000:]
    if cr.stderr:
        result["stderr"] = cr.stderr[-4000:]
    return result


@mcp.tool()
def list_resumes() -> list[dict[str, Any]]:
    """List generated resumes in output/. Returns name, mtime, has_pdf, paths."""
    paths.ensure_dirs()
    by_stem: dict[str, dict[str, Any]] = {}
    for path in paths.OUTPUT_DIR.iterdir():
        if not path.is_file():
            continue
        if path.suffix not in (".tex", ".pdf"):
            continue
        entry = by_stem.setdefault(
            path.stem,
            {"name": path.stem, "tex_path": None, "pdf_path": None, "mtime": 0.0},
        )
        if path.suffix == ".tex":
            entry["tex_path"] = str(path)
        else:
            entry["pdf_path"] = str(path)
        entry["mtime"] = max(entry["mtime"], path.stat().st_mtime)

    out: list[dict[str, Any]] = []
    for entry in by_stem.values():
        entry["has_pdf"] = entry["pdf_path"] is not None
        entry["modified_at"] = datetime.fromtimestamp(
            entry["mtime"], tz=timezone.utc
        ).isoformat()
        out.append(entry)
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return out


@mcp.tool()
def check_environment() -> dict[str, Any]:
    """Diagnostics: are required files present, is tectonic installed, etc.

    Useful for first-run troubleshooting. Returns a dict of booleans + paths.
    """
    return {
        "repo_root": str(paths.REPO_ROOT),
        "personal_info_exists": paths.PERSONAL_INFO_PATH.exists(),
        "personal_info_example_exists": paths.PERSONAL_INFO_EXAMPLE_PATH.exists(),
        "ui_guidelines_exists": paths.UI_GUIDELINES_PATH.exists(),
        "template_exists": paths.RESUME_TEMPLATE_PATH.exists(),
        "output_dir_exists": paths.OUTPUT_DIR.exists(),
        "tectonic_available": tectonic_available(),
    }


@mcp.tool()
def compile_resume(name: str) -> dict[str, Any]:
    """Compile an existing .tex file in output/ to PDF using Tectonic.

    Use this when you already have a .tex file (from generate_resume with
    compile=False, or after manually editing the .tex) and want to
    (re)compile it without re-rendering the template from scratch.

    Args:
        name: filename stem of an existing .tex file in output/,
            e.g. "acme_swe_2026". Must match [A-Za-z0-9_-]+.

    Returns the same shape as generate_resume.
    """
    safe = _safe_name(name)
    tex_path = paths.OUTPUT_DIR / f"{safe}.tex"
    if not tex_path.exists():
        raise FileNotFoundError(
            f"No .tex file found for '{safe}' in {paths.OUTPUT_DIR}. "
            "Use list_resumes() to see available files."
        )

    cr = compile_tex(tex_path)
    result: dict[str, Any] = {
        "name": safe,
        "tex_path": str(tex_path),
        "compiled": cr.ok,
    }
    if cr.ok and cr.pdf_path is not None:
        result["pdf_path"] = str(cr.pdf_path)
    if cr.error:
        result["error"] = cr.error
    if cr.stdout:
        result["stdout"] = cr.stdout[-4000:]
    if cr.stderr:
        result["stderr"] = cr.stderr[-4000:]
    return result


@mcp.tool()
def get_resume_critique_prompt(
    name: str,
    company: str,
    job_description: str,
) -> dict[str, Any]:
    """Build the POST-generation recruiter critique prompt for a rendered resume.

    Reads the already-generated output/<name>.tex AND the full personal-info
    catalogue, and returns a complete, self-contained prompt embedding both plus
    a skeptical-recruiter persona for `company`/`job_description`. Hand it to a
    FRESH sub-agent (no inherited context). Because it sees the catalogue, the
    sub-agent flags valuable entries that were wrongly OMITTED from the resume
    (by id) — not just missing keywords and per-item good/bad feedback — so
    nothing strong gets silently dropped. Apply it and call generate_resume
    again. The server does not call an LLM — the sub-agent runs on your own
    client/subscription.

    Args:
        name: filename stem of an existing .tex file in output/, e.g.
            "acme_swe_2026". Must match [A-Za-z0-9_-]+.
        company: the hiring company, e.g. "Citadel Securities".
        job_description: the job description text to critique against.

    Returns a dict with "prompt" (give this verbatim to the sub-agent) and
    "how_to_use".
    """
    safe = _safe_name(name)
    tex_path = paths.OUTPUT_DIR / f"{safe}.tex"
    if not tex_path.exists():
        raise FileNotFoundError(
            f"No .tex file found for '{safe}' in {paths.OUTPUT_DIR}. "
            "Generate it first, or use list_resumes() to see available files."
        )
    tex_source = tex_path.read_text(encoding="utf-8")
    _bootstrap_personal_info()
    personal_info = _read_json(paths.PERSONAL_INFO_PATH)
    return {
        "prompt": build_resume_critique_prompt(
            company, job_description, tex_source, personal_info
        ),
        "how_to_use": (
            "Launch a fresh sub-agent (e.g. the Task tool, general-purpose, no "
            "inherited context) with this exact prompt, then call "
            "submit_resume_critique(name, company, job_description, findings) "
            "with its output — finalize_resume is BLOCKED until you do. Apply its "
            "results to your content: REMOVE/rephrase every UNSUPPORTED claim it "
            "flags, ADD every wrongly-omitted entry, CUT the filler it lists "
            "under 'Cut or trim', keep what it marks as working, then fix the "
            "missing keywords and per-item issues and call generate_resume again. "
            "Repeat until the 'Unsupported claims' and 'Wrongly omitted' sections "
            "both come back empty and nothing remains under 'Cut or trim'."
        ),
    }


@mcp.tool()
def submit_resume_critique(
    name: str,
    company: str,
    job_description: str,
    findings: str,
) -> dict[str, Any]:
    """Register that the POST-generation critique actually ran for `name`.

    Call this after running get_resume_critique_prompt's prompt in a fresh
    sub-agent, passing that sub-agent's verbatim output as `findings`. This
    UNLOCKS finalize_resume for this resume. The gate ensures the critique
    isn't skipped and that the server holds the artifact.

    Args:
        name: the resume stem that was critiqued, e.g. "acme_swe_2026".
        company: same company string used for generate_resume.
        job_description: same JD text used for generate_resume.
        findings: the critique sub-agent's verbatim output.
    """
    safe = _safe_name(name)
    state.record_critique(safe, company, job_description, findings)
    return {
        "recorded": True,
        "next": (
            "Revise per the findings and re-run generate_resume as needed, then "
            "call finalize_resume when the critique is clean."
        ),
    }


@mcp.tool()
def finalize_resume(
    name: str,
    company: str,
    job_description: str,
) -> dict[str, Any]:
    """Mark a resume final. GATED on a submitted critique for `name`.

    This is the terminal step of the tailoring loop. It refuses unless a
    critique has been registered (submit_resume_critique) for this resume and
    (company, job_description), AND the compiled PDF is within the page limit
    (ui_guidelines.page.max_pages, default 1) — so a resume can't be shipped
    uncritiqued or overflowing. Returns the resume's paths for confirmation.

    Args:
        name: the resume stem to finalize, e.g. "acme_swe_2026".
        company: same company string used throughout.
        job_description: same JD text used throughout.
    """
    safe = _safe_name(name)
    if not state.has_critique(safe, company, job_description):
        raise ValueError(
            f"finalize_resume is blocked: no critique registered for {safe!r}. "
            "Run get_resume_critique_prompt in a fresh sub-agent, then call "
            "submit_resume_critique(name, company, job_description, findings) "
            "with the SAME name/company/job_description, then retry."
        )
    tex_path = paths.OUTPUT_DIR / f"{safe}.tex"
    pdf_path = paths.OUTPUT_DIR / f"{safe}.pdf"

    if pdf_path.exists():
        _bootstrap_ui_guidelines()
        ui = _read_json(paths.UI_GUIDELINES_PATH)
        pc = checks.page_check(pdf_path, _max_pages(ui))
        if not pc["ok"]:
            raise ValueError(
                f"finalize_resume is blocked: {pc.get('message', 'too many pages')}"
            )

    return {
        "name": safe,
        "finalized": True,
        "tex_path": str(tex_path) if tex_path.exists() else None,
        "pdf_path": str(pdf_path) if pdf_path.exists() else None,
    }


def _resume_plain_text(safe: str) -> str:
    """Plain text of a rendered resume — the PDF's extracted text if available
    (closest to what a human sees), else the raw .tex source."""
    pdf_path = paths.OUTPUT_DIR / f"{safe}.pdf"
    if pdf_path.exists():
        text = checks.pdf_text(pdf_path)
        if text and text.strip():
            return text
    tex_path = paths.OUTPUT_DIR / f"{safe}.tex"
    if tex_path.exists():
        return tex_path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"No resume found for '{safe}' in {paths.OUTPUT_DIR}. Generate it first."
    )


@mcp.tool()
def get_skim_review_prompt(
    name: str,
    company: str = "",
    job_description: str = "",
) -> dict[str, Any]:
    """Build a 6-second-skim first-impression prompt for a rendered resume.

    A FINAL pass (run once near the end, not in the revision loop). A fresh
    sub-agent sees only the rendered text and reacts fast: the takeaway, the
    strongest line, and — the point — what it did NOT notice at all. Catches
    placement/emphasis problems the careful critique never surfaces.
    """
    safe = _safe_name(name)
    return {
        "prompt": build_skim_prompt(company, job_description, _resume_plain_text(safe)),
        "how_to_use": (
            "Run in a fresh sub-agent. Act on emphasis/placement fixes (move a "
            "strong item up, break a dense block); this is not a content-cut pass."
        ),
    }


@mcp.tool()
def get_red_flag_prompt(
    name: str,
    company: str = "",
    job_description: str = "",
) -> dict[str, Any]:
    """Build a red-flag / skeptical-question prompt for a rendered resume.

    A FINAL pass. A fresh sub-agent lists what would make a hiring manager
    hesitate (overclaiming, a too-senior-sounding title, ambiguous scope,
    bullets that invite a question). Each flag can feed get_interview_prompt.
    """
    safe = _safe_name(name)
    return {
        "prompt": build_red_flag_prompt(
            company, job_description, _resume_plain_text(safe)
        ),
        "how_to_use": (
            "Run in a fresh sub-agent. Reword the lines it flags, or (per the "
            "flag) turn it into a get_interview_prompt to close the gap truthfully."
        ),
    }


@mcp.tool()
def get_proofread_prompt(name: str) -> dict[str, Any]:
    """Build a mechanical proofread/consistency prompt for the FINAL resume.

    Run ONCE on the final version (wasted on drafts): tense consistency, date
    formats, repeated opening verbs, punctuation, typos, and a language check
    (e.g. a Swedish Platsbanken ad may expect Swedish). Not a content pass.
    """
    safe = _safe_name(name)
    return {
        "prompt": build_proofread_prompt(_resume_plain_text(safe)),
        "how_to_use": (
            "Run in a fresh sub-agent on the FINAL version only. Apply the "
            "mechanical fixes, then regenerate once."
        ),
    }


@mcp.tool()
def get_interview_prompt(
    section: str,
    target_id: str = "",
    topic: str = "",
    company: str = "",
    job_description: str = "",
    focus: str = "",
) -> dict[str, Any]:
    """Build a prompt to interview the user and enrich ONE personal-info entry.

    Unlike the recruiter prompts, you (the main agent) run this interview
    YOURSELF in the conversation — it asks the user questions, so it must NOT go
    to a sub-agent. It probes one entry for stronger, more specific, truthful
    material and drops any thread that doesn't yield real detail (never inflates
    or pads).

    Two modes, chosen by `target_id`:
      - `target_id` set -> REFINE the existing entry with that `id` in `section`.
      - `target_id` empty -> CREATE a new `section` entry from `topic`.

    Two flavours, chosen by whether job context is given:
      - No company/job_description/focus -> GENERAL, role-agnostic enrichment:
        hunt for angles that matter to different kinds of jobs.
      - With job context + `focus` (the specific gap) -> TARGETED: a narrow
        interview to close that gap for that job. Answers that don't help the
        resume for the job are left off it, but new true facts are still worth
        saving to the catalogue. The "Worth interviewing the candidate about"
        section of get_resume_critique_prompt feeds this flavour during tailoring.

    Args:
        section: which list section the entry lives in, e.g. "experience",
            "projects", "education", "competitions", "certifications" (or any
            custom list section in the catalogue).
        target_id: `id` of the entry to refine; omit to create a new one.
        topic: short description of the new thing (create mode).
        company: hiring company (targeted mode).
        job_description: the job description text (targeted mode).
        focus: the specific gap to close for this job (targeted mode).

    Returns a dict with "prompt" (follow it yourself, in this conversation) and
    "how_to_use".
    """
    _bootstrap_personal_info()
    _bootstrap_ui_guidelines()
    personal_info = _read_json(paths.PERSONAL_INFO_PATH)
    ui = _read_json(paths.UI_GUIDELINES_PATH)

    entry: dict[str, Any] | None = None
    mode = "create"
    if target_id:
        mode = "refine"
        items = personal_info.get(section)
        if not isinstance(items, list):
            raise ValueError(
                f"Section '{section}' is not a list in the catalogue. "
                f"Available list sections: {_list_sections(personal_info)}."
            )
        entry = next((it for it in items if it.get("id") == target_id), None)
        if entry is None:
            ids = [it.get("id", "") for it in items if isinstance(it, dict)]
            raise ValueError(
                f"No entry with id '{target_id}' in section '{section}'. "
                f"Available ids: {ids}."
            )

    model = _SECTION_ITEM_MODELS.get(section)
    item_schema = model.model_json_schema() if model is not None else None

    prompt = build_interview_prompt(
        mode=mode,
        section=section,
        entry=entry,
        topic=topic,
        item_schema=item_schema,
        personal_info=personal_info,
        ui_guidelines=ui,
        company=company,
        job_description=job_description,
        focus=focus,
    )
    return {
        "prompt": prompt,
        "how_to_use": (
            "Run this interview YOURSELF in the current conversation — do NOT "
            "spawn a sub-agent; it has to ask the user questions. Ask a few at a "
            "time, drop any thread that doesn't yield concrete truthful detail, "
            "then show the proposed entry for approval. On approval, save it: "
            "call get_personal_info, replace the entry by `id` (refine) or append "
            "it with a new kebab-case `id` (create) in the right section, then "
            "call update_personal_info. In targeted mode, also use the new detail "
            "on the current resume only if it helps that job."
        ),
    }


@mcp.tool()
def search_platsbanken(
    query: str,
    location: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Search Platsbanken (Arbetsförmedlingen's JobTech JobSearch API) for live ads.

    Use this to DISCOVER jobs that match the candidate. Derive good search inputs
    from get_personal_info first: build `query` from the candidate's titles and
    strongest skills, and pass their `contact.location` (and/or "distans"/remote) as
    `location`. Run more than one query if useful and dedupe by job `id`.

    IMPORTANT: the results are candidates, NOT recommendations. Before you recommend
    ANY job to the user you MUST run the qualification gate via
    get_qualification_check_prompt (a PostToolUse hook will remind you). "Qualified"
    means the candidate meets the job's STATED requirements — not that they are likely
    to be hired.

    Args:
        query: freetext search, e.g. "machine learning engineer python".
        location: place name appended to the freetext, e.g. "Stockholm" or "distans".
        limit: max ads to return (1-100, default 20).
        offset: pagination offset (default 0).

    Returns a dict with "query", "total" (matches available), "count" (returned),
    "jobs" (normalized list with id, headline, employer, location, deadline, url,
    description, …), and "errors".
    """
    return search_jobs(query, location, limit, offset)


@mcp.tool()
def get_job_ad(ad_id: str) -> dict[str, Any]:
    """Fetch one full Platsbanken ad by id, for an accurate qualification check.

    search_platsbanken truncates long descriptions; call this on a promising hit to
    get the FULL requirements text plus the ad's structured must_have/nice_to_have
    blocks before running the qualification gate.

    Args:
        ad_id: the `id` of a job returned by search_platsbanken.

    Returns the normalized ad (full description + must_have/nice_to_have), or a dict
    with an "error" key if the fetch failed.
    """
    return fetch_ad(ad_id)


@mcp.tool()
def get_qualification_check_prompt(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the MANDATORY qualification-gate prompt for a shortlist of jobs.

    Returns a complete, self-contained prompt that embeds the full personal-info
    catalogue and the given jobs, and asks — requirement by requirement — whether the
    candidate meets each job's STATED requirements. This is NOT about hire likelihood.
    Hand the prompt to a FRESH sub-agent (e.g. the Task tool, no inherited context);
    it returns a per-job verdict (QUALIFIED / NOT QUALIFIED / UNCERTAIN) with the
    unmet stated requirements named. The server does not call an LLM.

    A job is recommendable to the user ONLY if the sub-agent returns QUALIFIED. Show
    NOT QUALIFIED jobs separately with their missing stated requirement, and flag
    UNCERTAIN jobs (unconfirmed hard requirements) for the user to confirm.

    Args:
        jobs: the candidate jobs to audit — pass the normalized dicts from
            search_platsbanken / get_job_ad (id, headline, employer, description,
            and any must_have/nice_to_have blocks).

    Returns a dict with "prompt" (give this verbatim to the sub-agent) and
    "how_to_use".
    """
    _bootstrap_personal_info()
    personal_info = _read_json(paths.PERSONAL_INFO_PATH)
    return {
        "prompt": build_qualification_check_prompt(jobs, personal_info),
        "how_to_use": (
            "Launch a fresh sub-agent (e.g. the Task tool, general-purpose, no "
            "inherited context) with this exact prompt. Recommend ONLY the jobs it "
            "marks QUALIFIED; list NOT QUALIFIED jobs separately with the missing "
            "stated requirement (the MISSING_HARD line); surface UNCERTAIN jobs to "
            "the user with the unconfirmed requirement. Qualified means meeting the "
            "job's stated requirements, NOT likelihood of being hired."
        ),
    }


# Run bootstrap eagerly so the first tool call works after a fresh clone. Cheap
# (a couple stats + maybe a copy) and idempotent. Both data files are gitignored
# and seeded from their committed *.example.json counterparts.
_bootstrap_personal_info()
_bootstrap_ui_guidelines()
