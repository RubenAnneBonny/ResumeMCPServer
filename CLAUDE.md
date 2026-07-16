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

**Route every review through its dedicated agent** (`.claude/agents/`), not a
default sub-agent: `subagent_type: recruiter-reviewer` for steps 1 and 3,
`final-reviewer` for step 4b, `qualification-auditor` for the job-search gate. Each is
pinned to a faster model and told to follow the server's prompt verbatim. Hand the
prompt over unchanged.

**Never run sub-agent reviews sequentially when they are independent.** Sequential
round trips are what made a full run take ~20 minutes. Launch independent reviews in
parallel, in a single message.

0. **Research the company yourself** with the `WebSearch`/`WebFetch` tools — mission,
   domain, and what it values for this role. For a small or obscure employer, fetch its own
   site and read the ad closely. Use the themes to steer the summary and which highlights
   you emphasise. (The server no longer ships a research tool; you do this natively.)
1. **Rank first.** Call `get_relevance_review_prompt(company, job_description)` and run
   the returned `prompt` in a fresh `recruiter-reviewer` sub-agent. Then call
   `submit_relevance_review(company, job_description, results)` with the sub-agent's output.
   This is a **hard code gate**: `generate_resume` refuses to run for this job until the
   review is submitted (the server holds the artifact, so the step can't be faked). Use its
   0–5 scores and `MUST_INCLUDE` line: include the must-haves, cut the low scorers.
2. **Select + generate.** Pick and rewrite content (2–4 highlights per item) following
   `ui_guidelines.voice`: **no personal pronouns, past tense, strong action verbs, and
   never em-dashes (—)** — use commas, colons, or parentheses (the server rejects em-dashes
   in `generate_resume`, and a `PreToolUse` hook also blocks them). If
   `voice.banned_phrases` is set, those strings are rejected too (case-insensitively,
   anywhere in the content). Obey the **selection policy** below. Then call
   `generate_resume(name, content, company, job_description)` — the same `company`/
   `job_description` strings you passed to `submit_relevance_review`.
3. **Critique after writing.** Call `get_resume_critique_prompt(name, company,
   job_description)` and run it in a fresh `recruiter-reviewer` sub-agent, then call
   `submit_resume_critique(name, company, job_description, findings)` with its output
   (this unlocks `finalize_resume`). It sees the full catalogue and the rendered resume, so
   it reports **unsupported claims** (anything the catalogue can't back), valuable entries
   you **wrongly omitted** (by id), filler to **cut/trim**, what's working, truthful missing
   keywords, per-item feedback, and a **"Worth interviewing the candidate about"** list.
   Two `PostToolUse` hooks also remind you (critique + guidelines).
4. **Revise.** REMOVE/rephrase every unsupported claim, ADD every wrongly-omitted entry,
   CUT the flagged filler, fix the keywords and per-item issues, then call
   `generate_resume` again.
   **Only *blocking* findings buy another critique round** — an unsupported claim, an
   omitted entry scoring 4–5, or real filler still on the page. Everything else is a
   nitpick: apply it **silently in the next `generate_resume`, with NO new critique
   round**. Re-critiquing to bless a comma costs a full sub-agent round trip and changes
   nothing. Repeat 3–4 only while blocking findings remain, until the **Verdict is
   `READY`** (hard cap ~3 rounds; if it still isn't `READY`, say what is unresolved
   rather than looping). Each `generate_resume` returns deterministic
   **`page_check`**, **`ats_check`**, and (when `include_all_experience` is on)
   **`selection_check`**. Fix overflow by CUTTING the lowest-relevance entry and underfill
   (`pages < target_pages`) by ADDING the next-highest-relevance entries or expanding
   highlights — **never** by shrinking/stretching margins, and never by padding with fluff.
   The server also rejects em-dashes and refuses to compile forbidden dashes, for every
   client.
4b. **Final review (once, near the end — NOT in the loop).** On the settled resume, call
   `get_final_review_prompt(name, company, job_description)` and run it in **ONE** fresh
   `final-reviewer` sub-agent. It returns all three passes in delimited sections: **SKIM**
   (6-second first impression / emphasis), **RED FLAGS** (skeptical questions; each can feed
   a targeted interview), **PROOFREAD** (tense/date/verb/punctuation/language). You are the
   arbiter: apply real fixes, ignore beige committee-speak. Then regenerate once — these are
   polish fixes and do **not** justify another critique round.
   The older `get_skim_review_prompt` / `get_red_flag_prompt` / `get_proofread_prompt` tools
   still exist. If you ever want them separately, launch all three **in parallel in a single
   message** — never one after another.
4c. **Finalize.** Call `finalize_resume(name, company, job_description)` — it refuses unless a
   critique is registered, the PDF is inside the page window (`max_pages`, plus
   `target_pages` when set), and (when `include_all_experience` is on) the last
   `generate_resume` covered every catalogue job.
5. **Targeted interview (optional, per critique).** For each item the critique flags under
   "Worth interviewing the candidate about", you MAY call `get_interview_prompt(section,
   target_id, company, job_description, focus=<the gap>)` and run that narrow interview
   **yourself in the conversation** (NOT a sub-agent — it asks the user). Save any new
   *true* fact to the catalogue (after approval) so future resumes benefit, and use it on
   this resume only if it helps this job. The user may decline.

`narrative` fields in `personal_info.json` are background context only — never copy them
verbatim into the resume. The recruiter persona and prompt wording live in
`src/resume_mcp_server/critic.py`.

### Quick mode (only when the user asks for it)

**Full mode above is the default.** If the user asks for a quick/fast run:

- **Skip step 0** (web research) **only when the JD is pasted in full** — the ad itself
  then carries the themes. Still research if the JD is a link, a fragment, or the employer
  is obscure and the ad is thin.
- **Cap at ONE critique round**: generate → critique → apply blocking fixes → regenerate.
  Report anything still unresolved rather than looping.
- Use the combined `get_final_review_prompt` (never the three separate passes).

Both gates still run — `submit_relevance_review` and `submit_resume_critique` are hard code
gates, and quick mode never skips a review, it just stops re-running one. If the critique
comes back `BLOCKING` after the single round, **say so plainly** instead of quietly
shipping it.

## Selection policy and the page window (`ui_guidelines`)

Read these before selecting content; they change what "done" means.

- **`selection.require_all_from`** (default `[]`). Lists the catalogue sections where
  **every entry must appear on the resume** — the relevance review then ranks those for
  *emphasis*, not for inclusion. An older or off-target entry may be compressed to its
  heading with 0–1 bullets, but **never dropped** (a missing job reads as a gap).
  `generate_resume` returns a `selection_check` naming any missing `id`, and
  `finalize_resume` refuses until it is clean. Sections not listed stay agent-selected.
  The older boolean `selection.include_all_experience: true` still works and means
  `["experience"]`.
- **`page.max_pages`** (default 1) is a hard ceiling; **`page.target_pages`** (optional) is
  a floor. Coming in under the target is a real finding: ADD the next-highest-relevance
  entries or expand the highlights of what's already there, guided by the relevance review.
  If the catalogue genuinely has nothing more worth adding, **say so** — do not invent
  material, and do not stretch margins or fonts.
- **`section_titles` / `skill_labels`** set the rendered headers (e.g. Swedish). If the
  resume is written in another language, set these too, or the page mixes languages. The
  template supplies English only as a fallback.
- **`sections`** (optional) is the ordered list of what actually renders: which sections
  exist, their order, their titles, and which catalogue keys feed each. Absent = the
  default eight; `[]` = render nothing. **Never assume the default set** — call
  `get_ui_guidelines()` and read `resolved_sections` (or `get_resume_schema()["sections"]`)
  to see what this user's resume will contain. A section can merge several sources under
  one heading, and its `fields` name catalogue fields, so a user may have invented a
  section (e.g. `publications`) that no template code mentions. Titles resolve as
  `sections[].title` → `section_titles[key]` → English default → title-cased key, so a
  translation-only config still just sets `section_titles`.
- **`voice.banned_phrases`** are rejected server-side anywhere in the content.

## Entry interview (catalogue enrichment)

Separate from tailoring: when the user adds or wants to refine a single catalogue entry
(a job, project, etc.) and isn't happy with how it reads, use the `/interview-entry` skill
or call `get_interview_prompt(section, target_id="" for new / id for refine)`. This is
**role-agnostic** — it hunts for angles that matter to *different* jobs. Unlike the
recruiter reviews, you run it **interactively in the main conversation** (a sub-agent can't
ask the user anything). Apply the **omit principle**: drop any thread that doesn't yield
concrete, truthful detail — never invent, inflate, or keep filler. Show the proposed entry
and save it only after the user approves, using the granular tools: `add_entry(section,
item)` to create (an id is derived if omitted) or `patch_entry(section, id, changes)` /
`delete_entry(section, id)` to refine. Prefer these over the whole-file `update_personal_info`.
The interviewer persona lives in `src/resume_mcp_server/critic.py`.

## Job search + mandatory qualification gate

When the user wants to **find** jobs (not tailor to one they already have), use the
`/find-jobs` skill. It searches Platsbanken via the JobTech JobSearch API
(`search_platsbanken`, `get_job_ad`).

**Hard rule: never recommend a job before the qualification gate passes.** The retrieved
ads are candidates, not recommendations. Before surfacing ANY job you MUST call
`get_qualification_check_prompt(jobs)` and run it in a **fresh `qualification-auditor`
sub-agent** (no inherited context) — like the recruiter reviews. Batch the shortlist into
ONE call rather than one sub-agent per job. A `PostToolUse` hook on
`search_platsbanken` also reminds you. **"Qualified" means the candidate meets the job's
STATED requirements — NOT that they are likely to be hired, beat other applicants, or
interview well.** A job is `NOT QUALIFIED` only when a *hard/must-have* requirement is
unmet; missing merits never disqualify; `UNCERTAIN` means the catalogue can't confirm a
hard requirement. Present results in three groups (qualified / not qualified with the
missing requirement named / uncertain). The auditor persona lives in
`src/resume_mcp_server/critic.py`.

## Privacy

`data/personal_info.json`, `data/ui_guidelines.json`, and `output/` hold real personal
data and are gitignored. Each `data/*.json` is seeded on first run from its committed
`*.example.json` counterpart (see `_bootstrap_personal_info` / `_bootstrap_ui_guidelines`
in `server.py`), so edits to the live files stay local. Run `git status` before committing;
if anything from `data/` (other than the `*.example.json` files) or `output/` appears, stop.
