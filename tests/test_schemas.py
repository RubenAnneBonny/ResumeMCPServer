from __future__ import annotations

import pytest

from resume_mcp_server.schemas import validate_personal_info, validate_ui_guidelines


def test_ui_guidelines_defaults_new_dicts():
    ui = validate_ui_guidelines({})
    assert ui["section_titles"] == {}
    assert ui["skill_labels"] == {}
    assert ui["selection"] == {}


def test_ui_guidelines_accepts_target_below_max():
    ui = validate_ui_guidelines({"page": {"max_pages": 2, "target_pages": 2}})
    assert ui["page"]["target_pages"] == 2


def test_ui_guidelines_rejects_target_above_max():
    # target_pages is a floor and max_pages a ceiling: a floor above the ceiling
    # can never be satisfied, so it must be refused at write time.
    with pytest.raises(ValueError, match="cannot exceed"):
        validate_ui_guidelines({"page": {"max_pages": 1, "target_pages": 2}})


def test_ui_guidelines_rejects_target_below_one():
    with pytest.raises(ValueError, match="must be >= 1"):
        validate_ui_guidelines({"page": {"max_pages": 2, "target_pages": 0}})


def test_ui_guidelines_target_defaults_max_pages_to_one():
    # max_pages absent -> the documented default of 1 applies to the comparison.
    with pytest.raises(ValueError, match="cannot exceed"):
        validate_ui_guidelines({"page": {"target_pages": 2}})


def test_ui_guidelines_no_target_is_fine():
    validate_ui_guidelines({"page": {"max_pages": 3}})  # no raise


def test_personal_info_accepts_structured_skills():
    pi = validate_personal_info({"name": "Ada", "skills": {"languages": ["Python"]}})
    assert pi["skills"]["languages"] == ["Python"]


def test_personal_info_accepts_flat_skills_list():
    pi = validate_personal_info({"name": "Ada", "skills": ["Upphandling", "Juridik"]})
    assert pi["skills"] == ["Upphandling", "Juridik"]


def test_personal_info_structured_skills_keeps_extra_keys():
    pi = validate_personal_info({"name": "Ada", "skills": {"algorithms": ["DP"]}})
    assert pi["skills"]["algorithms"] == ["DP"]
