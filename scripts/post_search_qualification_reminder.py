"""PostToolUse hook for the `resume` MCP server's search_platsbanken tool.

Claude Code runs this after every successful `mcp__resume__search_platsbanken`
call. It injects a reminder forcing the qualification gate so the agent cannot
recommend a job without first checking we actually meet its STATED requirements.
It does NOT call an LLM — the qualification check itself runs as a fresh sub-agent
on the user's own subscription.

Output contract: print a JSON object on stdout whose
`hookSpecificOutput.additionalContext` is fed back to the model as context.
"""

import json
import sys

REMINDER = (
    "Job ads were just retrieved from Platsbanken. These are CANDIDATES, not "
    "recommendations. Before you recommend ANY of them to the user, you MUST run "
    "the qualification gate — do not skip it:\n"
    "1) (Optional) Call mcp__resume__get_job_ad(id) on promising hits to get the "
    "full requirements text.\n"
    "2) Call mcp__resume__get_qualification_check_prompt(jobs) with the candidate "
    "jobs.\n"
    "3) Run the returned prompt in a FRESH sub-agent (e.g. the Task tool, no "
    "inherited context). It judges, requirement by requirement, whether the "
    "candidate meets each job's STATED requirements. Qualified means meeting the "
    "stated requirements — NOT likelihood of being hired.\n"
    "4) Recommend ONLY the jobs it marks QUALIFIED. List NOT QUALIFIED jobs in a "
    "separate section naming the exact missing stated requirement, and flag "
    "UNCERTAIN jobs (unconfirmed hard requirements) for the user to confirm. Never "
    "surface a job as a recommendation before it has passed this check."
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
