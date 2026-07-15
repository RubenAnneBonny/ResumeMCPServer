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
