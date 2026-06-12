"""Transaction phase state machine tests."""

from app.agents.transaction_state import TransactionPhase, TransactionStateMachine
from app.schemas.transactional import PartDetails, PurchaseHandoffPayload


def test_identified_after_part_details() -> None:
    machine = TransactionStateMachine()
    machine.after_part_details(
        PartDetails(
            part_id="PS11752778",
            name="Bin",
            appliance_type="refrigerator",
        )
    )
    assert machine.phase == TransactionPhase.IDENTIFIED


def test_search_single_match_advances_to_identified() -> None:
    machine = TransactionStateMachine()
    machine.after_search(parts_found=1)
    assert machine.phase == TransactionPhase.IDENTIFIED


def test_search_multiple_matches_stay_searching() -> None:
    machine = TransactionStateMachine()
    machine.after_search(parts_found=3)
    assert machine.phase == TransactionPhase.SEARCHING


def test_compatibility_confirmed_after_check() -> None:
    machine = TransactionStateMachine(TransactionPhase.IDENTIFIED)
    machine.after_compatibility(compatible=True)
    assert machine.phase == TransactionPhase.COMPATIBILITY_CONFIRMED


def test_purchase_ready_after_intent() -> None:
    machine = TransactionStateMachine(TransactionPhase.IDENTIFIED)
    machine.after_purchase_intent()
    assert machine.phase == TransactionPhase.PURCHASE_READY
    assert machine.can_handoff()


def test_handoff_updates_phase() -> None:
    machine = TransactionStateMachine(TransactionPhase.IDENTIFIED)
    machine.after_purchase_intent()
    machine.after_handoff(
        PurchaseHandoffPayload(
            allowed=True,
            ps_number="PS11752778",
            source_url="https://www.partselect.com/PS11752778.htm",
        )
    )
    assert machine.phase == TransactionPhase.PURCHASE_READY
