"""Chat API request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class ChatEvent(BaseModel):
    type: str
    content: str | None = None
    thread_id: str | None = None
    part: dict[str, object] | None = None
