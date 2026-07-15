"""PreToolUse hook for the `resume` MCP server's generate_resume tool.

Claude Code runs this BEFORE every `mcp__resume__generate_resume` call. It scans
the resume content for em-dashes and related long dashes and, if it finds any,
DENIES the call with a reason telling the agent to rewrite without them. These
have no glyph in the cmr/cfr-lm fonts and have repeatedly broken the Tectonic
compile; they also read poorly on a resume. The server rejects them too (see
checks.FORBIDDEN_DASHES) — this hook is an early, Claude-Code-only nicety that
keeps them out of the content before the tool call even runs.

Output contract: print a JSON object on stdout whose
`hookSpecificOutput.permissionDecision` is "deny" (with a reason) to block the
call, or nothing to let it through.
"""

import json
import sys

# Kept in sync with checks.FORBIDDEN_DASHES on the server. En dash (U+2013) is
# intentionally allowed as a range separator.
FORBIDDEN_DASHES = ("—", "―", "‒", "⸺", "⸻")

REASON = (
    "This resume content contains em-dashes (or related long dashes), which break "
    "the Tectonic PDF compile and read poorly on a resume. Rewrite the affected "
    "bullets WITHOUT them (use a comma, colon, parentheses, or two separate "
    "sentences) and call generate_resume again."
)


def _has_em_dash(value) -> bool:
    """True if any forbidden dash appears anywhere in the (nested) tool input."""
    blob = json.dumps(value, ensure_ascii=False)
    return any(d in blob for d in FORBIDDEN_DASHES)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        # If we can't parse the payload, don't block — fail open.
        return

    tool_input = payload.get("tool_input") or {}
    if not _has_em_dash(tool_input):
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
