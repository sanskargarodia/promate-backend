"""Structured catalog payloads returned by agent tools (never free-form prose)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PartResult(BaseModel):
    ps_number: str
    name: str
    brand: str | None = None
    appliance_type: str
    price_cents: int | None = None
    in_stock: bool = False
    image_urls: list[str] = Field(default_factory=list)
    install_difficulty: str | None = None
    install_time_minutes: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    source_url: str | None = None


class CompatibilityResult(BaseModel):
    ps_number: str
    model_number: str
    compatible: bool | None = Field(
        description="True/false when known; None when part or model missing from catalog.",
    )
    part_name: str | None = None
    message: str


class InstallStep(BaseModel):
    order: int
    text: str


class InstallationGuide(BaseModel):
    ps_number: str
    part_name: str
    difficulty: str | None = None
    time_minutes: int | None = None
    video_url: str | None = None
    stories: list["DocumentChunk"] = Field(
        default_factory=list,
        description="Semantically retrieved repair-story chunks for this part.",
    )
    steps: list[InstallStep] = Field(default_factory=list)
    safety_notice: str = (
        "Unplug the appliance and shut off the water supply before servicing, when applicable."
    )
    sources: list[str] = Field(default_factory=list)


class DiagnosisCandidate(BaseModel):
    ps_number: str
    name: str
    relevance: str | None = None
    price_cents: int | None = None
    in_stock: bool = False


class DiagnosisResult(BaseModel):
    symptom: str
    appliance_type: str | None = None
    brand: str | None = None
    likely_causes: list[str] = Field(default_factory=list)
    candidate_parts: list[DiagnosisCandidate] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class DocumentChunk(BaseModel):
    doc_type: str
    title: str
    content: str
    part_ps_number: str | None = None
    source_url: str | None = None
    score: float | None = None
