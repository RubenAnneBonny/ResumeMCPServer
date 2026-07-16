from __future__ import annotations

import pytest
from pydantic import ValidationError

from resume_mcp_server.schemas import (
    PersonalInfo,
    validate_personal_info,
    validate_ui_guidelines,
)


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


def test_personal_info_models_voluntary_work_and_languages():
    # Both render, so both must be in the schema get_resume_schema hands the
    # agent — they were silently missing while extra="allow" carried them.
    schema = PersonalInfo.model_json_schema()
    assert "voluntary_work" in schema["properties"]
    assert "languages" in schema["properties"]
    pi = validate_personal_info({
        "name": "Ada",
        "voluntary_work": [{"id": "v", "title": "Mentor", "organization": "Org"}],
        "languages": [{"language": "Swedish", "proficiency": "Native"}],
    })
    assert pi["voluntary_work"][0]["organization"] == "Org"
    assert pi["languages"][0]["proficiency"] == "Native"


# --------------------------------------------------------------------------
# ui_guidelines.sections
# --------------------------------------------------------------------------

VALID_SECTION = {
    "key": "experience",
    "blocks": [{"source": "experience", "kind": "entries", "fields": {"bold": ["title"]}}],
}


def test_ui_guidelines_absent_sections_stays_absent():
    # None means "synthesize the defaults". Writing `"sections": null` back into
    # a hand-edited config would read as a mistake, so exclude_none drops it.
    ui = validate_ui_guidelines({})
    assert "sections" not in ui


def test_ui_guidelines_round_trips_a_custom_sections_list():
    ui = validate_ui_guidelines({"sections": [VALID_SECTION]})
    section = ui["sections"][0]
    assert section["key"] == "experience"
    assert section["blocks"][0]["source"] == "experience"
    # Unset defaults are filled so the StrictUndefined template can't trip.
    assert section["space_after"] == "-16pt"
    assert section["blocks"][0]["fields"]["italic_sep"] == ", "
    # An unset title stays out rather than becoming null.
    assert "title" not in section


def test_ui_guidelines_keeps_an_explicitly_empty_sections_list():
    # [] must survive as [] — it means "render nothing", not "use the defaults".
    assert validate_ui_guidelines({"sections": []})["sections"] == []


def test_ui_guidelines_rejects_unknown_section_kind():
    bad = {"key": "x", "blocks": [{"source": "x", "kind": "bogus"}]}
    with pytest.raises(ValidationError):
        validate_ui_guidelines({"sections": [bad]})


def test_ui_guidelines_rejects_section_with_no_blocks():
    with pytest.raises(ValidationError):
        validate_ui_guidelines({"sections": [{"key": "x", "blocks": []}]})


def test_ui_guidelines_rejects_block_with_no_source():
    with pytest.raises(ValidationError):
        validate_ui_guidelines({"sections": [{"key": "x", "blocks": [{"kind": "entries"}]}]})
