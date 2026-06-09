"""Prompt builders for the critical recruiter-review agents.

The MCP server itself never calls an LLM. These helpers assemble complete,
self-contained prompts that the orchestrating agent hands to a *fresh* sub-agent
(no inherited context) — e.g. Claude Code's Task tool, which runs on the user's
subscription. That sub-agent plays a skeptical recruiter and returns structured
feedback the main agent acts on.

Two reviews bracket resume generation:

- ``build_relevance_review_prompt`` runs BEFORE selection — it ranks every
  catalogue entry by relevance to the job, so weak/irrelevant items get cut.
- ``build_resume_critique_prompt`` runs AFTER the ``.tex`` is written — it lists
  the top missing keywords and, per included item, what is good and what is weak.
"""

from __future__ import annotations

import json
from typing import Any

# Tough-but-fair persona, centralized so it is easy to tune. ``{company}`` is
# filled per call; everything else is constant.
RECRUITER_PERSONA = (
    "You are a skeptical senior recruiter at {company}, hiring for the role "
    "described below. You skim ~50 resumes at about 6 seconds each, so you are "
    "impatient with anything generic, filler, or off-target. Be honest and "
    "direct about what is weak, vague, or irrelevant — but give real credit "
    "where a candidate genuinely matches what the role needs. You have NO prior "
    "context about this candidate beyond what is shown here; judge only on the "
    "evidence in front of you, the way a real recruiter would."
)


def _persona(company: str) -> str:
    return RECRUITER_PERSONA.format(company=company or "the company")


# Curious, sharp interviewer used to enrich a single catalogue entry. Unlike the
# recruiter, this persona *talks to the candidate* — so the interview is run by
# the MAIN agent in the conversation, never a fresh sub-agent (a sub-agent can't
# ask the user anything). It has no ``{company}`` slot: by default it is
# role-agnostic catalogue maintenance.
INTERVIEWER_PERSONA = (
    "You are a sharp, curious interviewer and resume coach. Your job is to pull "
    "the STRONGEST TRUTHFUL material out of the candidate about ONE entry in "
    "their background — by asking focused, probing questions, a few at a time, "
    "like a real conversation. You press for concrete specifics: the scope and "
    "scale of the work, real numbers, what the candidate did THEMSELVES versus "
    "what the team did, the tools used, the outcome and its impact, what was "
    "hard, and what they learned. Your defining rule: if a line of questioning "
    "does NOT surface substantive, credible, specific detail, you ABANDON it — "
    "you never fabricate, never inflate, and never keep vague filler. A few "
    "strong, true highlights beat a pile of padded weak ones."
)


def build_relevance_review_prompt(
    company: str,
    job_description: str,
    personal_info: dict[str, Any],
) -> str:
    """Prompt for the PRE-generation relevance ranking.

    Embeds the full personal-info catalogue so the recruiter sub-agent judges
    every candidate entry against the job, and asks for a strict, parseable
    ranking the main agent can use to decide what to include.
    """
    catalogue = json.dumps(personal_info, indent=2, ensure_ascii=False)
    company_label = company or "the company"
    return f"""{_persona(company)}

# Job: {company_label}
## Job description
{job_description.strip() or "(no job description provided)"}

# Candidate catalogue (the full pool of everything they could put on a resume)
This is intentionally larger than any single resume. Each item under
experience, education, projects, competitions, and certifications has a stable
`id`. `narrative` fields are background context, not resume text.

```json
{catalogue}
```

# Your task
Rank how relevant each catalogue item is to THIS job. For every item in
`experience`, `education`, `projects`, `competitions`, and `certifications`:

- Give a relevance score from 0 to 5 (5 = clearly belongs on this resume,
  0 = irrelevant, cut it).
- Give a one-line, concrete justification grounded in the job description.
- Mark items scoring 0–2 as candidates to CUT.
- Mark items that would be a real MISTAKE to leave off — strong, directly
  relevant evidence for this role — as MUST-INCLUDE.

The goal is symmetric: cut weak material AND make sure nothing genuinely
valuable gets left off. Scan the WHOLE catalogue; do not overlook a strong
entry just because it is buried lower down.

Also: in one or two sentences, name the 2–3 themes this employer most wants to
see, so the main agent can lean the resume toward them.

# Output format (return EXACTLY this, nothing else)
A `THEMES:` line, then a `MUST_INCLUDE:` line listing the ids that must not be
omitted, then one markdown table per non-empty section:

```
THEMES: <2-3 themes the employer most wants>
MUST_INCLUDE: <comma-separated ids that would be a mistake to leave off>

## experience
| id | score | must-include? | cut? | why |
|----|-------|---------------|------|-----|
| <id> | <0-5> | yes/no | yes/no | <one line> |

## education
| id | score | must-include? | cut? | why |
|----|-------|---------------|------|-----|
...

(repeat for projects, competitions, certifications that have items)
```

Be decisive with the scores — do not give everything a 3 or 4. The point is to
help the candidate cut weak material and surface the must-haves, not to
reassure them."""


def build_resume_critique_prompt(
    company: str,
    job_description: str,
    tex_source: str,
    personal_info: dict[str, Any],
) -> str:
    """Prompt for the POST-generation critique.

    Embeds BOTH the rendered LaTeX and the full personal-info catalogue, so the
    recruiter sub-agent can do two things the resume alone can't support:
    (1) flag valuable catalogue entries that were wrongly OMITTED from the
    resume, by `id`, and (2) critique what is on the page. Output is a strict,
    parseable shape the main agent can act on deterministically.
    """
    catalogue = json.dumps(personal_info, indent=2, ensure_ascii=False)
    company_label = company or "the company"
    return f"""{_persona(company)}

# Job: {company_label}
## Job description
{job_description.strip() or "(no job description provided)"}

# The full candidate catalogue (everything they COULD have put on the resume)
Each item has a stable `id`. `narrative` fields are background context, not
resume text.

```json
{catalogue}
```

# The resume the candidate actually submitted (rendered LaTeX source)
Read it the way it would appear on the page; ignore LaTeX formatting commands.

```latex
{tex_source}
```

# Your task
Critique this resume AS THE RECRUITER for the job above. Be specific and
actionable — every point should change something concrete. The single most
important thing you do here is catch VALUABLE MATERIAL THAT WAS LEFT OFF.

1. **Wrongly omitted entries (do this first, most important).** Compare the
   resume against the FULL catalogue above. List every catalogue item (by `id`
   and name) that is relevant to THIS job but does NOT appear on the resume.
   For each, give a 0–5 relevance score and one line on why it belongs. Err
   hard on the side of flagging — it is far worse to silently drop a strong
   entry than to over-suggest. Only leave this section empty if nothing of
   value was omitted.
2. **Top 5 missing keywords / skills.** Things the job description clearly wants
   that this resume does not surface (or buries). Order by importance.
3. **Per included item.** For each experience, project, competition, and
   education entry actually shown on the resume, give one line of what is GOOD
   (why it earns its place) and one line of what is WEAK or should change
   (vague bullet, missing metric, wrong emphasis, etc.).
4. **Worth interviewing the candidate about.** List entries (on the resume OR in
   the catalogue) where a quick answer FROM THE CANDIDATE could materially
   strengthen this resume for THIS job — an unclear scope, a missing metric, an
   ambiguity that matters here (e.g. the role is team-heavy but a project never
   says whether it was solo or collaborative). For each, give the `id`, the
   specific question to ask, and why the answer would change the resume. Only
   list gaps a short interview could actually close; "none" if there are none.
5. **Prioritized fixes.** A short ordered list (max 5) of the highest-impact
   edits the candidate should make before submitting — include both additions
   (omitted entries) and rewrites.

# Output format (return EXACTLY this, nothing else)
```
## Wrongly omitted (FIX FIRST)
- <id> (<name>) — score <0-5> — <why it belongs on this resume>
... (every relevant omitted catalogue item; "none" only if truly nothing valuable was left off)

## Missing keywords
1. <keyword> — <why it matters for this job>
... (up to 5)

## Per-item feedback
### <item name>
- Good: <one line>
- Weak: <one line>
... (repeat per included item)

## Worth interviewing the candidate about
- <id> (<name>) — <the specific question to ask> — <why the answer would strengthen THIS resume>
... ("none" if no live question would change the resume)

## Prioritized fixes
1. <highest-impact edit, additions first>
... (up to 5)
```

Do not pad. If a bullet is genuinely strong, say so briefly; if it is filler,
say to cut it."""


def build_interview_prompt(
    *,
    mode: str,
    section: str,
    entry: dict[str, Any] | None,
    topic: str,
    item_schema: dict[str, Any] | None,
    personal_info: dict[str, Any],
    ui_guidelines: dict[str, Any],
    company: str = "",
    job_description: str = "",
    focus: str = "",
) -> str:
    """Build the prompt the MAIN agent follows to interview the user about ONE entry.

    Two flavours, decided by whether job context is supplied:

    - **General** (no ``company``/``job_description``/``focus``): role-agnostic
      catalogue enrichment. Probe many angles that matter to *different* kinds of
      jobs, since this entry feeds every future tailored resume.
    - **Targeted** (job context + ``focus``): a narrower interview to close one
      specific gap for one job. Answers that don't help the resume for that job
      are simply left off it — but any new TRUE fact is still worth recording in
      the catalogue.

    ``mode`` is ``"refine"`` (improve ``entry``) or ``"create"`` (build a new
    entry of type ``section`` from ``topic``). Unlike the recruiter prompts, this
    is run by the main agent in the conversation, NOT a sub-agent.
    """
    catalogue = json.dumps(personal_info, indent=2, ensure_ascii=False)
    voice = json.dumps(ui_guidelines.get("voice", {}), ensure_ascii=False)
    targeted = bool(company or job_description or focus)

    if mode == "create":
        subject_block = (
            f"# What you are building\n"
            f"A brand-new `{section}` entry. The candidate described it as:\n\n"
            f"> {topic.strip() or '(no description given — ask them what it is first)'}\n\n"
            f"There is no existing entry yet — build one from scratch through the "
            f"interview."
        )
    else:
        entry_json = json.dumps(entry or {}, indent=2, ensure_ascii=False)
        subject_block = (
            f"# The entry you are improving (section `{section}`)\n"
            f"This is what the catalogue currently says. It is background to "
            f"sharpen — do not assume it is complete or well-phrased.\n\n"
            f"```json\n{entry_json}\n```"
        )

    if item_schema is not None:
        shape = json.dumps(item_schema, indent=2, ensure_ascii=False)
        shape_block = (
            f"# The shape to fill (JSON schema for one `{section}` item)\n"
            f"```json\n{shape}\n```"
        )
    else:
        shape_block = (
            f"# The shape to fill\n"
            f"`{section}` is a free-form list. Mirror the structure of the other "
            f"entries in that section in the catalogue above. Highlights are "
            f'objects of the form {{"text": "...", "tags": ["..."]}}.'
        )

    if targeted:
        focus_block = (
            f"# This is a TARGETED interview (tied to a specific job)\n"
            f"Company: {company or '(unspecified)'}\n"
            f"## Job description\n{job_description.strip() or '(none provided)'}\n\n"
            f"## The specific gap to close\n{focus.strip() or '(none given — infer the most useful one)'}\n\n"
            f"Keep the interview NARROW — ask only what closes this gap for this "
            f"job; don't re-interview the whole entry. Job-relative omit rule: if "
            f"the candidate's answer does NOT help the resume for THIS role, do "
            f"not force it onto the resume. But if the answer is a real, true fact "
            f"about their background, still propose recording it in the catalogue "
            f"so future resumes can use it."
        )
        angle_instruction = (
            "Drill the specific gap above. Ask the 1-3 questions that actually "
            "resolve it; stop once it's resolved."
        )
    else:
        focus_block = (
            "# This is a GENERAL interview (not tied to any job)\n"
            "This entry feeds EVERY future tailored resume, so deliberately hunt "
            "for angles that different employers care about: quantitative rigor, "
            "ownership/initiative, collaboration & communication, technical "
            "depth, and measurable impact. Surface the material now; later "
            "tailoring decides which angle to use per job."
        )
        angle_instruction = (
            "Cover the varied angles above across the interview, but only keep the "
            "ones that produce real specifics."
        )

    return f"""{INTERVIEWER_PERSONA}

{subject_block}

{focus_block}

{shape_block}

# Voice for any phrasing you propose
Match `ui_guidelines.voice` (person + tense): {voice or "(defaults)"}.
`narrative` is background context for future tailoring — NOT resume copy; never
write it as a resume bullet.

# The full catalogue (background, so you avoid repeating angles already covered)
```json
{catalogue}
```

# How to run this interview
You are talking to the candidate directly in this conversation. Do NOT spawn a
sub-agent, and do NOT dump a long questionnaire.

1. Ask a few focused questions at a time and react to the answers.
2. {angle_instruction}
3. OMIT PRINCIPLE: the moment a thread stops yielding concrete, credible
   specifics, drop it. Never invent numbers, never inflate scope, never keep a
   vague bullet just to have one. Fewer strong highlights is the correct outcome
   when the material isn't there.
4. When you have enough, synthesize the result into the entry shape above:
   tight, specific `highlights` (each `text` + `tags`), an updated `narrative`
   (background only), and any other fields (tech, dates, etc.). Keep everything
   strictly truthful to what the candidate told you.
5. STOP and show the candidate the proposed entry as JSON, and wait for their
   approval before anything is written. After they approve, the entry is saved
   to `personal_info.json` via update_personal_info (merge by `id`)."""
