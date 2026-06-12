"""Conversion journey state machine for conversational commerce handoff."""

from __future__ import annotations

from enum import StrEnum

from app.schemas.transactional import PartDetails, PurchaseHandoffPayload


class TransactionPhase(StrEnum):
    SEARCHING = "SEARCHING"
    IDENTIFIED = "IDENTIFIED"
    COMPATIBILITY_CONFIRMED = "COMPATIBILITY_CONFIRMED"
    PURCHASE_READY = "PURCHASE_READY"


class TransactionStateMachine:
    """Tracks SEARCHING → IDENTIFIED → COMPATIBILITY_CONFIRMED → PURCHASE_READY."""

    def __init__(self, phase: TransactionPhase | str = TransactionPhase.SEARCHING) -> None:
        if isinstance(phase, str):
            phase = TransactionPhase(phase)
        self.phase = phase

    def after_search(self, *, parts_found: int) -> None:
        """Single unambiguous match advances to IDENTIFIED; multiple hits stay in SEARCHING."""
        if parts_found == 1 and self.phase == TransactionPhase.SEARCHING:
            self.phase = TransactionPhase.IDENTIFIED

    def after_part_details(self, details: PartDetails) -> None:
        if details.found:
            self.phase = TransactionPhase.IDENTIFIED

    def after_compatibility(self, *, compatible: bool | None) -> None:
        if compatible is True and self.phase in {
            TransactionPhase.IDENTIFIED,
            TransactionPhase.SEARCHING,
        }:
            self.phase = TransactionPhase.COMPATIBILITY_CONFIRMED

    def after_purchase_intent(self) -> None:
        if self.phase in {
            TransactionPhase.IDENTIFIED,
            TransactionPhase.COMPATIBILITY_CONFIRMED,
        }:
            self.phase = TransactionPhase.PURCHASE_READY

    def can_handoff(self) -> bool:
        return self.phase == TransactionPhase.PURCHASE_READY

    def handoff_blocked_reason(self) -> str:
        if self.phase == TransactionPhase.SEARCHING:
            return "Please search for or identify a part before ordering."
        if self.phase == TransactionPhase.IDENTIFIED:
            return (
                "I can help you order once you confirm you're ready to buy this part."
            )
        if self.phase == TransactionPhase.COMPATIBILITY_CONFIRMED:
            return "Tell me when you're ready to order and I'll link you to PartSelect.com."
        return "Please identify a part before ordering."

    def after_handoff(self, payload: PurchaseHandoffPayload) -> None:
        if payload.allowed:
            self.phase = TransactionPhase.PURCHASE_READY
