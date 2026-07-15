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
                "name": "Test",
                "projects": [
                    {"id": "alpha", "name": "Alpha", "highlights": []},
                    {"id": "beta", "name": "Beta", "highlights": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    return pi_path


def _load(pi_path):
    return json.loads(pi_path.read_text(encoding="utf-8"))


def test_add_entry_appends_and_derives_id(seeded):
    res = server.add_entry("projects", {"name": "Gamma Project"})
    assert res["count"] == 3
    assert res["added"]["id"] == "gamma-project"
    assert len(_load(seeded)["projects"]) == 3


def test_add_entry_creates_missing_section(seeded):
    server.add_entry("competitions", {"id": "imo", "name": "IMO"})
    assert _load(seeded)["competitions"][0]["id"] == "imo"


def test_patch_entry_shallow_merges(seeded):
    server.patch_entry("projects", "alpha", {"name": "Alpha Prime"})
    projects = _load(seeded)["projects"]
    alpha = next(p for p in projects if p["id"] == "alpha")
    assert alpha["name"] == "Alpha Prime"
    assert "highlights" in alpha  # untouched key preserved


def test_patch_entry_unknown_id_raises(seeded):
    with pytest.raises(ValueError, match="no entry with id"):
        server.patch_entry("projects", "nope", {"name": "x"})


def test_delete_entry_removes_one(seeded):
    res = server.delete_entry("projects", "alpha")
    assert res["deleted"]["id"] == "alpha"
    ids = [p["id"] for p in _load(seeded)["projects"]]
    assert ids == ["beta"]


def test_delete_entry_writes_backup(seeded):
    server.delete_entry("projects", "alpha")
    backups = list((seeded.parent / "backups").glob("personal_info.*.json"))
    assert backups, "a backup should be written before the delete"
