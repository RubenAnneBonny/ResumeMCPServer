from __future__ import annotations

import re
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from resume_mcp_server.paths import TEMPLATES_DIR

# Mapping of raw characters to their LaTeX-safe replacements. This is applied in
# a SINGLE pass (see _LATEX_ESCAPE_RE) so a replacement is never re-scanned — that
# matters because e.g. "\" -> "\textbackslash{}" contains "{" and "}", which the
# old sequential-replace approach then double-escaped into "\textbackslash\{\}".
_LATEX_ESCAPE_MAP: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    # Unicode dashes crash Tectonic (no glyph in the cmr/cfr-lm fonts). Convert
    # them to their LaTeX equivalents as a safety net — the agent is also told
    # (via the pre-generate hook / server-side check) to avoid em-dashes.
    "—": "---",  # em dash —
    "–": "--",   # en dash –
}

# Longest keys first so multi-char needles win; each key is matched at most once.
_LATEX_ESCAPE_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_LATEX_ESCAPE_MAP, key=len, reverse=True))
)


def latex_escape(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPE_MAP[m.group(0)], text)


# Section headers, keyed by the stable key used in ui_guidelines.section_titles.
# These are the fallbacks: whatever the config omits renders in English exactly
# as it did before section_titles existed. `projects` is the COMBINED
# competitions+projects header, which is why its default reads as a pair.
DEFAULT_SECTION_TITLES: dict[str, str] = {
    "profile": "Profile",
    "education": "Education",
    "experience": "Experience",
    "projects": "Competitions and Projects",
    "skills": "Technical Skills",
    "voluntary_work": "Voluntary Work and Engagements",
    "certifications": "Certifications",
    "languages": "Languages",
}

# Labels for the structured-skills sub-lists, keyed by their key in `skills`.
# A skills sub-key with no label here is rendered with its key title-cased.
DEFAULT_SKILL_LABELS: dict[str, str] = {
    "languages": "Programming Languages",
    "frameworks": "Frameworks & Libraries",
    "tools": "Developer Tools",
    "data_structures": "Data Structures",
    "algorithms": "Algorithms",
}


# A flat skills list is not necessarily *technical*, so it defaults to the
# plainer header. An explicit ui.section_titles.skills always wins.
FLAT_SKILLS_TITLE = "Skills"


def resolve_ui(ui: dict[str, Any], content: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return `ui` with section_titles/skill_labels defaulted, ready to render.

    Done here rather than in the template because the Jinja env uses
    StrictUndefined and generate_resume renders the ui_guidelines.json file
    as-is: `ui.section_titles.experience` would raise UndefinedError on any
    config predating these keys. Merging defaults in one place keeps every
    existing config working and keeps the template a plain lookup.

    `content` is consulted only to pick the *default* skills header, which
    depends on the catalogue's shape (structured -> "Technical Skills", flat
    -> "Skills"); a configured title overrides either.
    """
    titles = dict(DEFAULT_SECTION_TITLES)
    if isinstance((content or {}).get("skills"), list):
        titles["skills"] = FLAT_SKILLS_TITLE
    titles.update(ui.get("section_titles") or {})
    return {
        **ui,
        "section_titles": titles,
        "skill_labels": {
            **DEFAULT_SKILL_LABELS,
            **(ui.get("skill_labels") or {}),
        },
    }


def make_environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["tex"] = latex_escape
    return env


def render_resume(
    template_name: str,
    content: dict[str, Any],
    ui: dict[str, Any],
) -> str:
    env = make_environment()
    template = env.get_template(template_name)
    # Drop any stray "ui" key so it can't collide with the ui=ui keyword and
    # raise "got multiple values for keyword argument 'ui'".
    fields = {k: v for k, v in content.items() if k != "ui"}
    return template.render(**fields, ui=resolve_ui(ui, content))
