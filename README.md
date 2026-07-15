# Resume MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that turns a verbose personal-info catalogue into a tailored, JD-specific resume PDF. The server's job is to expose well-shaped data, validate writes, render a Jinja2 LaTeX template, and compile it via [Tectonic](https://tectonic-typesetting.github.io). The *tailoring* — picking which jobs/projects/bullets matter for a given job description, and rewriting them — happens in the LLM.

Works with any MCP-capable client: Claude Code, Claude Desktop, Cursor, Continue, Cline, Zed, or anything built on the official MCP SDKs.

## How it's structured

- `data/personal_info.json` — your full catalogue (every job, project, competition, every bullet you might ever want). Verbose by design. **Gitignored** — this file holds your real data.
- `data/personal_info.example.json` — committed dummy data. On first run, copied to `personal_info.json` if it's missing.
- `data/ui_guidelines.json` — style knobs: fonts, accent colour, margins, `page.max_pages`, voice (person/tense). **Gitignored**; auto-seeded on first run from `data/ui_guidelines.example.json`.
- `data/ui_guidelines.example.json` — committed defaults; copied to `ui_guidelines.json` if missing.
- `templates/resume.tex.j2` — the single Jinja2 LaTeX template. Generic placeholders only.
- `data/backups/` — timestamped catalogue backups written before every write. **Gitignored**.
- `output/` — generated `.tex` and `.pdf` files. **Gitignored**.

By default everything resolves relative to the repo root. Set the `RESUME_MCP_ROOT` environment variable to point `data/`, `templates/`, and `output/` at a different directory (e.g. a private folder outside the repo).

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

> **Note:** ChatGPT cannot open or preview local PDF files — `generate_resume` will still run and report the output path, but you will need to open the PDF yourself. All text-based tools (`get_personal_info`, `get_catalogue_index`, `get_resume_schema`, etc.) work normally.
>
> The review gates are enforced **server-side** (see below), so the mandatory ranking/critique steps hold even on clients that don't run Claude Code's hooks.

### Cline / Zed / others

Every MCP client documents a config block taking a `command` plus `args`. Use:

```
command: uv
args:    run --directory <ABS_PATH> resume-mcp-server
```

### Custom client (Python / TypeScript SDK)

Spawn the server directly via stdio using the official `@modelcontextprotocol/sdk` (TS) or `mcp` (Python) package; same command/args.

## Tools exposed

**Catalogue read/write**

| Tool | Purpose |
|---|---|
| `get_catalogue_index()` | Compact index: ids, labels, one-line summaries. Start here — it's a fraction of the tokens. |
| `get_entries(ids)` | Full detail for the entries you actually want. |
| `get_personal_info()` | Return the whole catalogue (use when you truly need everything). |
| `get_ui_guidelines()` | Return the current style knobs. |
| `add_entry(section, item)` | Append one entry (id derived if omitted). Backed up; atomic. |
| `patch_entry(section, entry_id, changes)` | Shallow-merge changes into one entry. Backed up; atomic. |
| `delete_entry(section, entry_id)` | Remove one entry by id. Backed up; atomic. |
| `update_personal_info(content, force=False)` | Whole-file write (bulk import/restore). Backed up; refuses to drop >30% of entries without `force`. Prefer the granular tools above. |
| `update_ui_guidelines(content)` | Whole-file write. Validated; atomic. |

**Tailoring loop** (gated — see below)

| Tool | Purpose |
|---|---|
| `get_resume_schema()` | Expected shape for `generate_resume`'s `content`, plus the mandatory tailoring guidance. |
| `get_relevance_review_prompt(company, job_description)` | Build the pre-generation ranking prompt. Run in a fresh sub-agent. |
| `submit_relevance_review(company, job_description, results)` | Register the ranking result. **Unlocks `generate_resume`.** |
| `generate_resume(name, content, company, job_description, compile_pdf=True)` | Render `.tex`, compile `.pdf`. Returns paths, `page_check`, `ats_check`. Gated on a relevance review. |
| `get_resume_critique_prompt(name, company, job_description)` | Build the post-generation critique prompt. Run in a fresh sub-agent. |
| `submit_resume_critique(name, company, job_description, findings)` | Register the critique. **Unlocks `finalize_resume`.** |
| `get_skim_review_prompt(name, …)` / `get_red_flag_prompt(name, …)` / `get_proofread_prompt(name)` | One-shot final-pass reviewers (6-second skim / red flags / proofread). |
| `finalize_resume(name, company, job_description)` | Terminal step. Refuses unless critiqued and within `max_pages`. |
| `get_interview_prompt(section, target_id, topic, company, job_description, focus)` | Interview the user to enrich one entry. Run **yourself in the conversation**, not a sub-agent. |
| `compile_resume(name)` | Re-compile an existing `.tex` without re-rendering. |
| `list_resumes()` / `check_environment()` | List outputs / diagnostics (files present, Tectonic installed). |

**Job search** (Platsbanken)

| Tool | Purpose |
|---|---|
| `search_platsbanken(query, location, limit, offset)` | Freetext search of Arbetsförmedlingen's JobTech JobSearch API. |
| `get_job_ad(ad_id)` | Fetch one full ad (description + must-have / nice-to-have). |
| `get_qualification_check_prompt(jobs)` | Build the mandatory qualification-gate prompt. Run in a fresh sub-agent before recommending any job. |

## Privacy / public-repo hygiene

This repo is meant to be public. Real content lives only on your machine.

**Tracked:**
- `data/personal_info.example.json` and `data/ui_guidelines.example.json` — dummy data / defaults only.
- `templates/resume.tex.j2` — generic placeholders only.
- All source code, `pyproject.toml`, `README.md`, `.mcp.json`.

**Gitignored:**
- `data/personal_info.json` and `data/ui_guidelines.json` — the real catalogue and your style config.
- `data/backups/` — timestamped catalogue backups.
- `output/` — rendered `.tex` and `.pdf` files contain personal data.
- `.claude/settings.local.json` — machine-specific paths/permissions.
- `.venv/`, `__pycache__/`, `.tectonic-cache/`, etc.

Always run `git status` before pushing — if anything from `data/` (other than the `*.example.json` files) or `output/` shows up unexpectedly, stop and investigate.

## Tailoring model (how the agent uses this)

`personal_info.json` is the **complete catalogue** — intentionally larger than any single resume. For a given JD, the agent makes two independent decisions:

1. **Item selection per section.** From each section, pick the items most relevant to the JD. Counts are agent-driven by relevance, not hardcoded.
2. **Bullet selection + rewriting.** For each item that *was* selected, pick the 2–4 highlights most relevant to the JD and rewrite them to match `ui_guidelines.voice` and the language of the JD.

`narrative` fields exist as background context for the agent only — they should never be copied verbatim into the resume.

## Critical tailoring loop (recruiter reviews)

To stop the agent from being a "yes-sayer" that includes irrelevant entries — or, just as bad, silently **leaves off something valuable** — two skeptical-recruiter reviews bracket generation. The check is symmetric: cut the weak **and** force-include the strong. Both reviews run as the **client's own fresh sub-agents** (e.g. Claude Code's Task tool) with no inherited context — so they're genuinely independent. **The server never calls an LLM**, so there's no API key and no extra cost beyond your normal client/subscription.

The loop is **enforced server-side**, not just by prose: the server records which review gates have been satisfied for a `(company, job_description)` in `output/.state/`, and refuses to proceed until they are. This holds on any client, including ones that don't run Claude Code's hooks.

1. **Rank (before selecting).** Call `get_relevance_review_prompt(company, job_description)`, run it in a fresh sub-agent, then `submit_relevance_review(...)`. This **unlocks** `generate_resume` for this job.
2. **Generate.** Select and rewrite content using those rankings, then call `generate_resume(name, content, company, job_description)`. The result includes deterministic `page_check` (≤ `max_pages`, default 1) and `ats_check`.
3. **Critique (after writing).** Call `get_resume_critique_prompt(name, company, job_description)`, run it in a fresh sub-agent, then `submit_resume_critique(...)`. It compares the rendered resume against the **full catalogue** — flagging unsupported claims, wrongly-omitted entries (by `id`), filler to cut, missing keywords, per-item feedback, and a **BLOCKING/READY** verdict so the loop terminates.
4. **Revise, review, finalize.** Apply blocking fixes and re-`generate_resume` until the verdict is `READY` (cap ~3 rounds). Run the one-shot final passes (`get_skim_review_prompt`, `get_red_flag_prompt`, `get_proofread_prompt`), then `finalize_resume(...)` — which refuses unless a critique is registered **and** the PDF is within `max_pages`.

The omission check is the safety net that makes it hard to drop something valuable: the post-write critic compares what's on the page against the entire catalogue and names anything strong that's missing, by `id`.

The full workflow is also returned by `get_resume_schema()`. Claude Code `PostToolUse` hooks add reminders on top of the server gates. The personas and prompt wording live in `src/resume_mcp_server/critic.py`.

### A note on MCP primitives

The reviews are delivered as *tools that return prompts*, which the client then runs in a sub-agent. MCP also has native `prompts` and `sampling` (server-requested completions) primitives; `sampling` would let the server run the reviews itself, but client support is still uneven, so returning prompts is the pragmatic choice today. The server-side state machine closes the main gap in that pattern — the client can't merely *claim* a review ran, because the server holds the submitted artifact. This is an MCP server rather than a single-client skill precisely so these validated writes and gates work across every MCP client.
