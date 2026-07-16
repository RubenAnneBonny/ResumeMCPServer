"""Manual end-to-end smoke test on the BUNDLED EXAMPLE data.

Not part of pytest: it shells out to Tectonic and takes a few seconds. Run it
after changing the template, the checks, or the ui_guidelines schema.

Drives the real MCP tool functions through an isolated RESUME_MCP_ROOT (a temp
dir seeded from the *.example.json files + a copy of templates/), so the user's
real, gitignored data/ and output/ are never touched.

Exercises the Batch A config surface end to end:
  max_pages 2 + target_pages 2 + Swedish section_titles + include_all_experience

    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SWEDISH_UI_OVERRIDES = {
    "page": {
        "size": "a4paper",
        "font_size": "11pt",
        "margin_left": "1.4cm",
        "margin_top": "0.8cm",
        "margin_right": "1.2cm",
        "margin_bottom": "1.0cm",
        "max_pages": 2,
        "target_pages": 2,
    },
    "section_titles": {
        "profile": "Profil",
        "education": "Utbildning",
        "experience": "Arbetslivserfarenhet",
        "projects": "Strategiska uppdrag",
        "skills": "Tekniska färdigheter",
        "voluntary_work": "Ideellt engagemang",
        "certifications": "Certifieringar",
        "languages": "Språk",
    },
    "skill_labels": {
        "languages": "Programmeringsspråk",
        "frameworks": "Ramverk & bibliotek",
        "tools": "Utvecklingsverktyg",
        "data_structures": "Datastrukturer",
        "algorithms": "Algoritmer",
    },
    "selection": {"include_all_experience": True},
}

# Headers the template used to hardcode, as the exact LaTeX construct each is
# rendered in. Matching the construct rather than the bare word matters: the
# example catalogue legitimately contains "LinkedIn Profile" (a link label) and
# a summary reading "Experienced in ...", neither of which is a leaked header.
ENGLISH_HEADERS = [
    rf"\section{{\textbf{{{h}}}}}"
    for h in (
        "Profile",
        "Education",
        "Experience",
        "Competitions and Projects",
        "Technical Skills",
        "Voluntary Work and Engagements",
        "Certifications",
        "Languages",
        "Skills",
    )
] + [
    rf"\textbf{{{label}}}:"
    for label in (
        "Programming Languages",
        r"Frameworks \& Libraries",
        "Developer Tools",
        "Data Structures",
        "Algorithms",
    )
]

COMPANY = "Exempel AB"
JD = "Vi söker en utvecklare med stark bakgrund inom Python och dataanalys."


def _setup_root(tmp: Path) -> None:
    (tmp / "data").mkdir(parents=True)
    (tmp / "output").mkdir(parents=True)
    shutil.copytree(REPO / "templates", tmp / "templates")
    shutil.copy2(
        REPO / "data" / "personal_info.example.json", tmp / "data" / "personal_info.json"
    )
    ui = json.loads(
        (REPO / "data" / "ui_guidelines.example.json").read_text(encoding="utf-8")
    )
    ui.update(SWEDISH_UI_OVERRIDES)
    (tmp / "data" / "ui_guidelines.json").write_text(
        json.dumps(ui, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _content_from_catalogue(pi: dict) -> dict:
    """Everything the catalogue has, lightly shaped — this is a render/checks
    smoke test, not a tailoring test, so no selection judgement is applied."""
    return {
        k: v
        for k, v in pi.items()
        if k
        in (
            "name",
            "title",
            "contact",
            "summary",
            "education",
            "experience",
            "competitions",
            "projects",
            "skills",
            "voluntary_work",
            "languages",
            "certifications",
        )
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="resume_smoke_"))
    os.environ["RESUME_MCP_ROOT"] = str(tmp)
    _setup_root(tmp)

    # Import AFTER RESUME_MCP_ROOT is set: paths resolves it at import time.
    from resume_mcp_server import paths, server

    print(f"root: {tmp}")
    print(f"tectonic available: {server.check_environment()['tectonic_available']}")

    pi = json.loads(paths.PERSONAL_INFO_PATH.read_text(encoding="utf-8"))
    content = _content_from_catalogue(pi)

    server.submit_relevance_review(COMPANY, JD, "smoke test: rankings not exercised")
    result = server.generate_resume("smoke", content, COMPANY, JD)

    ok = True

    print(f"\ncompiled: {result['compiled']}")
    if not result["compiled"]:
        print("  error:", result.get("error"))
        print("  stderr:", (result.get("stderr") or "")[-1500:])
        ok = False

    for key in ("page_check", "ats_check", "selection_check"):
        check = result.get(key)
        if check is None:
            print(f"{key}: MISSING")
            ok = False
            continue
        print(f"{key}: ok={check['ok']}")
        for field in ("pages", "max_pages", "target_pages", "missing_ids"):
            if field in check:
                print(f"    {field}: {check[field]}")
        if not check["ok"]:
            print(f"    message: {check.get('message', '')[:200]}")
            ok = False

    tex = (paths.OUTPUT_DIR / "smoke.tex").read_text(encoding="utf-8")
    leaked = [h for h in ENGLISH_HEADERS if h in tex]
    print(f"\nenglish headers/labels left in .tex: {leaked or 'none'}")
    if leaked:
        ok = False

    titles = SWEDISH_UI_OVERRIDES["section_titles"]
    rendered = [k for k, v in titles.items() if rf"\section{{\textbf{{{v}}}}}" in tex]
    absent = sorted(set(titles) - set(rendered))
    print(f"swedish headers rendered ({len(rendered)}/{len(titles)}): {rendered}")
    # A section with no catalogue entries is legitimately not rendered.
    for key in absent:
        empty = not (pi.get("certifications" if key == "certifications" else key) or [])
        print(f"  not rendered: {key} ({'section is empty in the catalogue' if empty else 'UNEXPECTED'})")
        if not empty:
            ok = False

    # Labels are LaTeX-escaped on the way in ("&" -> "\&"), so escape the
    # expected string the same way rather than massaging the rendered output.
    from resume_mcp_server.render import latex_escape

    labels = SWEDISH_UI_OVERRIDES["skill_labels"]
    shown = [
        k for k, v in labels.items() if rf"\textbf{{{latex_escape(v)}}}:" in tex
    ]
    missing_labels = sorted(set(labels) - set(shown))
    print(f"swedish skill labels rendered ({len(shown)}/{len(labels)}): {shown}")
    for key in missing_labels:
        empty = not ((pi.get("skills") or {}).get(key) or [])
        print(f"  not rendered: {key} ({'no such skills in the catalogue' if empty else 'UNEXPECTED'})")
        if not empty:
            ok = False

    # The combined final-pass tool must build against the real rendered resume.
    prompt = server.get_final_review_prompt("smoke", COMPANY, JD)["prompt"]
    has_sections = all(s in prompt for s in ("## SKIM", "## RED FLAGS", "## PROOFREAD"))
    print(f"\nget_final_review_prompt: {len(prompt)} chars, 3 sections={has_sections}")
    if not has_sections:
        ok = False

    server.submit_resume_critique("smoke", COMPANY, JD, "READY - smoke test")
    try:
        fin = server.finalize_resume("smoke", COMPANY, JD)
        print(f"finalize_resume: finalized={fin['finalized']}")
        if fin.get("note"):
            print(f"  note: {fin['note']}")
    except ValueError as e:
        print(f"finalize_resume BLOCKED: {e}")
        ok = False

    pdf = paths.OUTPUT_DIR / "smoke.pdf"
    print(f"\npdf: {pdf if pdf.exists() else 'MISSING'}")
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
