from __future__ import annotations

import copy
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


def _field_text(item: Any, name: str) -> str:
    """One catalogue field as display text. A list field (e.g. `tech`) is joined;
    anything missing or blank becomes "" so callers can drop it."""
    if not isinstance(item, dict):
        return ""
    value = item.get(name)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def join_fields(item: Any, names: Any, sep: str = ", ") -> str:
    """Join several catalogue fields into one string, dropping the empty ones.

    Returns RAW text: the template applies |tex, so escaping stays in
    latex_escape alone. Dropping empties is what keeps "Title, " (with a
    dangling separator) off the page when an item omits e.g. `company`.
    """
    parts = [_field_text(item, n) for n in (names or [])]
    return sep.join(p for p in parts if p)


def date_range(item: Any, names: Any) -> str:
    """The right-hand cell of an entry: "" for no names, the single value for
    one, or "start--end" for two — collapsing to just "start" when the end is
    missing or identical (an ongoing or single-year entry)."""
    values = [_field_text(item, n) for n in (names or [])]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    start, end = values[0], values[1]
    return f"{start}--{end}" if end and end != start else start


def skill_lines(skills: Any, labels: dict[str, Any]) -> list[tuple[str, str]]:
    """(label, joined values) per non-empty skills sub-list, in catalogue order.

    Covers EVERY sub-key rather than a fixed five, so a catalogue can invent a
    category; one without a configured label falls back to its title-cased key.
    """
    lines: list[tuple[str, str]] = []
    if not isinstance(skills, dict):
        return lines
    for key, values in skills.items():
        if not isinstance(values, (list, tuple)):
            continue
        text = ", ".join(str(v).strip() for v in values if str(v).strip())
        if text:
            lines.append((str(labels.get(key) or key.replace("_", " ").title()), text))
    return lines


# The sections rendered when a config has no `sections` key: exactly the layout
# and order the template hardcoded before it was data-driven, including the
# inconsistent trailing spacing (-2mm/-6mm/-16pt), so an existing config keeps
# producing a byte-identical resume. Anything here is overridable per user.
DEFAULT_SECTIONS: list[dict[str, Any]] = [
    {
        "key": "profile",
        "space_after": "-2mm",
        "blocks": [{"source": "summary", "kind": "prose"}],
    },
    {
        "key": "education",
        "space_after": "-6mm",
        "blocks": [
            {
                "source": "education",
                "kind": "entries",
                "fields": {
                    "bold": ["degree"],
                    "italic": ["institution", "location"],
                    "italic_sep": ", ",
                    "right": ["start_date", "end_date"],
                    "note": "gpa",
                    "note_label": "GPA",
                    "bullets": "highlights",
                },
            }
        ],
    },
    {
        "key": "experience",
        "space_after": "-6mm",
        "blocks": [
            {
                "source": "experience",
                "kind": "entries",
                "fields": {
                    "bold": ["title", "company"],
                    "right": ["start_date", "end_date"],
                    "bullets": "highlights",
                },
            }
        ],
    },
    {
        # One heading fed by two catalogue keys — the reason a section takes a
        # LIST of blocks rather than a single source.
        "key": "projects",
        "blocks": [
            {
                "source": "competitions",
                "kind": "entries",
                "fields": {
                    "bold": ["name"],
                    "italic": ["placement"],
                    "italic_sep": " --- ",
                    "right": ["date"],
                    "bullets": "highlights",
                },
            },
            {
                "source": "projects",
                "kind": "entries",
                "fields": {
                    "bold": ["name"],
                    "italic": ["tech"],
                    "italic_sep": " --- ",
                    "right": [],
                    "bullets": "highlights",
                },
            },
        ],
    },
    {
        "key": "skills",
        "blocks": [{"source": "skills", "kind": "skills"}],
    },
    {
        "key": "voluntary_work",
        "blocks": [
            {
                "source": "voluntary_work",
                "kind": "entries",
                "fields": {
                    "bold": ["title", "organization"],
                    "right": ["start_date", "end_date"],
                    "bullets": "highlights",
                },
            }
        ],
    },
    {
        "key": "certifications",
        "blocks": [
            {
                "source": "certifications",
                "kind": "oneline",
                "fields": {
                    "bold": ["name"],
                    "sep": " --- ",
                    "rest": ["issuer"],
                    "paren": "date",
                },
            }
        ],
    },
    {
        "key": "languages",
        "blocks": [
            {
                "source": "languages",
                "kind": "oneline",
                "fields": {
                    "bold": ["language"],
                    "sep": ": ",
                    "rest": ["proficiency"],
                },
            }
        ],
    },
]


def _block_has_content(
    block: dict[str, Any], content: dict[str, Any], labels: dict[str, Any]
) -> bool:
    """Is there anything in the catalogue for this block to render?

    Emptiness is kind-specific: a `skills` mapping of nothing but empty
    sub-lists is a truthy dict that renders no lines, and a `prose` source of
    whitespace is a truthy string that renders nothing.
    """
    data = content.get(block["source"])
    kind = block["kind"]
    if kind == "skills":
        if isinstance(data, list):
            return any(str(v).strip() for v in data)
        return bool(skill_lines(data, labels))
    if kind == "prose":
        return bool(str(data or "").strip())
    return bool(data)


def resolve_sections(
    ui: dict[str, Any],
    content: dict[str, Any],
    titles: dict[str, Any],
    labels: dict[str, Any],
) -> list[dict[str, Any]]:
    """The ordered, fully-defaulted, pruned section specs the template loops over.

    `ui["sections"]` absent (not []) means "use DEFAULT_SECTIONS", so a config
    written before sections were data-driven renders exactly as it always did.

    Each spec is normalised through SectionSpec so every field the template
    touches is present — the Jinja env uses StrictUndefined, so a hand-written
    section omitting e.g. `italic_sep` would otherwise raise at render time.
    Blocks with no catalogue content (and sections left with no blocks) are
    dropped HERE rather than guarded in the template, which keeps the template a
    plain loop.
    """
    from resume_mcp_server.schemas import SectionSpec

    raw = ui.get("sections")
    if raw is None:
        raw = copy.deepcopy(DEFAULT_SECTIONS)

    resolved: list[dict[str, Any]] = []
    for item in raw:
        spec = SectionSpec.model_validate(item).model_dump(mode="json")
        blocks = [
            b for b in spec["blocks"] if _block_has_content(b, content, labels)
        ]
        if not blocks:
            continue
        key = spec["key"]
        spec["title"] = (
            spec.get("title")
            or titles.get(key)
            or key.replace("_", " ").title()
        )
        spec["blocks"] = blocks
        resolved.append(spec)
    return resolved


def resolve_ui(ui: dict[str, Any], content: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return `ui` with sections/section_titles/skill_labels defaulted, ready to render.

    Done here rather than in the template because the Jinja env uses
    StrictUndefined and generate_resume renders the ui_guidelines.json file
    as-is: `ui.section_titles.experience` would raise UndefinedError on any
    config predating these keys. Merging defaults in one place keeps every
    existing config working and keeps the template a plain lookup.

    `content` is consulted to prune empty sections, and to pick the *default*
    skills header, which depends on the catalogue's shape (structured ->
    "Technical Skills", flat -> "Skills"); a configured title overrides either.
    """
    content = content or {}
    titles = dict(DEFAULT_SECTION_TITLES)
    if isinstance(content.get("skills"), list):
        titles["skills"] = FLAT_SKILLS_TITLE
    titles.update(ui.get("section_titles") or {})
    labels = {**DEFAULT_SKILL_LABELS, **(ui.get("skill_labels") or {})}
    return {
        **ui,
        "section_titles": titles,
        "skill_labels": labels,
        "sections": resolve_sections(ui, content, titles, labels),
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
    # Field plumbing lives in Python, not Jinja: it returns RAW text that the
    # template then pipes through |tex, so escaping still happens in exactly one
    # place and the macros stay readable.
    env.globals["join_fields"] = join_fields
    env.globals["date_range"] = date_range
    env.globals["skill_lines"] = skill_lines
    return env


def render_resume(
    template_name: str,
    content: dict[str, Any],
    ui: dict[str, Any],
) -> str:
    env = make_environment()
    template = env.get_template(template_name)
    # Drop any stray "ui"/"content" key so it can't collide with the keyword
    # arguments and raise "got multiple values for keyword argument".
    fields = {k: v for k, v in content.items() if k not in ("ui", "content")}
    # `content` is passed WHOLE as well as splatted: the section loop looks
    # sources up by name (content[block.source]), while the header block still
    # reads name/title/contact as plain globals.
    return template.render(**fields, content=fields, ui=resolve_ui(ui, content))
