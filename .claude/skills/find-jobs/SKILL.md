---
name: find-jobs
description: Search Platsbanken (Arbetsförmedlingen's job board) for live job ads that match the candidate's personal_info.json catalogue, then run a mandatory qualification check before recommending any of them. Use when the user wants to find, discover, or browse jobs that fit their profile. "Qualified" here means we meet the job's STATED requirements — not that we're likely to be hired.
---

# Find jobs on Platsbanken

Discover live job ads on Platsbanken that align with the candidate, then **gate every
recommendation behind a qualification check**. The check answers one narrow question —
*do we meet the job's stated requirements?* — NOT *are we likely to get hired?* You must
run it (a PostToolUse hook will also remind you); never present a job as a recommendation
before it has passed.

## Steps

1. **Build the search from the catalogue.** Call `mcp__resume__get_personal_info`. Derive
   freetext `query` terms from the candidate's titles and strongest skills, and a
   `location` from `contact.location` (and/or `distans`/remote if relevant). It's fine to
   run a few `mcp__resume__search_platsbanken(query, location, limit)` queries with
   different angles and dedupe the results by job `id`.

2. **Get full requirements for promising hits.** `search_platsbanken` truncates long
   descriptions. For the candidates worth considering, call
   `mcp__resume__get_job_ad(id)` to pull the full requirements text plus the structured
   `must_have`/`nice_to_have` blocks — the qualification check is only as accurate as the
   requirements it sees.

3. **Qualification gate (mandatory).** Call
   `mcp__resume__get_qualification_check_prompt(jobs)` with the candidate jobs, then run
   the returned `prompt` in a **fresh `qualification-auditor` sub-agent** (no inherited
   context) — exactly like the recruiter reviews. Batch the whole shortlist into ONE call,
   not one sub-agent per job. It returns a per-job verdict
   (`QUALIFIED` / `NOT QUALIFIED` / `UNCERTAIN`), a requirement-by-requirement table, and
   the unmet stated requirements (`MISSING_HARD`). A job is `NOT QUALIFIED` only when a
   **hard** requirement is unmet; missing merits never disqualify.

4. **Present results in three groups.** Be honest and concrete:
   - **✅ Recommended (qualified):** for each, one line on why we meet the stated
     requirements + the `webpage_url`.
   - **❌ Not qualified:** each with the *specific* stated requirement we don't meet (from
     `MISSING_HARD`). Don't hide these — the user may have a qualification the catalogue
     doesn't capture yet.
   - **❔ Uncertain:** each with the hard requirement the catalogue can't confirm, for the
     user to verify.

   State plainly that "qualified" means meeting the stated requirements, not likelihood of
   being hired.

## After the search

- If an **Uncertain** or **Not qualified** verdict is only because the catalogue is missing
  a true fact about the candidate, suggest the `/interview-entry` skill to capture it so
  future searches judge accurately.
- To tailor a resume to one of the recommended jobs, hand off to the normal tailoring loop
  (relevance review → generate → critique) in `CLAUDE.md`.
