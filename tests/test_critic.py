"""Tests for the sub-agent prompt builders.

These guard two things that are easy to break silently: the catalogue payload
handed to a reviewer (tags out, narrative in) and the cache-friendly ordering
that makes the three sub-agent prompts share a prefix.
"""

from __future__ import annotations

import json

from resume_mcp_server.critic import (
    _CATALOGUE_HEADER,
    build_final_review_prompt,
    build_qualification_check_prompt,
    build_relevance_review_prompt,
    build_resume_critique_prompt,
)

CATALOGUE = {
    "name": "Ada",
    "experience": [
        {
            "id": "job-a",
            "title": "Dev",
            "narrative": "Owned the pricing service end to end.",
            "highlights": [
                {"text": "Cut latency 40%", "tags": ["perf", "backend"]},
                {"text": "Mentored two interns", "tags": ["leadership"]},
            ],
        }
    ],
    "projects": [{"id": "p1", "name": "Solver", "tags": ["math"]}],
}

JD = "Build low-latency systems."
COMPANY = "Acme"


def _prompts() -> list[str]:
    return [
        build_relevance_review_prompt(COMPANY, JD, CATALOGUE),
        build_resume_critique_prompt(COMPANY, JD, "\\section{Experience}", CATALOGUE),
        build_qualification_check_prompt([{"id": "1", "headline": "Dev"}], CATALOGUE),
    ]


def test_tags_are_stripped_from_every_catalogue_prompt():
    # tags are selection metadata for the main agent, not recruiter evidence.
    for prompt in _prompts():
        assert '"tags"' not in prompt
        assert "leadership" not in prompt
        assert "backend" not in prompt


def test_narrative_is_kept_as_evidence():
    # The honesty gate needs narrative to tell a supported claim from an
    # invented one — stripping it would break the critique.
    for prompt in _prompts():
        assert "Owned the pricing service end to end." in prompt


def test_stripping_does_not_mutate_the_caller_s_catalogue():
    before = json.dumps(CATALOGUE, sort_keys=True)
    build_relevance_review_prompt(COMPANY, JD, CATALOGUE)
    assert json.dumps(CATALOGUE, sort_keys=True) == before


def test_catalogue_json_is_compact():
    prompt = build_relevance_review_prompt(COMPANY, JD, CATALOGUE)
    assert '"name":"Ada"' in prompt  # compact separators, not indent=2
    assert '"name": "Ada"' not in prompt


def test_every_catalogue_prompt_starts_with_the_identical_block():
    # The point of the ordering: a byte-identical prefix across sub-agent calls
    # is what lets prompt caching hit. Persona/task come after.
    prompts = _prompts()
    for prompt in prompts:
        assert prompt.startswith(_CATALOGUE_HEADER)
    prefix = prompts[0].split("```", 2)[:2]
    for prompt in prompts[1:]:
        assert prompt.split("```", 2)[:2] == prefix


def test_untrusted_markers_survive_the_reorder():
    for prompt in (
        build_relevance_review_prompt(COMPANY, JD, CATALOGUE),
        build_resume_critique_prompt(COMPANY, JD, "tex", CATALOGUE),
    ):
        assert "<untrusted_job_text>" in prompt
        assert "</untrusted_job_text>" in prompt
        assert "UNTRUSTED data from an external ad" in prompt
    # The qualification prompt wraps job JSON, not a JD, but keeps the note.
    assert "UNTRUSTED data from an external ad" in build_qualification_check_prompt(
        [{"id": "1"}], CATALOGUE
    )


def test_final_review_prompt_covers_all_three_passes():
    prompt = build_final_review_prompt(COMPANY, JD, "Ada Lovelace\nEngineer")
    for marker in ("## SKIM", "## RED FLAGS", "## PROOFREAD"):
        assert marker in prompt
    assert "6-second skim" in prompt or "~6-second skim" in prompt
    assert "Ada Lovelace" in prompt
    # The skim is only meaningful before a careful read, so the ordering
    # instruction must survive any future edit to this prompt.
    assert "IN ORDER" in prompt


def test_final_review_prompt_handles_missing_job_description():
    prompt = build_final_review_prompt("", "", "resume text")
    assert "the company" in prompt
    assert "(no job description provided)" in prompt
