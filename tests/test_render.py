from __future__ import annotations

from resume_mcp_server.render import latex_escape, render_resume
from resume_mcp_server.schemas import validate_personal_info


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
    ui = {"page": {}, "fonts": {}, "colors": {}, "section_heading": {}, "spacing": {}, "header": {}}
    out = render_resume("resume.tex.j2", content, ui)
    assert "\\begin{document}" in out
    assert "Ada Lovelace" in out
    assert r"\&" in out  # user content was escaped
