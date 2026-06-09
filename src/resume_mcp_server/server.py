from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from resume_mcp_server import paths
from resume_mcp_server.critic import (
    build_interview_prompt,
    build_relevance_review_prompt,
    build_resume_critique_prompt,
)
from resume_mcp_server.latex import compile_tex, tectonic_available
from resume_mcp_server.render import render_resume
from resume_mcp_server.research import research_company_online
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


def _list_sections(personal_info: dict[str, Any]) -> list[str]:
    """Top-level keys whose value is a list — the catalogue's entry sections."""
    return [k for k, v in personal_info.items() if isinstance(v, list)]


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


@mcp.tool()
def get_ui_guidelines() -> dict[str, Any]:
    """Return the UI / style guidelines (data/ui_guidelines.json).

    These are knobs the LaTeX template reads: fonts, accent color, margins,
    section heading style, spacing, voice (person/tense). Pass these into
    generate_resume so the rendered PDF matches the configured style.
    """
    return _read_json(paths.UI_GUIDELINES_PATH)


@mcp.tool()
def update_personal_info(content: dict[str, Any]) -> dict[str, Any]:
    """Replace the personal-info catalogue with `content` (whole-file write).

    Workflow: call get_personal_info, mutate the dict, pass the entire result
    here. The file is validated, written atomically (temp + rename), and the
    saved content is returned for confirmation. Adding new top-level fields is
    fine — schemas allow extra keys.
    """
    validated = validate_personal_info(content)
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
        "0) RANK (before selecting): call get_relevance_review_prompt(company, "
        "job_description) and run the returned prompt in a FRESH sub-agent (e.g. "
        "the Task tool, no inherited context). It scores every catalogue entry "
        "0-5 for this job. Cut the low-scoring ones.\n"
        "1) Read get_personal_info() in full. It is the catalogue, not the resume.\n"
        "2) Using the rankings, pick the items most relevant to the JD per section "
        "(experience, education, projects, competitions, certifications). The agent "
        "decides counts — typical output is e.g. 2 of 3 jobs, 4 of 4 education "
        "entries, 5 of 8 projects, 4 of 6 competitions.\n"
        "3) For each selected item, pick the 2-4 highlights most relevant to the "
        "JD and rewrite them tightly. Match tone to ui_guidelines.voice "
        "(person + tense).\n"
        "4) `narrative` fields in personal_info are background context for you. "
        "They must never be copied verbatim into the resume.\n"
        "5) Pass the curated, rewritten dict to generate_resume(name, content). "
        "The server merges it with current ui_guidelines and renders LaTeX.\n"
        "6) CRITIQUE (after generating): call get_resume_critique_prompt(name, "
        "company, job_description) and run it in a FRESH sub-agent. It sees the "
        "full catalogue AND the rendered resume, so it flags valuable entries you "
        "wrongly OMITTED (by id) plus the top-5 missing keywords and per-item "
        "good/bad feedback.\n"
        "7) REVISE: ADD every wrongly-omitted entry it flags, fix the keywords and "
        "per-item issues, and call generate_resume again. Repeat 6-7 until the "
        "'Wrongly omitted' section comes back empty and the critique is clean."
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
            "inherited context) with this exact prompt. Use the returned 0-5 "
            "rankings to choose which entries and highlights to include — drop "
            "the low-scoring ones — then build content for generate_resume."
        ),
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
    compile: bool = True,
) -> dict[str, Any]:
    """Render a tailored resume to LaTeX and (by default) compile to PDF.

    Args:
        name: filename stem for output, e.g. "acme_swe_2026". Must match
            [A-Za-z0-9_-]+.
        content: the curated structured dict — same shape as personal_info,
            but trimmed and rewritten for the target JD. See get_resume_schema.
        compile: if True (default), runs Tectonic to produce a PDF. If False,
            only the .tex file is written, useful for iterating on content
            without paying the compile cost.

    Returns paths to the generated .tex and .pdf (when compiled), plus any
    Tectonic stdout/stderr/log path on failure.
    """
    safe = _safe_name(name)
    paths.ensure_dirs()
    ui = _read_json(paths.UI_GUIDELINES_PATH)

    tex_source = render_resume("resume.tex.j2", content, ui)
    tex_path = paths.OUTPUT_DIR / f"{safe}.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    result: dict[str, Any] = {
        "name": safe,
        "tex_path": str(tex_path),
        "compiled": False,
    }

    if not compile:
        return result

    cr = compile_tex(tex_path)
    result["compiled"] = cr.ok
    if cr.ok and cr.pdf_path is not None:
        result["pdf_path"] = str(cr.pdf_path)
    if cr.log_path is not None:
        result["log_path"] = str(cr.log_path)
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
    if cr.log_path is not None:
        result["log_path"] = str(cr.log_path)
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
            "inherited context) with this exact prompt. Apply its results to your "
            "content — ADD every wrongly-omitted entry it flags, then fix the "
            "missing keywords and per-item issues — and call generate_resume "
            "again. Repeat until the 'Wrongly omitted' section comes back empty."
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
def research_company(
    company_name: str,
    job_description: str = "",
) -> dict[str, Any]:
    """Research a company online to gather context for resume tailoring.

    Queries DuckDuckGo and fetches the company's own pages to collect
    information about mission, culture, tech stack, and domain focus.
    Returns structured findings for use when writing the resume summary
    and selecting/rewriting highlights to match what the company values.

    Args:
        company_name: name of the company to research, e.g. "Citadel Securities".
        job_description: optional job description text; used to run an
            additional domain-specific search (e.g. role keywords refine
            what to look for).

    Returns a dict with keys: company_name, findings (list of {type, source,
    text}), sources (list of URLs), errors (list of any fetch failures).
    findings types: "overview", "related", "tech", "webpage", "role_context".
    """
    return research_company_online(company_name, job_description)


# Run bootstrap eagerly so first call to get_personal_info() works after a
# fresh clone. Cheap (one stat + maybe one copy) and idempotent.
_bootstrap_personal_info()
