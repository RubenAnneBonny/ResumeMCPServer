from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Lax(BaseModel):
    model_config = ConfigDict(extra="allow")


class Link(_Lax):
    label: str = ""
    url: str = ""
    display: str = ""


class Contact(_Lax):
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = Field(default_factory=list)


class Highlight(_Lax):
    text: str = ""
    tags: list[str] = Field(default_factory=list)


class Experience(_Lax):
    id: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    narrative: str = ""
    highlights: list[Highlight] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)


class Education(_Lax):
    id: str = ""
    degree: str = ""
    institution: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    narrative: str = ""
    highlights: list[Highlight] = Field(default_factory=list)
    gpa: str = ""


class Project(_Lax):
    id: str = ""
    name: str = ""
    narrative: str = ""
    highlights: list[Highlight] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)


class Competition(_Lax):
    id: str = ""
    name: str = ""
    placement: str = ""
    date: str = ""
    narrative: str = ""
    highlights: list[Highlight] = Field(default_factory=list)


class Certification(_Lax):
    id: str = ""
    name: str = ""
    issuer: str = ""
    date: str = ""
    url: str = ""


class VoluntaryWork(_Lax):
    id: str = ""
    title: str = ""
    organization: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    narrative: str = ""
    highlights: list[Highlight] = Field(default_factory=list)


class Language(_Lax):
    """A spoken language. Deliberately has no `id`: it is not a rankable resume
    entry, which is how critic.py tells it apart from the sections a relevance
    review scores."""

    language: str = ""
    proficiency: str = ""


class Skills(_Lax):
    """Structured, developer-centric skills: {languages, frameworks, tools, ...}.

    Extra keys are allowed (the example catalogue also carries data_structures /
    algorithms); the template renders any it has a label for. A catalogue may
    instead use a FLAT list of strings — see ``PersonalInfo.skills``.
    """

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class PersonalInfo(_Lax):
    name: str = ""
    title: str = ""
    contact: Contact = Field(default_factory=Contact)
    summary: str = ""
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    # Two accepted shapes. A flat ["Python", "SQL", ...] list is common for
    # non-developer catalogues; the structured form is the developer default.
    # A list can't validate as Skills (it isn't a mapping), so the union is
    # unambiguous either way.
    skills: Skills | list[str] = Field(default_factory=Skills)
    projects: list[Project] = Field(default_factory=list)
    competitions: list[Competition] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    voluntary_work: list[VoluntaryWork] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)


class SectionFields(_Lax):
    """Which catalogue fields feed each slot of a rendered item.

    Field names are looked up on the item; a list-valued field (e.g. `tech`) is
    flattened, and empty/missing ones drop out. This is what lets a section the
    template has never heard of render without a template edit.
    """

    # kind="entries": "\textbf{bold}<italic_sep>\textit{italic}" on the left,
    # `right` on the right, an optional "<note_label>: <note>" line, then bullets.
    bold: list[str] = Field(default_factory=list)
    italic: list[str] = Field(default_factory=list)
    italic_sep: str = ", "
    # [] = no right-hand cell, ["date"] = one value, ["start", "end"] = a range
    # rendered "start--end", collapsing when end is empty or equals start.
    right: list[str] = Field(default_factory=list)
    note: str = ""
    note_label: str = ""
    bullets: str = "highlights"
    # kind="oneline": "\textbf{bold}<sep>rest (paren)".
    sep: str = " --- "
    rest: list[str] = Field(default_factory=list)
    paren: str = ""


class SectionBlock(_Lax):
    """One catalogue source rendered inside a section. A section usually has a
    single block; multiple blocks render under one heading, which is how the
    default "Competitions and Projects" section merges two catalogue keys."""

    source: str
    kind: Literal["prose", "entries", "oneline", "skills"] = "entries"
    fields: SectionFields = Field(default_factory=SectionFields)


class SectionSpec(_Lax):
    """One rendered resume section. The ORDER of these in UIGuidelines.sections
    is the order they appear on the page."""

    key: str
    # None = fall back to ui.section_titles[key], then the English default in
    # render.DEFAULT_SECTION_TITLES, then a title-cased key.
    title: str | None = None
    space_after: str = "-16pt"
    blocks: list[SectionBlock] = Field(min_length=1)


class UIGuidelines(_Lax):
    page: dict[str, Any] = Field(default_factory=dict)
    fonts: dict[str, Any] = Field(default_factory=dict)
    colors: dict[str, Any] = Field(default_factory=dict)
    section_heading: dict[str, Any] = Field(default_factory=dict)
    spacing: dict[str, Any] = Field(default_factory=dict)
    header: dict[str, Any] = Field(default_factory=dict)
    bullet_style: str = "•"
    voice: dict[str, Any] = Field(default_factory=dict)
    # Display strings for the rendered section headers, keyed by stable section
    # key (profile, education, experience, ...). Anything absent falls back to
    # the English default in render.DEFAULT_SECTION_TITLES, so old configs keep
    # working. Set these to render a non-English resume.
    section_titles: dict[str, Any] = Field(default_factory=dict)
    # Which sections exist, in render order, and what feeds each. None (the
    # default) means "synthesize render.DEFAULT_SECTIONS", so a config predating
    # this key keeps rendering exactly as before. An explicit [] is different: it
    # means render no sections at all.
    sections: list[SectionSpec] | None = None
    # Display strings for the labels INSIDE the skills section, keyed by the
    # skills sub-key (languages, frameworks, tools, ...). Falls back to
    # render.DEFAULT_SKILL_LABELS.
    skill_labels: dict[str, Any] = Field(default_factory=dict)
    # Selection policy the AGENT must honor, enforced by checks.py.
    selection: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_page_targets(self) -> UIGuidelines:
        """target_pages is a floor, max_pages a ceiling — a floor above the
        ceiling is unsatisfiable, so refuse it at write time rather than
        letting page_check fail forever."""
        target = self.page.get("target_pages")
        if target is None:
            return self
        try:
            target_n = int(target)
            max_n = int(self.page.get("max_pages", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "page.target_pages and page.max_pages must be integers"
            ) from exc
        if target_n < 1:
            raise ValueError(f"page.target_pages must be >= 1 (got {target_n})")
        if target_n > max_n:
            raise ValueError(
                f"page.target_pages ({target_n}) cannot exceed page.max_pages "
                f"({max_n}): the target is a floor and max_pages is a hard "
                "ceiling, so this can never be satisfied."
            )
        return self


def validate_personal_info(data: Any) -> dict[str, Any]:
    return PersonalInfo.model_validate(data).model_dump(mode="json")


def validate_ui_guidelines(data: Any) -> dict[str, Any]:
    # exclude_none so an absent `sections` (and an unset section `title`) stays
    # absent rather than being written back into the user's config as `null` —
    # which resolve_sections would then have to treat as "synthesize defaults"
    # anyway, and which reads as a mistake in a hand-edited file.
    return UIGuidelines.model_validate(data).model_dump(mode="json", exclude_none=True)
