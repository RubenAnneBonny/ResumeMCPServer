from __future__ import annotations

from resume_mcp_server.render import latex_escape, render_resume, resolve_ui
from resume_mcp_server.schemas import validate_personal_info

# A ui config predating section_titles/skill_labels — the fallback path must
# keep working for it.
LEGACY_UI = {
    "page": {},
    "fonts": {},
    "colors": {},
    "section_heading": {},
    "spacing": {},
    "header": {},
}


def test_latex_escape_backslash_not_double_escaped():
    # The historical bug: "\" -> "\textbackslash{}" then "{"/"}" re-escaped the
    # braces into "\textbackslash\{\}". A single-pass escape must not do that.
    assert latex_escape("C:\\Users\\ruben") == r"C:\textbackslash{}Users\textbackslash{}ruben"


def test_latex_escape_specials():
    assert latex_escape("a & b_c 100%") == r"a \& b\_c 100\%"
    assert latex_escape("#$^") == r"\#\$\textasciicircum{}"
    assert latex_escape("tilde~x") == r"tilde\textasciitilde{}x"


def test_latex_escape_unicode_dashes():
    assert latex_escape("em—dash") == "em---dash"
    assert latex_escape("en–dash") == "en--dash"


def test_latex_escape_none_is_empty():
    assert latex_escape(None) == ""


def test_render_ignores_stray_ui_key_in_content():
    # A "ui" key inside content must not collide with the ui=ui keyword arg.
    content = validate_personal_info({"name": "Test Candidate", "ui": "should be ignored"})
    content["ui"] = "should be ignored"  # force the collision case
    ui = {"page": {}, "fonts": {}, "colors": {}, "section_heading": {}, "spacing": {}, "header": {}}
    out = render_resume("resume.tex.j2", content, ui)
    assert "Test Candidate" in out


def test_render_smoke_minimal_content():
    # Mirrors generate_resume, which validates (filling top-level defaults)
    # before rendering.
    content = validate_personal_info({
        "name": "Ada Lovelace",
        "title": "Engineer",
        "summary": "Builds things.",
        "experience": [
            {"title": "Dev", "company": "Acme", "start_date": "2024", "end_date": "2025",
             "highlights": [{"text": "Did work with special chars & symbols_here"}]}
        ],
    })
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert "\\begin{document}" in out
    assert "Ada Lovelace" in out
    assert r"\&" in out  # user content was escaped


def test_resolve_ui_fills_defaults_for_config_without_section_titles():
    # The whole point of resolving in Python: StrictUndefined would blow up on
    # ui.section_titles.experience for a config that predates the key.
    resolved = resolve_ui(LEGACY_UI)
    assert resolved["section_titles"]["experience"] == "Experience"
    assert resolved["skill_labels"]["languages"] == "Programming Languages"


def test_resolve_ui_config_overrides_win_and_others_fall_back():
    resolved = resolve_ui({**LEGACY_UI, "section_titles": {"experience": "Arbetslivserfarenhet"}})
    assert resolved["section_titles"]["experience"] == "Arbetslivserfarenhet"
    assert resolved["section_titles"]["education"] == "Education"  # untouched default


def test_render_uses_configured_section_titles():
    content = validate_personal_info({
        "name": "Ada",
        "summary": "Bygger saker.",
        "education": [{"degree": "Civilingenjör", "institution": "KTH", "start_date": "2023"}],
        "experience": [{"title": "Utvecklare", "company": "Acme", "start_date": "2024"}],
        "competitions": [{"id": "c1", "name": "SM i programmering", "date": "2024"}],
    })
    ui = {
        **LEGACY_UI,
        "section_titles": {
            "profile": "Profil",
            "education": "Utbildning",
            "experience": "Arbetslivserfarenhet",
            "projects": "Strategiska uppdrag",
        },
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert r"\section{\textbf{Profil}}" in out
    assert r"\section{\textbf{Utbildning}}" in out
    assert r"\section{\textbf{Arbetslivserfarenhet}}" in out
    assert r"\section{\textbf{Strategiska uppdrag}}" in out
    # No English header survives when every rendered section is configured.
    for english in ("Profile", "Education", "Experience", "Competitions and Projects"):
        assert f"\\section{{\\textbf{{{english}}}}}" not in out


def test_render_escapes_section_titles():
    content = validate_personal_info({"name": "Ada", "summary": "x"})
    ui = {**LEGACY_UI, "section_titles": {"profile": "R&D 100%"}}
    out = render_resume("resume.tex.j2", content, ui)
    assert r"\section{\textbf{R\&D 100\%}}" in out


def test_render_structured_skills_uses_configured_labels():
    content = validate_personal_info({
        "name": "Ada",
        "skills": {"languages": ["Python", "C++"], "frameworks": [], "tools": ["Git"]},
    })
    ui = {
        **LEGACY_UI,
        "section_titles": {"skills": "Tekniska färdigheter"},
        "skill_labels": {"languages": "Programmeringsspråk", "tools": "Utvecklingsverktyg"},
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert r"\section{\textbf{Tekniska färdigheter}}" in out
    assert r"\textbf{Programmeringsspråk}: Python, C++" in out
    assert r"\textbf{Utvecklingsverktyg}: Git" in out
    assert "Frameworks" not in out  # empty sub-list is not rendered


def test_render_structured_skills_defaults_to_english_labels():
    content = validate_personal_info({"name": "Ada", "skills": {"languages": ["Python"]}})
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert r"\section{\textbf{Technical Skills}}" in out
    assert r"\textbf{Programming Languages}: Python" in out


def test_render_flat_skills_list():
    # Regression: a flat ["..."] skills list used to render NOTHING at all.
    content = validate_personal_info({
        "name": "Ada",
        "skills": ["Projektledning", "Upphandling", "R&D"],
    })
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert r"\section{\textbf{Skills}}" in out  # flat default, not "Technical Skills"
    assert r"\item{Projektledning, Upphandling, R\&D}" in out


def test_render_flat_skills_honors_configured_title():
    content = validate_personal_info({"name": "Ada", "skills": ["Upphandling"]})
    ui = {**LEGACY_UI, "section_titles": {"skills": "Kompetenser"}}
    out = render_resume("resume.tex.j2", content, ui)
    assert r"\section{\textbf{Kompetenser}}" in out


def test_render_empty_skills_renders_no_section():
    for empty in ([], {}):
        content = validate_personal_info({"name": "Ada", "skills": empty})
        out = render_resume("resume.tex.j2", content, LEGACY_UI)
        assert "Skills" not in out
