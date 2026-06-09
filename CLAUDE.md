# ResumeMCPServer — working notes for Claude

A stateless MCP server that turns a verbose personal-info catalogue into a tailored,
JD-specific resume PDF. It exposes data, validates writes, renders a Jinja2 LaTeX
template, and compiles via Tectonic. **The tailoring — and the recruiter reviews
below — happen in you (the agent), not in the server.** The server never calls an LLM.

## Mandatory critical tailoring loop

When asked to tailor a resume to a job, you MUST run both recruiter reviews — do not
skip them. They run as **fresh sub-agents** (the Task tool, no inherited context), which
keeps them independent and bills only to the user's normal subscription.

The check is symmetric — **cut weak entries AND force-include strong ones that were
missed**. Never silently drop something valuable.

1. **Rank first.** Call `get_relevance_review_prompt(company, job_description)` and run
   the returned `prompt` in a fresh Task sub-agent. Use its 0–5 scores and `MUST_INCLUDE`
   line: include the must-haves, cut the low scorers.
2. **Select + generate.** Pick and rewrite content (2–4 highlights per item, match
   `ui_guidelines.voice`), then call `generate_resume(name, content)`.
3. **Critique after writing.** Call `get_resume_critique_prompt(name, company,
   job_description)` and run it in a fresh Task sub-agent. It sees the full catalogue and
   the rendered resume, so it reports any valuable entries you **wrongly omitted** (by id),
   missing keywords, per-item feedback, and a **"Worth interviewing the candidate about"**
   list of gaps that matter for this job. A `PostToolUse` hook also reminds you.
4. **Revise.** ADD every wrongly-omitted entry it flags, fix the keywords and per-item
   issues, call `generate_resume` again, and repeat 3–4 until the **"Wrongly omitted"
   section is empty** and the critique is clean.
5. **Targeted interview (optional, per critique).** For each item the critique flags under
   "Worth interviewing the candidate about", you MAY call `get_interview_prompt(section,
   target_id, company, job_description, focus=<the gap>)` and run that narrow interview
   **yourself in the conversation** (NOT a sub-agent — it asks the user). Save any new
   *true* fact to the catalogue (after approval) so future resumes benefit, and use it on
   this resume only if it helps this job. The user may decline.

`narrative` fields in `personal_info.json` are background context only — never copy them
verbatim into the resume. The recruiter persona and prompt wording live in
`src/resume_mcp_server/critic.py`.

## Entry interview (catalogue enrichment)

Separate from tailoring: when the user adds or wants to refine a single catalogue entry
(a job, project, etc.) and isn't happy with how it reads, use the `/interview-entry` skill
or call `get_interview_prompt(section, target_id="" for new / id for refine)`. This is
**role-agnostic** — it hunts for angles that matter to *different* jobs. Unlike the
recruiter reviews, you run it **interactively in the main conversation** (a sub-agent can't
ask the user anything). Apply the **omit principle**: drop any thread that doesn't yield
concrete, truthful detail — never invent, inflate, or keep filler. Show the proposed entry
and save it (via `get_personal_info` → mutate → `update_personal_info`) only after the user
approves. The interviewer persona lives in `src/resume_mcp_server/critic.py`.

## Job search + mandatory qualification gate

When the user wants to **find** jobs (not tailor to one they already have), use the
`/find-jobs` skill. It searches Platsbanken via the JobTech JobSearch API
(`search_platsbanken`, `get_job_ad`).

**Hard rule: never recommend a job before the qualification gate passes.** The retrieved
ads are candidates, not recommendations. Before surfacing ANY job you MUST call
`get_qualification_check_prompt(jobs)` and run it in a **fresh sub-agent** (Task tool, no
inherited context) — like the recruiter reviews. A `PostToolUse` hook on
`search_platsbanken` also reminds you. **"Qualified" means the candidate meets the job's
STATED requirements — NOT that they are likely to be hired, beat other applicants, or
interview well.** A job is `NOT QUALIFIED` only when a *hard/must-have* requirement is
unmet; missing merits never disqualify; `UNCERTAIN` means the catalogue can't confirm a
hard requirement. Present results in three groups (qualified / not qualified with the
missing requirement named / uncertain). The auditor persona lives in
`src/resume_mcp_server/critic.py`.

## Privacy

`data/personal_info.json` and `output/` hold real personal data and are gitignored. Run
`git status` before committing; if anything from `data/` or `output/` appears, stop.
