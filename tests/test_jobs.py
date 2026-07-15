from __future__ import annotations

import pytest

from resume_mcp_server.jobs import _location_str, _normalize_hit
from resume_mcp_server.server import _safe_name


def test_safe_name_accepts_valid():
    assert _safe_name("acme_swe-2026") == "acme_swe-2026"


@pytest.mark.parametrize("bad", ["", "has space", "slash/name", "dots.here", "unïcode"])
def test_safe_name_rejects_invalid(bad):
    with pytest.raises(ValueError):
        _safe_name(bad)


def test_location_str_dedupes_and_orders():
    addr = {"city": "Stockholm", "municipality": "Stockholm", "region": "Stockholm", "country": "Sweden"}
    assert _location_str(addr) == "Stockholm, Sweden"


def test_location_str_handles_missing():
    assert _location_str(None) == ""


def test_normalize_hit_truncates_long_description():
    long = "x" * 5000
    hit = {"id": "1", "headline": "Dev", "description": {"text": long}}
    out = _normalize_hit(hit, full_description=False)
    assert len(out["description"]) < 5000
    assert "truncated" in out["description"]


def test_normalize_hit_full_keeps_requirements_blocks():
    hit = {
        "id": "1",
        "description": {"text": "short"},
        "must_have": {"skills": ["python"]},
        "nice_to_have": {"skills": ["rust"]},
    }
    out = _normalize_hit(hit, full_description=True)
    assert out["description"] == "short"
    assert out["must_have"] == {"skills": ["python"]}
    assert out["nice_to_have"] == {"skills": ["rust"]}
