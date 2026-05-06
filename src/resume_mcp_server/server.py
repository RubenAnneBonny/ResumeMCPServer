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
from resume_mcp_server.latex import compile_tex, tectonic_available
from resume_mcp_server.render import render_resume
from resume_mcp_server.research import research_company_online
from resume_mcp_server.schemas import (
    PersonalInfo,
    UIGuidelines,
    validate_personal_info,
    validate_ui_guidelines,
)

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
        "When tailoring a resume to a job description:\n"
        "1) Read get_personal_info() in full. It is the catalogue, not the resume.\n"
        "2) For each section (experience, education, projects, competitions, "
        "certifications), pick the items most relevant to the JD. The agent "
        "decides counts — typical output is e.g. 2 of 3 jobs, 4 of 4 education "
        "entries, 5 of 8 projects, 4 of 6 competitions.\n"
        "3) For each selected item, pick the 2-4 highlights most relevant to the "
        "JD and rewrite them tightly. Match tone to ui_guidelines.voice "
        "(person + tense).\n"
        "4) `narrative` fields in personal_info are background context for you. "
        "They must never be copied verbatim into the resume.\n"
        "5) Pass the curated, rewritten dict to generate_resume(name, content). "
        "The server merges it with current ui_guidelines and renders LaTeX."
    )
    return {"schema": schema, "guidance": guidance}


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
