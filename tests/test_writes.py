from __future__ import annotations

import json

import pytest

from resume_mcp_server.server import (
    _backup_json,
    _count_entries,
    _guard_destructive_write,
)


def test_count_entries_sums_list_sections():
    pi = {
        "name": "x",
        "experience": [1, 2, 3],
        "projects": [1, 1],
        "skills": {"languages": ["a"]},  # dict, not counted
    }
    assert _count_entries(pi) == 5


def test_guard_allows_small_shrink():
    old = {"experience": list(range(10))}
    new = {"experience": list(range(8))}  # dropped 20% -> allowed
    _guard_destructive_write(old, new, force=False)  # no raise


def test_guard_refuses_large_shrink():
    old = {"experience": list(range(10)), "projects": list(range(4))}
    new = {"experience": list(range(3))}  # 14 -> 3, way over 30%
    with pytest.raises(ValueError, match="Refusing write"):
        _guard_destructive_write(old, new, force=False)


def test_guard_force_overrides():
    old = {"experience": list(range(10))}
    new = {"experience": []}
    _guard_destructive_write(old, new, force=True)  # no raise


def test_guard_noop_when_old_empty():
    _guard_destructive_write({}, {}, force=False)  # no raise


def test_backup_json_copies_existing(tmp_path):
    src = tmp_path / "personal_info.json"
    src.write_text(json.dumps({"name": "orig"}), encoding="utf-8")
    dest = _backup_json(src)
    assert dest is not None
    assert dest.parent.name == "backups"
    assert json.loads(dest.read_text(encoding="utf-8")) == {"name": "orig"}


def test_backup_json_none_when_missing(tmp_path):
    assert _backup_json(tmp_path / "does_not_exist.json") is None
