from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from resume_mcp_server.paths import OUTPUT_DIR

# Hard ceiling on a single Tectonic invocation. Without this a hung compile
# would block the MCP tool call indefinitely.
COMPILE_TIMEOUT_SECONDS = 120


@dataclass
class CompileResult:
    ok: bool
    pdf_path: Path | None
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

    try:
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
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return CompileResult(
            ok=False,
            pdf_path=None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error=(
                f"tectonic timed out after {COMPILE_TIMEOUT_SECONDS}s. "
                "The .tex may contain a construct that loops or waits for input."
            ),
        )

    pdf_path = OUTPUT_DIR / (tex_path.stem + ".pdf")

    if proc.returncode == 0 and pdf_path.exists():
        return CompileResult(
            ok=True,
            pdf_path=pdf_path,
            stdout=proc.stdout,
            stderr=proc.stderr,
            error=None,
        )

    return CompileResult(
        ok=False,
        pdf_path=None,
        stdout=proc.stdout,
        stderr=proc.stderr,
        error=f"tectonic exited with code {proc.returncode}",
    )
