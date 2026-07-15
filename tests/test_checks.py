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
