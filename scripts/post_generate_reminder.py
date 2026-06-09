"""PostToolUse hook for the `resume` MCP server's generate_resume tool.

Claude Code runs this after every successful `mcp__resume__generate_resume`
call. It injects a reminder forcing the post-write recruiter critique so the
step can't be silently skipped. It does NOT call an LLM — the actual critique
runs as a fresh sub-agent on the user's own subscription.

Output contract: print a JSON object on stdout whose
`hookSpecificOutput.additionalContext` is fed back to the model as context.
"""

import json
import sys

REMINDER = (
    "A resume .tex was just generated. Before you finish, you MUST run the "
    "post-write recruiter critique (do not skip it):\n"
    "1) Call mcp__resume__get_resume_critique_prompt(name, company, "
    "job_description) for the resume you just generated.\n"
    "2) Run the returned prompt in a FRESH sub-agent (e.g. the Task tool, no "
    "inherited context). It compares the resume against the full catalogue and "
    "reports valuable entries you wrongly OMITTED, missing keywords, and "
    "per-item feedback.\n"
    "3) ADD every wrongly-omitted entry it flags, fix the missing keywords and "
    "per-item issues, then call generate_resume again. Repeat until the "
    "'Wrongly omitted' section comes back empty."
)


def main() -> None:
    # Claude Code passes the hook payload as JSON on stdin; we don't need it,
    # but read it so the pipe closes cleanly.
    try:
        sys.stdin.read()
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": REMINDER,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
