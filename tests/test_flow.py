"""End-to-end test of the gated tailoring state machine (no Tectonic needed)."""

from __future__ import annotations

import json

import pytest

from resume_mcp_server import paths, server

COMPANY = "Acme"
JD = "Build trading systems in Python."
UI = {
    "page": {},
    "fonts": {},
    "colors": {},
    "section_heading": {},
    "spacing": {},
    "header": {},
}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "personal_info.json").write_text(
        json.dumps({"name": "Ada", "projects": [{"id": "a", "name": "A"}]}),
        encoding="utf-8",
    )
    (data_dir / "ui_guidelines.json").write_text(json.dumps(UI), encoding="utf-8")
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(paths, "PERSONAL_INFO_PATH", data_dir / "personal_info.json")
    monkeypatch.setattr(paths, "UI_GUIDELINES_PATH", data_dir / "ui_guidelines.json")
    monkeypatch.setattr(paths, "PERSONAL_INFO_EXAMPLE_PATH", data_dir / "missing1.json")
    monkeypatch.setattr(paths, "UI_GUIDELINES_EXAMPLE_PATH", data_dir / "missing2.json")
    return tmp_path


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_full_gated_flow(isolated):
    content = {"name": "Ada", "title": "Engineer"}

    # 1. generate is blocked before a relevance review
    with pytest.raises(ValueError, match="no relevance review"):
        server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)

    # 2. submit review unlocks generate
    server.submit_relevance_review(COMPANY, JD, "scores...")
    gen = server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)
    assert gen["tex_path"].endswith("r.tex")

    # 3. finalize is blocked before a critique
    with pytest.raises(ValueError, match="no critique"):
        server.finalize_resume("r", COMPANY, JD)

    # 4. submit critique unlocks finalize
    server.submit_resume_critique("r", COMPANY, JD, "READY")
    fin = server.finalize_resume("r", COMPANY, JD)
    assert fin["finalized"] is True


def test_generate_rejects_em_dash(isolated):
    server.submit_relevance_review(COMPANY, JD, "scores...")
    content = {"name": "Ada", "summary": "Led a team—shipped fast"}
    with pytest.raises(ValueError, match="forbidden dash"):
        server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)


def test_generate_rejects_banned_phrase(isolated):
    _write(
        isolated / "data" / "ui_guidelines.json",
        {**UI, "voice": {"banned_phrases": ["gedigen kompetens"]}},
    )
    server.submit_relevance_review(COMPANY, JD, "scores...")
    content = {"name": "Ada", "summary": "Har Gedigen Kompetens inom analys."}
    with pytest.raises(ValueError, match="gedigen kompetens"):
        server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)


def test_generate_allows_content_without_banned_phrases(isolated):
    _write(
        isolated / "data" / "ui_guidelines.json",
        {**UI, "voice": {"banned_phrases": ["gedigen kompetens"]}},
    )
    server.submit_relevance_review(COMPANY, JD, "scores...")
    content = {"name": "Ada", "summary": "Byggde en riskmodell i Python."}
    gen = server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)
    assert gen["tex_path"].endswith("r.tex")


def test_selection_check_absent_when_flag_off(isolated):
    server.submit_relevance_review(COMPANY, JD, "scores...")
    gen = server.generate_resume("r", {"name": "Ada"}, COMPANY, JD, compile_pdf=False)
    assert "selection_check" not in gen


def test_include_all_experience_reports_and_blocks_finalize(isolated):
    _write(
        isolated / "data" / "personal_info.json",
        {"name": "Ada", "experience": [{"id": "job-a", "title": "Dev"}, {"id": "job-b", "title": "Analyst"}]},
    )
    _write(
        isolated / "data" / "ui_guidelines.json",
        {**UI, "selection": {"include_all_experience": True}},
    )
    server.submit_relevance_review(COMPANY, JD, "scores...")

    # Only one of the two catalogue jobs is on the resume.
    content = {"name": "Ada", "experience": [{"id": "job-a", "title": "Dev"}]}
    gen = server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)
    assert gen["selection_check"]["ok"] is False
    assert gen["selection_check"]["missing_ids"] == ["job-b"]

    # ... and finalize refuses, even though the critique gate is satisfied.
    server.submit_resume_critique("r", COMPANY, JD, "READY")
    with pytest.raises(ValueError, match="job-b"):
        server.finalize_resume("r", COMPANY, JD)

    # Adding the missing job clears both.
    content["experience"].append({"id": "job-b", "title": "Analyst"})
    gen = server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)
    assert gen["selection_check"]["ok"] is True
    assert server.finalize_resume("r", COMPANY, JD)["finalized"] is True


def test_require_all_from_covers_more_than_experience(isolated):
    # The generalisation: coverage is no longer hardwired to `experience`.
    _write(
        isolated / "data" / "personal_info.json",
        {
            "name": "Ada",
            "experience": [{"id": "job-a", "title": "Dev"}],
            "education": [{"id": "edu-a", "degree": "BSc"}, {"id": "edu-b", "degree": "MSc"}],
        },
    )
    _write(
        isolated / "data" / "ui_guidelines.json",
        {**UI, "selection": {"require_all_from": ["experience", "education"]}},
    )
    server.submit_relevance_review(COMPANY, JD, "scores...")

    content = {
        "name": "Ada",
        "experience": [{"id": "job-a", "title": "Dev"}],
        "education": [{"id": "edu-a", "degree": "BSc"}],
    }
    gen = server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)
    assert gen["selection_check"]["ok"] is False
    assert gen["selection_check"]["missing_ids"] == ["edu-b"]

    server.submit_resume_critique("r", COMPANY, JD, "READY")
    with pytest.raises(ValueError, match="edu-b"):
        server.finalize_resume("r", COMPANY, JD)

    content["education"].append({"id": "edu-b", "degree": "MSc"})
    gen = server.generate_resume("r", content, COMPANY, JD, compile_pdf=False)
    assert gen["selection_check"]["ok"] is True
    assert server.finalize_resume("r", COMPANY, JD)["finalized"] is True


def test_get_ui_guidelines_exposes_resolved_sections_for_a_config_without_any(isolated):
    # The raw file has no `sections` key; the agent must still be able to see
    # what will actually render.
    ui = server.get_ui_guidelines()
    assert "sections" not in {k: v for k, v in ui.items() if k != "resolved_sections"}
    resolved = ui["resolved_sections"]
    # The isolated catalogue only has projects, so only that section survives.
    assert [s["key"] for s in resolved] == ["projects"]
    assert resolved[0]["title"] == "Competitions and Projects"
    assert resolved[0]["sources"] == ["projects"]


def test_get_ui_guidelines_reflects_a_custom_sections_list(isolated):
    _write(
        isolated / "data" / "ui_guidelines.json",
        {
            **UI,
            "sections": [
                {
                    "key": "projects",
                    "title": "Selected Work",
                    "blocks": [
                        {"source": "projects", "kind": "entries", "fields": {"bold": ["name"]}}
                    ],
                }
            ],
        },
    )
    resolved = server.get_ui_guidelines()["resolved_sections"]
    assert resolved == [
        {"key": "projects", "title": "Selected Work", "sources": ["projects"]}
    ]


def test_get_resume_schema_reports_sections_and_the_full_catalogue_shape(isolated):
    schema = server.get_resume_schema()
    assert [s["key"] for s in schema["sections"]] == ["projects"]
    props = schema["schema"]["properties"]
    # These render, so they must not be missing from the shape handed to the agent.
    assert "voluntary_work" in props
    assert "languages" in props
    # The guidance names the sections instead of restating a hardcoded list.
    assert "in order: projects" in schema["guidance"]


def test_finalize_notes_unverified_coverage_without_a_generation_record(isolated):
    # Flag turned on for a resume that was generated before it existed.
    server.submit_relevance_review(COMPANY, JD, "scores...")
    server.generate_resume("r", {"name": "Ada"}, COMPANY, JD, compile_pdf=False)
    server.submit_resume_critique("r", COMPANY, JD, "READY")
    _write(
        isolated / "data" / "personal_info.json",
        {"name": "Ada", "experience": [{"id": "job-a", "title": "Dev"}]},
    )
    _write(
        isolated / "data" / "ui_guidelines.json",
        {**UI, "selection": {"include_all_experience": True}},
    )
    fin = server.finalize_resume("r", COMPANY, JD)
    assert fin["finalized"] is True
    assert "NOT verified" in fin["note"]
