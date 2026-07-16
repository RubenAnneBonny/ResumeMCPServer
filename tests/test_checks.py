from __future__ import annotations

from pypdf import PdfWriter

from resume_mcp_server import checks


def _make_pdf(path, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)  # A4 points
    with path.open("wb") as f:
        writer.write(f)


def test_find_forbidden_dashes_detects_em_dash_nested():
    content = {
        "name": "ok",
        "experience": [{"highlights": [{"text": "Led team—shipped fast"}]}],
    }
    findings = checks.find_forbidden_dashes(content)
    assert len(findings) == 1
    assert "em dash" in findings[0]


def test_find_forbidden_dashes_allows_en_dash():
    # en dash is a legitimate range separator, handled by the renderer
    assert checks.find_forbidden_dashes({"dates": "2023–2024"}) == []


def test_page_check_ok_for_one_page(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 1)
    res = checks.page_check(pdf, max_pages=1)
    assert res["ok"] is True
    assert res["pages"] == 1


def test_page_check_fails_for_two_pages(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 2)
    res = checks.page_check(pdf, max_pages=1)
    assert res["ok"] is False
    assert res["pages"] == 2
    assert "CUT" in res["message"]


def test_page_check_no_target_ignores_underfill(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 1)
    res = checks.page_check(pdf, max_pages=2)  # no target_pages configured
    assert res["ok"] is True
    assert "target_pages" not in res


def test_page_check_flags_underfill_against_target(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 1)
    res = checks.page_check(pdf, max_pages=2, target_pages=2)
    assert res["ok"] is False
    assert res["pages"] == 1
    assert res["target_pages"] == 2
    # Underfill must push toward ADDING real entries, never toward padding.
    assert "ADD" in res["message"]
    assert "pad" in res["message"].lower()


def test_page_check_ok_when_target_met(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 2)
    res = checks.page_check(pdf, max_pages=2, target_pages=2)
    assert res["ok"] is True


def test_page_check_overflow_wins_over_target(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 3)
    res = checks.page_check(pdf, max_pages=2, target_pages=2)
    assert res["ok"] is False
    assert "CUT" in res["message"]


def test_experience_coverage_flags_missing_ids():
    catalogue = {
        "experience": [
            {"id": "a", "title": "Dev"},
            {"id": "b", "title": "Analyst"},
            {"id": "c", "title": "Intern"},
        ]
    }
    content = {"experience": [{"id": "a"}]}
    res = checks.coverage_check(content, catalogue, ["experience"])
    assert res["ok"] is False
    assert res["missing_ids"] == ["b", "c"]
    assert "Analyst" in res["message"]


def test_experience_coverage_ok_when_all_present():
    catalogue = {"experience": [{"id": "a"}, {"id": "b"}]}
    content = {"experience": [{"id": "b"}, {"id": "a"}]}
    res = checks.coverage_check(content, catalogue, ["experience"])
    assert res["ok"] is True
    assert "missing_ids" not in res


def test_experience_coverage_ok_on_empty_catalogue():
    res = checks.coverage_check({"experience": []}, {}, ["experience"])
    assert res["ok"] is True


def test_coverage_check_spans_several_sections():
    # The point of taking a list of sections: a config can demand full coverage
    # of more than just experience.
    catalogue = {
        "experience": [{"id": "a", "title": "Dev"}],
        "education": [{"id": "e1", "degree": "BSc"}, {"id": "e2", "degree": "MSc"}],
    }
    content = {"experience": [{"id": "a"}], "education": [{"id": "e1"}]}
    res = checks.coverage_check(content, catalogue, ["experience", "education"])
    assert res["ok"] is False
    assert res["missing_ids"] == ["e2"]
    assert res["sections"]["experience"]["ok"] is True
    assert res["sections"]["education"]["ok"] is False
    # The message must name the section, not just the id.
    assert "education: e2 (MSc)" in res["message"]


def test_find_banned_phrases_is_case_insensitive_and_reports_path():
    content = {
        "experience": [
            {"highlights": [{"text": "ok"}, {"text": "Tillförde Perspektiv till teamet"}]}
        ]
    }
    findings = checks.find_banned_phrases(content, ["tillförde perspektiv"])
    assert len(findings) == 1
    assert "tillförde perspektiv" in findings[0]
    assert "experience[0].highlights[1].text" in findings[0]


def test_find_banned_phrases_empty_list_is_noop():
    assert checks.find_banned_phrases({"summary": "anything at all"}, []) == []
    assert checks.find_banned_phrases({"summary": "anything at all"}, None) == []


def test_find_banned_phrases_matches_substring_in_longer_text():
    findings = checks.find_banned_phrases(
        {"summary": "Kandidaten har gedigen kompetens inom analys."},
        ["gedigen kompetens", "kvalificerat stöd"],
    )
    assert len(findings) == 1
    assert "summary" in findings[0]


def test_ats_check_flags_missing_name(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 1)  # blank page -> no extractable text
    res = checks.ats_check(pdf, {"name": "Ada Lovelace"})
    assert res["ok"] is False
    assert any("name" in m for m in res["missing_from_extracted_text"])


def test_ats_check_ok_when_nothing_to_verify(tmp_path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, 1)
    res = checks.ats_check(pdf, {})  # no name/email to look for
    assert res["ok"] is True
