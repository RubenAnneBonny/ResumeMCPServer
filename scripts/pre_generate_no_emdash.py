"""PreToolUse hook for the `resume` MCP server's generate_resume tool.

Claude Code runs this BEFORE every `mcp__resume__generate_resume` call. It scans
the resume content for two things and DENIES the call if it finds either:

1. Em-dashes and related long dashes. These have no glyph in the cmr/cfr-lm
   fonts and have repeatedly broken the Tectonic compile; they also read poorly
   on a resume.
2. Any phrase listed in ui_guidelines.voice.banned_phrases (case-insensitive) —
   the user's own pet phrases (committee-speak, padding). Absent/empty = no-op.

The server rejects both too (see checks.find_forbidden_dashes /
checks.find_banned_phrases) — this hook is an early, Claude-Code-only nicety
that keeps them out before the tool call even runs.

Output contract: print a JSON object on stdout whose
`hookSpecificOutput.permissionDecision` is "deny" (with a reason) to block the
call, or nothing to let it through.
"""

import json
import os
import sys
from pathlib import Path

# Kept in sync with checks.FORBIDDEN_DASHES on the server. En dash (U+2013) is
# intentionally allowed as a range separator.
FORBIDDEN_DASHES = ("—", "―", "‒", "⸺", "⸻")

DASH_REASON = (
    "This resume content contains em-dashes (or related long dashes), which break "
    "the Tectonic PDF compile and read poorly on a resume. Rewrite the affected "
    "bullets WITHOUT them (use a comma, colon, parentheses, or two separate "
    "sentences) and call generate_resume again."
)


def _ui_guidelines() -> dict:
    """Load the active ui_guidelines.json. RESUME_MCP_ROOT wins (it can point
    data/ outside the repo); CLAUDE_PROJECT_DIR is the fallback — same
    resolution order as post_generate_guidelines_reminder.py."""
    root = os.environ.get("RESUME_MCP_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    try:
        with (Path(root) / "data" / "ui_guidelines.json").open(
            "r", encoding="utf-8"
        ) as f:
            return json.load(f)
    except Exception:
        return {}


def _banned_phrases() -> list:
    voice = _ui_guidelines().get("voice") or {}
    raw = voice.get("banned_phrases")
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, str) and p.strip()]
    return []


def _find_dashes(blob: str) -> bool:
    return any(d in blob for d in FORBIDDEN_DASHES)


def _find_banned(blob: str) -> list:
    lowered = blob.lower()
    return [p for p in _banned_phrases() if p.lower() in lowered]


def _deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _read_payload() -> dict:
    """Parse the hook payload from stdin, decoding it as UTF-8 explicitly.

    Do NOT use sys.stdin.read(): on Windows it decodes with the locale codec
    (cp1252), which silently mangles the very characters this hook exists to
    catch — an em-dash arrives as mojibake and the substring test misses it.
    Reading the raw buffer keeps the check working on every platform, and
    matters just as much for non-ASCII banned phrases (e.g. "kvalificerat stöd").
    """
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")
    except Exception:
        # If we can't parse the payload, don't block — fail open.
        return {}


def main() -> None:
    payload = _read_payload()

    # One flattened blob of the whole (nested) tool input: both checks are
    # substring matches, so structure doesn't matter here. The server reports
    # the precise field path when it re-checks.
    blob = json.dumps(payload.get("tool_input") or {}, ensure_ascii=False)

    if _find_dashes(blob):
        _deny(DASH_REASON)
        return

    banned = _find_banned(blob)
    if banned:
        listed = ", ".join(repr(p) for p in banned)
        _deny(
            f"This resume content contains {len(banned)} phrase(s) banned by "
            f"ui_guidelines.voice.banned_phrases: {listed}. Rewrite the affected "
            "text with concrete, specific wording (say what was actually done, "
            "with real detail) and call generate_resume again."
        )


if __name__ == "__main__":
    main()
