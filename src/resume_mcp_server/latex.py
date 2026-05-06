from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from resume_mcp_server.paths import OUTPUT_DIR


@dataclass
class CompileResult:
    ok: bool
    pdf_path: Path | None
    log_path: Path | None
    stdout: str
    stderr: str
    error: str | None


def tectonic_available() -> bool:
    return shutil.which("tectonic") is not None


def compile_tex(tex_path: Path) -> CompileResult:
    if not tectonic_available():
        return CompileResult(
            ok=False,
            pdf_path=None,
            log_path=None,
            stdout="",
            stderr="",
            error=(
                "tectonic was not found on PATH. Install it with "
                "'winget install TectonicTypesetting.Tectonic' "
                "(or see https://tectonic-typesetting.github.io). "
                "JSON read/write tools still work without it."
            ),
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [
            "tectonic",
            "--outdir",
            str(OUTPUT_DIR),
            str(tex_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    pdf_path = OUTPUT_DIR / (tex_path.stem + ".pdf")

    if proc.returncode == 0 and pdf_path.exists():
        return CompileResult(
            ok=True,
            pdf_path=pdf_path,
            log_path=None,
            stdout=proc.stdout,
            stderr=proc.stderr,
            error=None,
        )

    return CompileResult(
        ok=False,
        pdf_path=None,
        log_path=None,
        stdout=proc.stdout,
        stderr=proc.stderr,
        error=f"tectonic exited with code {proc.returncode}",
    )
