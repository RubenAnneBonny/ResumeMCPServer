from __future__ import annotations

import pytest

from resume_mcp_server import paths, state


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    # Redirect the state dir (output/.state) to a tmp dir so tests never touch
    # the real output/ folder.
    monkeypatch.setattr(paths, "OUTPUT_DIR", tmp_path / "output")


def test_job_key_is_whitespace_and_case_insensitive():
    a = state.job_key("Acme Corp", "Build   things\nfast")
    b = state.job_key("acme corp", "build things fast")
    assert a == b


def test_relevance_review_roundtrip():
    company, jd = "Acme", "Do X"
    assert not state.has_relevance_review(company, jd)
    state.record_relevance_review(company, jd, "scores: ...")
    assert state.has_relevance_review(company, jd)


def test_critique_is_per_name():
    company, jd = "Acme", "Do X"
    state.record_critique("resume_a", company, jd, "findings a")
    assert state.has_critique("resume_a", company, jd)
    assert not state.has_critique("resume_b", company, jd)


def test_generate_resume_blocked_without_review(monkeypatch):
    from resume_mcp_server import server

    with pytest.raises(ValueError, match="blocked: no relevance review"):
        server.generate_resume(
            name="acme_swe",
            content={"name": "X"},
            company="Acme",
            job_description="Do X",
            compile_pdf=False,
        )


def test_finalize_resume_blocked_without_critique():
    from resume_mcp_server import server

    with pytest.raises(ValueError, match="blocked: no critique"):
        server.finalize_resume("acme_swe", "Acme", "Do X")
