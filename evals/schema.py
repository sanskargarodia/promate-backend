"""Eval case schema — shared by trajectory, live, and judge layers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "compatibility",
    "installation",
    "troubleshooting",
    "out_of_scope",
    "injection",
    "multi_turn",
    "canonical",
]

DATASET_CATEGORIES: tuple[Category, ...] = (
    "compatibility",
    "installation",
    "troubleshooting",
    "out_of_scope",
    "injection",
    "multi_turn",
)


class EvalCase(BaseModel):
    """One eval row from `evals/datasets/*.jsonl`."""

    id: str
    category: Category
    message: str | None = None
    turns: list[str] = Field(default_factory=list)
    state: dict = Field(default_factory=dict)
    expect_tools: list[str] = Field(default_factory=list)
    expect_intent: str | None = None
    expect_clarification: bool = False
    expect_refusal: bool = False
    in_scope: bool = True
    expect_contains: list[str] = Field(default_factory=list)
    expect_not_contains: list[str] = Field(default_factory=list)
    expect_events: list[str] = Field(default_factory=list)
    expect_grounding_failure: bool = False

    @property
    def is_multi_turn(self) -> bool:
        return len(self.turns) > 1

    def primary_message(self) -> str:
        if self.turns:
            return self.turns[0]
        return self.message or ""

    def routing_message(self) -> str:
        if self.is_multi_turn:
            return self.turns[-1]
        return self.primary_message()

    def expects_handoff(self) -> bool:
        return (
            "purchase_handoff" in self.expect_tools
            or "purchase_handoff" in self.expect_events
        )
