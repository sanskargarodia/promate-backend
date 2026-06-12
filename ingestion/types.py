"""Pydantic records produced by the ingestion parsers (never prose for tools)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepairStory(BaseModel):
    title: str
    content: str


class ScrapedPart(BaseModel):
    ps_number: str
    manufacturer_part_number: str | None = None
    name: str
    brand: str | None = None
    appliance_type: str
    price_cents: int | None = None
    in_stock: bool = False
    image_urls: list[str] = Field(default_factory=list)
    install_difficulty: str | None = None
    install_time_minutes: int | None = None
    install_instructions: str | None = None
    repair_stories: list[RepairStory] = Field(default_factory=list)
    video_url: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    description: str | None = None
    replaced_part_numbers: list[str] = Field(default_factory=list)
    symptoms_fixed: list[str] = Field(default_factory=list)
    compatible_models: list[str] = Field(default_factory=list)
    source_url: str


class ScrapedModel(BaseModel):
    model_number: str
    brand: str | None = None
    appliance_type: str
    title: str | None = None
    part_ps_numbers: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    source_url: str


class ScrapedDocument(BaseModel):
    doc_type: str
    title: str
    content: str
    part_ps_number: str | None = None
    model_number: str | None = None
    source_url: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CrawlManifest(BaseModel):
    """URLs discovered or required for a crawl run."""

    part_urls: list[str] = Field(default_factory=list)
    model_urls: list[str] = Field(default_factory=list)
    category_urls: list[str] = Field(default_factory=list)
