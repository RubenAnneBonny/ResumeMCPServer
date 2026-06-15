from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from resume_mcp_server.paths import TEMPLATES_DIR

_LATEX_ESCAPES: list[tuple[str, str]] = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
    # Unicode dashes crash Tectonic (no glyph in the cmr/cfr-lm fonts). Convert
    # them to their LaTeX equivalents as a safety net — the agent is also told
    # (via the pre-generate hook) to avoid em-dashes in the first place.
    ("—", "---"),  # em dash —
    ("–", "--"),   # en dash –
]


def latex_escape(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    for needle, replacement in _LATEX_ESCAPES:
        text = text.replace(needle, replacement)
    return text


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
    return template.render(**content, ui=ui)
