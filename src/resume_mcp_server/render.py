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
    return template.render(**fields, ui=ui)
