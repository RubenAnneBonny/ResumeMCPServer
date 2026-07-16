"""PostToolUse hook for the `resume` MCP server's generate_resume tool.

Runs after a resume .tex/.pdf is generated, alongside the critique reminder. It
reads the active ui_guidelines and reminds the agent to confirm the rendered
resume actually honors them before finishing — the style knobs the AGENT (not
the template) controls: voice and the page-length limit. Reminder only; it runs
no checks and calls no LLM.

Output contract: print a JSON object on stdout whose
`hookSpecificOutput.additionalContext` is fed back to the model as context.
"""

import json
import os
import sys
from pathlib import Path


def _ui_guidelines() -> dict:
    root = os.environ.get("RESUME_MCP_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    path = Path(root) / "data" / "ui_guidelines.json"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _build_reminder() -> str:
    ui = _ui_guidelines()
    voice = ui.get("voice", {})
    page = ui.get("page") or {}
    max_pages = page.get("max_pages")
    target_pages = page.get("target_pages")

    voice_line = json.dumps(voice, ensure_ascii=False) if voice else "(see ui_guidelines)"
    pages_line = str(max_pages) if max_pages is not None else "(see ui_guidelines)"

    if target_pages is not None:
        length_line = (
            f"2) LENGTH: target_pages = {target_pages}, max_pages = {pages_line}. "
            "Open the PDF and count pages. Over the max: use the critique's 'Cut "
            "or trim' output to remove the weakest lines. UNDER the target: you "
            "are wasting the page — ADD the next-highest-relevance entries from "
            "the relevance review or expand existing highlights, but never pad "
            "with fluff or unsupported claims. Either way, do NOT shrink or "
            "stretch fonts/margins; regenerate instead.\n"
        )
    else:
        length_line = (
            f"2) LENGTH: max_pages = {pages_line}. Open the PDF and count pages. If it "
            "overflows, use the critique's 'Cut or trim' output to remove the weakest "
            "lines (do NOT shrink fonts/margins) and regenerate.\n"
        )

    extra = ""
    if (ui.get("selection") or {}).get("include_all_experience"):
        extra += (
            "3) COVERAGE: selection.include_all_experience is ON — EVERY job in "
            "the catalogue must appear. Older roles may be compressed to "
            "title/company/dates with 0-1 bullets, but never dropped. Check the "
            "selection_check in the generate_resume result.\n"
        )
    banned = (voice or {}).get("banned_phrases") or []
    if banned:
        extra += (
            f"4) BANNED PHRASES: {json.dumps(banned, ensure_ascii=False)} are "
            "rejected server-side anywhere in the content. Keep the wording "
            "concrete and specific.\n"
        )

    return (
        "Before you call the resume finished, verify the rendered PDF actually "
        "honors ui_guidelines — these are the parts YOU control, not the "
        "template:\n"
        f"1) VOICE: {voice_line}. Confirm every bullet obeys it — no personal "
        "pronouns, past tense, strong action verbs, and NO em-dashes (—).\n"
        f"{length_line}"
        f"{extra}"
        "If anything is off, fix the content and call generate_resume again."
    )


def main() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": _build_reminder(),
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
