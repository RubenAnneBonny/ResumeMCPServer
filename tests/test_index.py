from __future__ import annotations

import json

import pytest

from resume_mcp_server import paths, server


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    pi_path = data_dir / "personal_info.json"
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(paths, "PERSONAL_INFO_PATH", pi_path)
    monkeypatch.setattr(paths, "PERSONAL_INFO_EXAMPLE_PATH", data_dir / "missing.json")
    pi_path.write_text(
        json.dumps(
            {
                "name": "Test Candidate",
                "title": "Engineer",
                "summary": "Does things.",
                "projects": [
                    {
                        "id": "alpha",
                        "name": "Alpha",
                        "narrative": "First sentence. Second sentence.",
                        "highlights": [{"text": "Built X"}],
                    },
                    {
                        "id": "beta",
                        "name": "Beta",
                        "highlights": [{"text": "Shipped Y fast"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return pi_path


def test_index_is_compact(seeded):
    idx = server.get_catalogue_index()
    assert idx["name"] == "Test Candidate"
    rows = idx["sections"]["projects"]
    assert {r["id"] for r in rows} == {"alpha", "beta"}
    # one-liner comes from narrative first sentence, else first highlight
    alpha = next(r for r in rows if r["id"] == "alpha")
    beta = next(r for r in rows if r["id"] == "beta")
    assert alpha["summary"] == "First sentence."
    assert beta["summary"] == "Shipped Y fast"
    # index rows carry no highlights/narrative bulk
    assert "highlights" not in alpha


def test_get_entries_returns_full_and_reports_missing(seeded):
    res = server.get_entries(["alpha", "ghost"])
    assert res["missing"] == ["ghost"]
    projects = res["entries"]["projects"]
    assert len(projects) == 1
    assert projects[0]["highlights"] == [{"text": "Built X"}]
