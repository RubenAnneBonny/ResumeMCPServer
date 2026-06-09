# Resume MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that turns a verbose personal-info catalogue into a tailored, JD-specific resume PDF. The server's job is to expose well-shaped data, validate writes, render a Jinja2 LaTeX template, and compile it via [Tectonic](https://tectonic-typesetting.github.io). The *tailoring* — picking which jobs/projects/bullets matter for a given job description, and rewriting them — happens in the LLM.

Works with any MCP-capable client: Claude Code, Claude Desktop, Cursor, Continue, Cline, Zed, or anything built on the official MCP SDKs.

## How it's structured

- `data/personal_info.json` — your full catalogue (every job, project, competition, every bullet you might ever want). Verbose by design. **Gitignored** — this file holds your real data.
- `data/personal_info.example.json` — committed dummy data. On first run, copied to `personal_info.json` if it's missing.
- `data/ui_guidelines.json` — style knobs: fonts, accent colour, margins, voice (person/tense). Committed.
- `templates/resume.tex.j2` — the single Jinja2 LaTeX template. Generic placeholders only.
- `output/` — generated `.tex` and `.pdf` files. **Gitignored**.

## First-run setup

1. Install **uv** (Python package/runtime manager):
   - Windows: `winget install astral-sh.uv`
   - macOS / Linux: see [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)
2. Install **Tectonic** (LaTeX → PDF):
   - Windows: `winget install TectonicTypesetting.Tectonic`
   - macOS: `brew install tectonic`
   - Linux: see [tectonic-typesetting.github.io](https://tectonic-typesetting.github.io)
   - The first compile downloads LaTeX packages — slow once, then cached.
3. From the repo root: `uv sync`
4. Edit `data/personal_info.json` with your real content. (It's auto-created from the example on first use.)
5. Edit `data/ui_guidelines.json` to taste, or leave defaults.
6. Wire up your MCP client (see below).
7. Ask it: *"Generate a resume tailored to this JD: …"*

## MCP client configuration

The server speaks stdio MCP. Any MCP-capable client can launch it. Replace `<ABS_PATH>` with the absolute path to this repo.

### Claude Code

A `.mcp.json` is bundled at the repo root. Open this directory in Claude Code and approve the `resume` server when prompted. No further config needed.

### Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "resume": {
      "command": "uv",
      "args": ["run", "--directory", "<ABS_PATH>", "resume-mcp-server"]
    }
  }
}
```

### Cursor

Edit `~/.cursor/mcp.json` (or `.cursor/mcp.json` per-project) — same shape as above.

### Continue

In `~/.continue/config.yaml`:

```yaml
mcpServers:
  - name: resume
    command: uv
    args: ["run", "--directory", "<ABS_PATH>", "resume-mcp-server"]
```

### ChatGPT Desktop

Requires the **ChatGPT desktop app** (Windows or macOS) and a **ChatGPT Plus / Pro subscription**. The browser-only web app does not support local MCP servers.

OpenAI's desktop app reads MCP servers from a JSON config file. The exact path has changed between app releases — open **Settings → Beta features** (or **Connected tools**) in the app to find the current config location, or check [OpenAI's MCP documentation](https://platform.openai.com/docs/mcp). The content follows the same shape as Claude Desktop:

```json
{
  "mcpServers": {
    "resume": {
      "command": "uv",
      "args": ["run", "--directory", "<ABS_PATH>", "resume-mcp-server"]
    }
  }
}
```

Restart the desktop app after saving. The `resume` tools will appear in the tool picker (paperclip / tools icon) in a new chat.

> **Note:** ChatGPT cannot open or preview local PDF files — `generate_resume` will still run and report the output path, but you will need to open the PDF yourself. All text-based tools (`get_personal_info`, `get_resume_schema`, `research_company`, etc.) work normally.

### Cline / Zed / others

Every MCP client documents a config block taking a `command` plus `args`. Use:

```
command: uv
args:    run --directory <ABS_PATH> resume-mcp-server
```

### Custom client (Python / TypeScript SDK)

Spawn the server directly via stdio using the official `@modelcontextprotocol/sdk` (TS) or `mcp` (Python) package; same command/args.

## Tools exposed

| Tool | Purpose |
|---|---|
| `get_personal_info()` | Return the full catalogue. |
| `get_ui_guidelines()` | Return the current style knobs. |
| `update_personal_info(content)` | Whole-file write. Validated; atomic. |
| `update_ui_guidelines(content)` | Whole-file write. Validated; atomic. |
| `get_resume_schema()` | Returns the expected shape for `generate_resume`'s `content`, plus the mandatory critical-tailoring guidance. |
| `get_relevance_review_prompt(company, job_description)` | Build the pre-generation recruiter ranking prompt (embeds the full catalogue). Run it in a fresh sub-agent to score every entry 0–5. |
| `generate_resume(name, content, compile=True)` | Render `.tex`, optionally compile to `.pdf`. Returns paths and any compiler output. |
| `get_resume_critique_prompt(name, company, job_description)` | Build the post-generation recruiter critique prompt (embeds the rendered `.tex`). Run it in a fresh sub-agent for missing keywords + per-item feedback + gaps worth interviewing about. |
| `get_interview_prompt(section, target_id, topic, company, job_description, focus)` | Build a prompt to interview the user and enrich one catalogue entry (refine or create). Run it **yourself in the conversation** (not a sub-agent) — drops weak answers, saves on approval. General by default; targeted when job context is passed. |
| `list_resumes()` | List previously generated outputs. |
| `check_environment()` | Diagnostics: are required files present, is Tectonic installed. |

## Privacy / public-repo hygiene

This repo is meant to be public. Real content lives only on your machine.

**Tracked:**
- `data/personal_info.example.json` — dummy data only.
- `data/ui_guidelines.json` — style knobs, no personal data.
- `templates/resume.tex.j2` — generic placeholders only.
- All source code, `pyproject.toml`, `README.md`, `.mcp.json`.

**Gitignored:**
- `data/personal_info.json` — the real catalogue.
- `output/` — rendered `.tex` and `.pdf` files contain personal data.
- `.venv/`, `__pycache__/`, `.tectonic-cache/`, etc.

Always run `git status` before pushing — if anything from `data/` or `output/` shows up unexpectedly, stop and investigate.

## Tailoring model (how the agent uses this)

`personal_info.json` is the **complete catalogue** — intentionally larger than any single resume. For a given JD, the agent makes two independent decisions:

1. **Item selection per section.** From each section, pick the items most relevant to the JD. Counts are agent-driven by relevance, not hardcoded.
2. **Bullet selection + rewriting.** For each item that *was* selected, pick the 2–4 highlights most relevant to the JD and rewrite them to match `ui_guidelines.voice` and the language of the JD.

`narrative` fields exist as background context for the agent only — they should never be copied verbatim into the resume.

## Critical tailoring loop (recruiter reviews)

To stop the agent from being a "yes-sayer" that includes irrelevant entries — or, just as bad, silently **leaves off something valuable** — two skeptical-recruiter reviews bracket generation. The check is symmetric: cut the weak **and** force-include the strong. Both reviews run as the **client's own fresh sub-agents** (e.g. Claude Code's Task tool) with no inherited context — so they're genuinely independent. **The server never calls an LLM**, so there's no API key and no extra cost beyond your normal client/subscription.

1. **Rank (before selecting).** Call `get_relevance_review_prompt(company, job_description)` and run the returned prompt in a fresh sub-agent. A recruiter for that company scores every catalogue entry 0–5 against the job, marks the **must-includes**, and flags the low scorers to cut.
2. **Generate.** Select and rewrite content using those rankings, then call `generate_resume(name, content)`.
3. **Critique (after writing).** Call `get_resume_critique_prompt(name, company, job_description)` and run it in a fresh sub-agent. It sees the **full catalogue and the rendered resume**, so it lists valuable entries you **wrongly omitted** (by `id`), the top‑5 missing keywords, and per‑item good/bad.
4. **Revise.** Add every wrongly-omitted entry, fix the keywords and per-item issues, and call `generate_resume` again. Repeat 3–4 until the **"Wrongly omitted" section comes back empty** and the critique is clean.

The omission check is the safety net that makes it hard to drop something valuable: the post-write critic compares what's on the page against the entire catalogue and names anything strong that's missing, by `id`, so the main agent can add it back deterministically.

The full workflow is also returned by `get_resume_schema()`. In Claude Code, a `PostToolUse` hook (`.claude/settings.json` → `scripts/post_generate_reminder.py`) fires after `generate_resume` to remind the agent to run the critique, so step 3 doesn't get skipped. The persona and prompt wording live in `src/resume_mcp_server/critic.py` if you want to tune how tough the recruiter is.
