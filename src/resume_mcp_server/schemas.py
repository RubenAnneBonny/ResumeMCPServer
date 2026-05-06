from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class Skills(_Lax):
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
    skills: Skills = Field(default_factory=Skills)
    projects: list[Project] = Field(default_factory=list)
    competitions: list[Competition] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)


class UIGuidelines(_Lax):
    page: dict[str, Any] = Field(default_factory=dict)
    fonts: dict[str, Any] = Field(default_factory=dict)
    colors: dict[str, Any] = Field(default_factory=dict)
    section_heading: dict[str, Any] = Field(default_factory=dict)
    spacing: dict[str, Any] = Field(default_factory=dict)
    header: dict[str, Any] = Field(default_factory=dict)
    date_format: str = "MMM YYYY"
    bullet_style: str = "•"
    voice: dict[str, Any] = Field(default_factory=dict)


def validate_personal_info(data: Any) -> dict[str, Any]:
    return PersonalInfo.model_validate(data).model_dump(mode="json")


def validate_ui_guidelines(data: Any) -> dict[str, Any]:
    return UIGuidelines.model_validate(data).model_dump(mode="json")
