"""SQLAlchemy ORM models for the PartSelect catalog (Phase 1)."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.db import Base


class Part(Base):
    __tablename__ = "parts"

    ps_number: Mapped[str] = mapped_column(String(16), primary_key=True)
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(512))
    brand: Mapped[str | None] = mapped_column(String(64))
    appliance_type: Mapped[str] = mapped_column(String(32))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    image_urls: Mapped[list[str]] = mapped_column(JSONB, default=list)
    install_difficulty: Mapped[str | None] = mapped_column(String(32))
    install_time_minutes: Mapped[int | None] = mapped_column(Integer)
    install_instructions: Mapped[str | None] = mapped_column(Text)
    video_url: Mapped[str | None] = mapped_column(String(512))
    rating: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    replaced_part_numbers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    symptoms_fixed: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_url: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    compatibilities: Mapped[list[PartModelCompatibility]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )
    symptom_links: Mapped[list[PartSymptom]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )


class ApplianceModel(Base):
    __tablename__ = "models"

    model_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    brand: Mapped[str | None] = mapped_column(String(64))
    appliance_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256))
    source_url: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    compatibilities: Mapped[list[PartModelCompatibility]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class PartModelCompatibility(Base):
    __tablename__ = "part_model_compatibility"
    __table_args__ = (UniqueConstraint("part_ps_number", "model_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_ps_number: Mapped[str] = mapped_column(
        String(16), ForeignKey("parts.ps_number", ondelete="CASCADE")
    )
    model_number: Mapped[str] = mapped_column(
        String(32), ForeignKey("models.model_number", ondelete="CASCADE")
    )
    compatible: Mapped[bool] = mapped_column(Boolean, default=True)

    part: Mapped[Part] = relationship(back_populates="compatibilities")
    model: Mapped[ApplianceModel] = relationship(back_populates="compatibilities")


class Symptom(Base):
    __tablename__ = "symptoms"
    __table_args__ = (UniqueConstraint("slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512))
    appliance_type: Mapped[str | None] = mapped_column(String(32))
    brand: Mapped[str | None] = mapped_column(String(64))

    part_links: Mapped[list[PartSymptom]] = relationship(
        back_populates="symptom", cascade="all, delete-orphan"
    )


class PartSymptom(Base):
    __tablename__ = "part_symptoms"
    __table_args__ = (UniqueConstraint("part_ps_number", "symptom_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_ps_number: Mapped[str] = mapped_column(
        String(16), ForeignKey("parts.ps_number", ondelete="CASCADE")
    )
    symptom_id: Mapped[int] = mapped_column(Integer, ForeignKey("symptoms.id", ondelete="CASCADE"))

    part: Mapped[Part] = relationship(back_populates="symptom_links")
    symptom: Mapped[Symptom] = relationship(back_populates="part_links")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(settings.embedding_dim))
    part_ps_number: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("parts.ps_number", ondelete="SET NULL")
    )
    model_number: Mapped[str | None] = mapped_column(String(32))
    source_url: Mapped[str | None] = mapped_column(String(512))
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    part: Mapped[Part | None] = relationship(back_populates="documents")
