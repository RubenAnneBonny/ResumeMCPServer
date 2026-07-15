---
name: interview-entry
description: Interview the user to enrich one personal_info.json entry — probe for stronger, more specific, truthful detail and better phrasing, drop weak answers, then save after approval. Use when the user has added or wants to add/refine a job, project, education, competition, or other catalogue entry and isn't happy with how it reads. Refine an existing entry or create a new one from scratch.
---

# Interview an entry

Conduct a short interview to make ONE entry in `data/personal_info.json` stronger and
truer — better phrasing, concrete specifics, missed angles — then save it on approval.
This is **role-agnostic catalogue maintenance**, not job tailoring. (The job-specific
recruiter loop can *also* trigger a narrower, targeted interview during tailoring — see
the last section.)

You run the interview **yourself, here in the conversation** — never a sub-agent, because
it has to ask the user questions.

## Steps

1. **Pick the target.** From the user's request or by asking:
   - Which `section`? (e.g. `experience`, `projects`, `education`, `competitions`,
     `certifications`, or any custom list section.)
   - **Refine** an existing entry (need its `id`) or **create** a new one (need a short
     `topic`)? If the user is unsure of ids, call `mcp__resume__get_personal_info` and show
     the entries in that section.

2. **Get the interview prompt.** Call
   `mcp__resume__get_interview_prompt(section, target_id=<id or "">, topic=<text or "">)`.
   (Leave `company`/`job_description`/`focus` empty for a general interview.)

3. **Run the interview** by following the returned `prompt`:
   - Ask a few focused questions at a time; react to the answers.
   - Hunt for angles different employers care about: quantitative rigor, ownership/
     initiative, collaboration & communication, technical depth, measurable impact.
   - **Omit principle:** the moment a thread stops yielding concrete, credible specifics,
     drop it. Never invent numbers, inflate scope, or keep a vague bullet. Fewer strong,
     true highlights is the right outcome when the material isn't there.

4. **Synthesize and show for approval.** Assemble the result into the entry shape
   (tight `highlights` with `text`+`tags`, an updated `narrative` that is background
   context only — never resume copy, plus any other fields). Present it as JSON and **wait
   for the user's OK**.

5. **Save on approval.** Use the granular tools (small, auditable writes — each backs up
   the catalogue to `data/backups/` first):
   - **Create:** `mcp__resume__add_entry(section, item)` — an `id` is derived if you omit one.
   - **Refine:** `mcp__resume__patch_entry(section, entry_id, changes)` to update only the
     changed keys, or `mcp__resume__delete_entry(section, entry_id)` to remove one.

   Avoid `update_personal_info` for single-entry edits (it is a whole-file write). Confirm
   what was saved.

## Targeted use during job tailoring

The post-write critique (`get_resume_critique_prompt`) returns a **"Worth interviewing the
candidate about"** section listing gaps that matter for the specific job. For each, you may
call `get_interview_prompt(section, target_id, company=…, job_description=…, focus=<the
gap>)` and run that narrower interview. Job-relative rule: if an answer doesn't help the
resume for that job, don't force it onto the resume — but still save any new *true* fact to
the catalogue (after approval) so future resumes benefit. The user may decline any interview.
