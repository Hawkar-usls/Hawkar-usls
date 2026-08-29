from __future__ import annotations

import json
from pathlib import Path

from janus_spi.activator import ActivationEvent, JanusActivator, canonical_hash
from janus_spi.ack import JanusAckReconciler
from janus_spi.dispatch import JanusDispatchBroker
from janus_spi.transport import JanusTransportBroker


class FakeResponse:
    def __init__(self, status: int = 204) -> None:
        self.status = status


class FakeOpener:
    def __init__(self, *, status: int = 204, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls = 0

    def __call__(self, request, timeout=20.0):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status)


def make_packet_and_state(tmp_path: Path):
    state = tmp_path / "state"
    activation = JanusActivator(state_dir=state).activate(
        ActivationEvent.build(
            source_kind="GITHUB_COMMIT",
            source_ref="Hawkar-usls/janus-meta-registry@ack-test",
            payload={"kind": "registry_change"},
            classifications=["research_or_anomaly_investigation"],
            fresh=True,
        )
    )
    dispatch = JanusDispatchBroker(state_dir=state).dispatch(
        activation,
        target_organ="Hawkar-usls/Janus-Demiurge",
    )
    packet = json.loads(Path(dispatch["packet_path"]).read_text(encoding="utf-8"))
    return state, packet


def make_transport(state: Path, packet: dict, *, status: int = 204, error: Exception | None = None):
    broker = JanusTransportBroker(state_dir=state, opener=FakeOpener(status=status, error=error))
    return broker.send(packet, token="unit-test-token")


def make_ack(packet: dict, *, accepted: bool = True, terminal: str = "ACK_ACCEPTED_NO_EXECUTION") -> dict:
    ack = {
        "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
        "created_at": 1.0,
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "accepted": accepted,
        "terminal": terminal,
        "reasons": ["synthetic offline test ACK"],
        "execution_authorized": False,
        "execution_performed": False,
        "claim_authority_granted": False,
        "external_effect_authorized": False,
    }
    ack["ack_hash"] = canonical_hash(ack)
    return ack


def reseal_ack(ack: dict) -> dict:
    ack = dict(ack)
    ack.pop("ack_hash", None)
    ack["ack_hash"] = canonical_hash(ack)
    return ack


def reseal_transport(receipt: dict) -> dict:
    receipt = dict(receipt)
    receipt.pop("receipt_hash", None)
    receipt["receipt_hash"] = canonical_hash(receipt)
    return receipt


def test_accepted_ack_is_only_structurally_bound_source_unverified(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
    assert receipt["ack_integrity_valid"] is True
    assert receipt["ack_source_authenticity"] == "UNVERIFIED_OFFLINE"
    assert receipt["ack_source_authenticated"] is False
    assert receipt["delivery_confirmed"] is False
    assert receipt["transport_ambiguity_resolved"] is False
    assert receipt["execution_authorized"] is False
    assert receipt["execution_performed"] is False
    assert receipt["claim_authority_granted"] is False
    assert receipt["external_effect_authorized"] is False


def test_fabricated_but_self_hashed_ack_cannot_claim_source_authenticity(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    fabricated = make_ack(packet)
    fabricated["reasons"] = ["fabricated locally but internally self-consistent"]
    fabricated = reseal_ack(fabricated)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, fabricated)

    assert receipt["terminal"] == "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
    assert receipt["ack_integrity_valid"] is True
    assert receipt["ack_source_authenticated"] is False
    assert receipt["delivery_confirmed"] is False


def test_late_structural_ack_does_not_resolve_ambiguous_transport_without_source_provenance(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet, error=TimeoutError("ambiguous timeout"))
    assert transport["terminal"] == "TRANSPORT_OUTCOME_UNDETERMINED"
    ack = make_ack(packet)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
    assert receipt["transport_terminal_before"] == "TRANSPORT_OUTCOME_UNDETERMINED"
    assert receipt["transport_ambiguity_resolved"] is False
    assert receipt["delivery_confirmed"] is False
    assert any("remains unresolved" in reason for reason in receipt["reasons"])


def test_tampered_ack_is_blocked(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet)
    ack["terminal"] = "ACK_ACCEPTED_NO_EXECUTION_TAMPERED"

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_INVALID_ACK"
    assert receipt["ack_integrity_valid"] is False
    assert receipt["delivery_confirmed"] is False


def test_resealed_ack_for_different_packet_is_blocked_by_lineage_mismatch(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet)
    ack["packet_id"] = "dsp-" + "b" * 64
    ack = reseal_ack(ack)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_PACKET_MISMATCH"
    assert receipt["ack_integrity_valid"] is True
    assert receipt["delivery_confirmed"] is False


def test_tampered_transport_receipt_is_blocked(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    transport["terminal"] = "TRANSPORT_SENT_AWAITING_ACK_TAMPERED"
    ack = make_ack(packet)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_INVALID_TRANSPORT_RECEIPT"
    assert receipt["delivery_confirmed"] is False


def test_pre_effect_transport_state_cannot_be_reconciled(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = JanusTransportBroker(state_dir=state, opener=FakeOpener()).send(packet, token="")
    assert transport["terminal"] == "TRANSPORT_BLOCKED_NO_CREDENTIAL"
    ack = make_ack(packet)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_TRANSPORT_NOT_RECONCILABLE"
    assert receipt["delivery_confirmed"] is False


def test_transport_receipt_for_other_packet_is_blocked_even_if_resealed(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    transport["packet_id"] = "dsp-" + "c" * 64
    transport = reseal_transport(transport)
    ack = make_ack(packet)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_PACKET_MISMATCH"
    assert receipt["delivery_confirmed"] is False


def test_resealed_ack_authority_escalation_is_blocked(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet)
    ack["execution_performed"] = True
    ack = reseal_ack(ack)

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_AUTHORITY_ESCALATION"
    assert receipt["ack_integrity_valid"] is True
    assert receipt["execution_performed"] is False
    assert receipt["delivery_confirmed"] is False


def test_inconsistent_ack_state_is_blocked(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet, accepted=True, terminal="ACK_REJECTED_INVALID_PACKET")

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_INCONSISTENT_ACK_STATE"
    assert receipt["ack_integrity_valid"] is True


def test_structurally_valid_rejection_is_preserved_without_authentication(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet, accepted=False, terminal="ACK_REJECTED_POLICY")

    receipt = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
    assert receipt["ack_integrity_valid"] is True
    assert receipt["ack_source_authenticated"] is False
    assert receipt["delivery_confirmed"] is False


def test_duplicate_structural_reconciliation_does_not_create_second_state_transition(tmp_path):
    state, packet = make_packet_and_state(tmp_path)
    transport = make_transport(state, packet)
    ack = make_ack(packet)
    reconciler = JanusAckReconciler(state_dir=state)

    first = reconciler.reconcile(packet, transport, ack)
    second = reconciler.reconcile(packet, transport, ack)

    assert first["terminal"] == "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
    assert second["terminal"] == "ACK_ALREADY_STRUCTURALLY_RECONCILED"
    assert first["reconciliation_id"] == second["reconciliation_id"]
    assert second["delivery_confirmed"] is False
    assert reconciler.ledger.verify() is True
