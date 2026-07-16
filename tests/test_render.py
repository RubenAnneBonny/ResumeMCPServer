from __future__ import annotations

import json
import pathlib

import pytest

from resume_mcp_server.render import (
    date_range,
    join_fields,
    latex_escape,
    render_resume,
    resolve_ui,
)
from resume_mcp_server.schemas import validate_personal_info

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
REPO = pathlib.Path(__file__).resolve().parents[1]

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


# --------------------------------------------------------------------------
# Data-driven sections (ui_guidelines.sections)
# --------------------------------------------------------------------------


def _load(path: str) -> dict:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def _section_order(tex: str) -> list[str]:
    return [
        line[len(r"\section{\textbf{") : -len("}}")]
        for line in tex.splitlines()
        if line.startswith(r"\section{\textbf{")
    ]


@pytest.mark.parametrize(
    ("golden", "catalogue"),
    [
        ("golden_default.tex", "data/personal_info.example.json"),
        ("golden_full.tex", "tests/fixtures/full_catalogue.json"),
    ],
)
def test_golden_render_is_unchanged(golden, catalogue):
    """The regression net for making sections data-driven.

    These fixtures were captured from the template BEFORE it became a generic
    loop, so an unintended layout change anywhere shows up as a diff. The
    example config now carries an explicit `sections` list, which means this
    also proves the explicit config and the synthesized DEFAULT_SECTIONS agree.
    (The one intentional difference at capture time: an empty section no longer
    leaves a stray blank line in the .tex. LaTeX collapses blank lines in
    vertical mode, so the PDF is identical.)
    """
    want = (FIXTURES / golden).read_text(encoding="utf-8")
    got = render_resume(
        "resume.tex.j2",
        validate_personal_info(_load(catalogue)),
        _load("data/ui_guidelines.example.json"),
    )
    assert got == want


def test_config_without_sections_key_still_renders_the_defaults():
    # The migration guarantee: `sections` is opt-in, and a config predating it
    # (like a live data/ui_guidelines.json) must keep working untouched.
    content = validate_personal_info(_load("tests/fixtures/full_catalogue.json"))
    assert "sections" not in LEGACY_UI
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert _section_order(out) == [
        "Profile",
        "Education",
        "Experience",
        "Competitions and Projects",
        "Technical Skills",
        "Voluntary Work and Engagements",
        "Certifications",
        "Languages",
    ]


def test_sections_can_be_reordered_and_dropped():
    content = validate_personal_info(_load("tests/fixtures/full_catalogue.json"))
    default_sections = resolve_ui(LEGACY_UI, content)["sections"]
    by_key = {s["key"]: s for s in default_sections}
    ui = {**LEGACY_UI, "sections": [by_key["experience"], by_key["education"]]}
    out = render_resume("resume.tex.j2", content, ui)
    # Experience now precedes Education, and everything else is gone.
    assert _section_order(out) == ["Experience", "Education"]


def test_empty_sections_list_renders_no_sections():
    # [] is meaningfully different from an absent key: it means "render nothing".
    content = validate_personal_info(_load("tests/fixtures/full_catalogue.json"))
    out = render_resume("resume.tex.j2", content, {**LEGACY_UI, "sections": []})
    assert _section_order(out) == []
    assert "Jordan Fixture" in out  # the header still renders


def test_section_title_precedence_spec_beats_section_titles():
    content = validate_personal_info({"name": "Ada", "summary": "Builds things."})
    ui = {
        **LEGACY_UI,
        "section_titles": {"profile": "From section_titles"},
        "sections": [
            {
                "key": "profile",
                "title": "From the spec",
                "blocks": [{"source": "summary", "kind": "prose"}],
            }
        ],
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert _section_order(out) == ["From the spec"]


def test_section_without_title_falls_back_to_section_titles():
    # So a user who only wants translated headers still edits section_titles
    # alone, even with an explicit sections list.
    content = validate_personal_info({"name": "Ada", "summary": "Bygger saker."})
    ui = {
        **LEGACY_UI,
        "section_titles": {"profile": "Profil"},
        "sections": [{"key": "profile", "blocks": [{"source": "summary", "kind": "prose"}]}],
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert _section_order(out) == ["Profil"]


def test_unknown_section_key_title_falls_back_to_titlecased_key():
    content = validate_personal_info({"name": "Ada", "summary": "x"})
    content["side_gigs"] = [{"what": "Bar work", "when": "2024"}]
    ui = {
        **LEGACY_UI,
        "sections": [
            {
                "key": "side_gigs",
                "blocks": [
                    {"source": "side_gigs", "kind": "entries", "fields": {"bold": ["what"]}}
                ],
            }
        ],
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert _section_order(out) == ["Side Gigs"]


def test_invented_section_renders_with_no_template_change():
    """The payoff of the field mapping: a section the template has never heard
    of, fed by a catalogue key that is not in PersonalInfo, renders from config
    alone."""
    content = validate_personal_info({"name": "Ada", "summary": "x"})
    content["publications"] = [
        {
            "id": "pub-1",
            "title": "On Computable Numbers",
            "venue": "Proc. LMS",
            "year": "1936",
            "notes": [{"text": "Cited 20000 times."}],
        }
    ]
    ui = {
        **LEGACY_UI,
        "sections": [
            {
                "key": "publications",
                "title": "Publications",
                "blocks": [
                    {
                        "source": "publications",
                        "kind": "entries",
                        "fields": {
                            "bold": ["title"],
                            "italic": ["venue"],
                            "italic_sep": " --- ",
                            "right": ["year"],
                            "bullets": "notes",
                        },
                    }
                ],
            }
        ],
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert _section_order(out) == ["Publications"]
    assert r"\textbf{On Computable Numbers} --- \textit{Proc. LMS} & \textit{1936}" in out
    assert r"\item Cited 20000 times." in out


def test_one_section_can_merge_several_sources():
    content = validate_personal_info(_load("tests/fixtures/full_catalogue.json"))
    ui = {
        **LEGACY_UI,
        "sections": [
            {
                "key": "everything",
                "title": "Selected Work",
                "blocks": [
                    {
                        "source": "competitions",
                        "kind": "entries",
                        "fields": {"bold": ["name"], "right": ["date"]},
                    },
                    {
                        "source": "projects",
                        "kind": "entries",
                        "fields": {"bold": ["name"], "italic": ["tech"], "italic_sep": " --- "},
                    },
                ],
            }
        ],
    }
    out = render_resume("resume.tex.j2", content, ui)
    # One heading, both sources under it, inside a single itemize.
    assert _section_order(out) == ["Selected Work"]
    assert out.count(r"\begin{itemize}[leftmargin=0.05in, label={}]") == 1
    assert r"\textbf{ICPC Nordic}" in out
    assert r"\textbf{Sparse Solver} --- \textit{Rust, LAPACK}" in out


def test_block_with_no_catalogue_content_is_pruned():
    content = validate_personal_info({"name": "Ada", "summary": "x", "projects": []})
    ui = {
        **LEGACY_UI,
        "sections": [
            {
                "key": "projects",
                "title": "Projects",
                "blocks": [
                    {"source": "projects", "kind": "entries", "fields": {"bold": ["name"]}}
                ],
            }
        ],
    }
    out = render_resume("resume.tex.j2", content, ui)
    assert _section_order(out) == []


def test_skills_renders_every_subkey_not_a_hardcoded_five():
    # The template used to enumerate languages/frameworks/tools/data_structures/
    # algorithms, so a sixth category was silently invisible.
    content = validate_personal_info({
        "name": "Ada",
        "skills": {"languages": ["Python"], "quantum_things": ["Qiskit"]},
    })
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    # No configured label -> title-cased key, which render.py always promised.
    assert r"\textbf{Quantum Things}: Qiskit" in out


def test_skills_section_renders_when_only_an_unlisted_subkey_has_values():
    # The old `has_skills` guard checked only languages/frameworks/tools, so a
    # catalogue with just data_structures rendered no section at all.
    content = validate_personal_info({
        "name": "Ada",
        "skills": {"data_structures": ["Segment trees"]},
    })
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert r"\section{\textbf{Technical Skills}}" in out
    assert r"\textbf{Data Structures}: Segment trees" in out


def test_skills_with_only_empty_sublists_renders_no_section():
    content = validate_personal_info({"name": "Ada", "skills": {"languages": [], "tools": []}})
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert _section_order(out) == []


def test_join_fields_drops_empties_and_flattens_lists():
    assert join_fields({"a": "x", "b": "y"}, ["a", "b"]) == "x, y"
    # A dangling ", " is exactly what the old hardcoded "title, company" produced.
    assert join_fields({"a": "x", "b": ""}, ["a", "b"]) == "x"
    assert join_fields({"tech": ["Rust", "C"]}, ["tech"]) == "Rust, C"
    assert join_fields({"a": "x"}, ["missing"]) == ""
    assert join_fields({"a": "x", "b": "y"}, ["a", "b"], sep=" --- ") == "x --- y"


def test_date_range_collapses_and_handles_arity():
    item = {"start_date": "2024", "end_date": "2025", "same": "2024", "one": "2020"}
    assert date_range(item, []) == ""
    assert date_range(item, ["one"]) == "2020"
    assert date_range(item, ["start_date", "end_date"]) == "2024--2025"
    # An ongoing or single-year entry must not render "2024--2024" or "2024--".
    assert date_range(item, ["start_date", "same"]) == "2024"
    assert date_range({"start_date": "2024", "end_date": ""}, ["start_date", "end_date"]) == "2024"


def test_entries_with_no_right_field_render_a_bare_cell():
    # Projects have no dates: the right-hand cell must stay empty rather than
    # emitting an empty \textit{}, which is what the pre-refactor template did.
    content = validate_personal_info({
        "name": "Ada",
        "projects": [{"id": "p", "name": "Solver", "tech": ["Rust"]}],
    })
    out = render_resume("resume.tex.j2", content, LEGACY_UI)
    assert r"\textbf{Solver} --- \textit{Rust} &" in out
    assert r"\textit{}" not in out
