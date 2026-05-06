from __future__ import annotations

import os
from pathlib import Path


def _repo_root() -> Path:
    env = os.environ.get("RESUME_MCP_ROOT")
    if env:
        return Path(env).resolve()
    # src/resume_mcp_server/paths.py -> repo root is three parents up
    return Path(__file__).resolve().parents[2]


REPO_ROOT: Path = _repo_root()
DATA_DIR: Path = REPO_ROOT / "data"
TEMPLATES_DIR: Path = REPO_ROOT / "templates"
OUTPUT_DIR: Path = REPO_ROOT / "output"

PERSONAL_INFO_PATH: Path = DATA_DIR / "personal_info.json"
PERSONAL_INFO_EXAMPLE_PATH: Path = DATA_DIR / "personal_info.example.json"
UI_GUIDELINES_PATH: Path = DATA_DIR / "ui_guidelines.json"
RESUME_TEMPLATE_PATH: Path = TEMPLATES_DIR / "resume.tex.j2"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
