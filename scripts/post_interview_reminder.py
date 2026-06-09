"""PostToolUse hook for the `resume` MCP server's get_interview_prompt tool.

Claude Code runs this after every `mcp__resume__get_interview_prompt` call. It
injects a reminder that — unlike the recruiter prompts — this interview is run by
the MAIN agent in the conversation (a sub-agent can't ask the user anything), and
that weak answers must be dropped rather than padded. It does NOT call an LLM.

Output contract: print a JSON object on stdout whose
`hookSpecificOutput.additionalContext` is fed back to the model as context.
"""

import json
import sys

REMINDER = (
    "An interview prompt was just built. Run this interview YOURSELF in this "
    "conversation — do NOT spawn a sub-agent; it has to ask the user questions.\n"
    "1) Ask a few focused questions at a time and react to the answers.\n"
    "2) OMIT PRINCIPLE: drop any thread that doesn't yield concrete, credible, "
    "truthful detail. Never invent numbers, inflate scope, or keep vague filler.\n"
    "3) Synthesize the result into the entry shape and SHOW it for approval.\n"
    "4) On approval, save it: get_personal_info -> replace by `id` (refine) or "
    "append with a new kebab-case `id` (create) -> update_personal_info."
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
