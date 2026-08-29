import json
from pathlib import Path

from janus_spi.activator import ActivationEvent, JanusActivator
from janus_spi.dispatch import JanusDispatchBroker, verify_dispatch_packet


def research_receipt(tmp_path: Path):
    state = tmp_path / "state"
    activator = JanusActivator(state_dir=state)
    receipt = activator.activate(ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="Hawkar-usls/janus-meta-registry@abc123",
        payload={"sha": "abc123", "kind": "registry_change"},
        classifications=["research_or_anomaly_investigation"],
        fresh=True,
    ))
    return state, receipt


def test_selected_research_targets_emit_read_only_packets(tmp_path):
    state, receipt = research_receipt(tmp_path)
    broker = JanusDispatchBroker(state_dir=state)
    targets = receipt["routes_selected"][0]["organs"]
    decisions = [broker.dispatch(receipt, target_organ=target) for target in targets]

    assert {row["terminal"] for row in decisions} == {"AUTHORIZED_INTERNAL_HANDOFF"}
    assert all(row["dispatch_authorized"] is True for row in decisions)
    assert all(row["external_effect_authorized"] is False for row in decisions)
    assert len(list((state / "dispatch_outbox").glob("*.json"))) == 3

    for row in decisions:
        packet = json.loads(Path(row["packet_path"]).read_text(encoding="utf-8"))
        assert verify_dispatch_packet(packet) is True
        assert packet["operation"] == "WAKE_ORGAN_READ_ONLY"
        assert packet["risk_class"] == "R0_INTERNAL_READ_ONLY_ORGAN_WAKE"
        assert packet["effect_scope"] == "GITHUB_INTERNAL_READ_ONLY_ANALYSIS"
        assert packet["claim_authority_granted"] is False
        assert packet["command_authority_granted"] is False
        assert packet["external_effect_authorized"] is False
        assert packet["required_gates"] == receipt["routes_selected"][0]["required_gates"]

    assert broker.ledger.verify() is True


def test_duplicate_dispatch_is_idempotent_and_does_not_emit_second_packet(tmp_path):
    state, receipt = research_receipt(tmp_path)
    broker = JanusDispatchBroker(state_dir=state)
    target = "Hawkar-usls/Janus-Demiurge"

    first = broker.dispatch(receipt, target_organ=target)
    second = broker.dispatch(receipt, target_organ=target)

    assert first["terminal"] == "AUTHORIZED_INTERNAL_HANDOFF"
    assert second["terminal"] == "ALREADY_EMITTED"
    assert first["dispatch_id"] == second["dispatch_id"]
    assert first["packet_hash"] == second["packet_hash"]
    assert len(list((state / "dispatch_outbox").glob("*.json"))) == 1
    assert broker.ledger.verify() is True


def test_tampered_activation_receipt_is_blocked(tmp_path):
    state, receipt = research_receipt(tmp_path)
    tampered = dict(receipt)
    tampered["terminal"] = "ROUTE_PROPOSED_BUT_TAMPERED"
    broker = JanusDispatchBroker(state_dir=state)

    decision = broker.dispatch(tampered, target_organ="Hawkar-usls/Janus-Demiurge")

    assert decision["terminal"] == "BLOCKED_INVALID_ACTIVATION_RECEIPT"
    assert decision["dispatch_authorized"] is False
    assert len(list((state / "dispatch_outbox").glob("*.json"))) == 0


def test_unselected_target_is_blocked(tmp_path):
    state, receipt = research_receipt(tmp_path)
    broker = JanusDispatchBroker(state_dir=state)

    decision = broker.dispatch(receipt, target_organ="Hawkar-usls/AIFC")

    assert decision["terminal"] == "BLOCKED_TARGET_NOT_SELECTED"
    assert decision["dispatch_authorized"] is False


def test_human_effect_surface_is_never_auto_dispatched(tmp_path):
    state = tmp_path / "state"
    activator = JanusActivator(state_dir=state)
    receipt = activator.activate(ActivationEvent.build(
        source_kind="TERMINAL",
        source_ref="terminal:effect-request",
        payload={"request": "external effect"},
        classifications=["human_operator_effect_request"],
        fresh=True,
    ))
    broker = JanusDispatchBroker(state_dir=state)

    decision = broker.dispatch(receipt, target_organ="Hawkar-usls/-Terminal-for-Janus")

    assert decision["terminal"] == "BLOCKED_FORBIDDEN_AUTO_TARGET"
    assert decision["dispatch_authorized"] is False
    assert decision["external_effect_authorized"] is False
    assert len(list((state / "dispatch_outbox").glob("*.json"))) == 0


def test_non_read_only_operation_is_blocked(tmp_path):
    state, receipt = research_receipt(tmp_path)
    broker = JanusDispatchBroker(state_dir=state)

    decision = broker.dispatch(
        receipt,
        target_organ="Hawkar-usls/Janus-Demiurge",
        operation="EXECUTE_AND_WRITE",
    )

    assert decision["terminal"] == "BLOCKED_OPERATION"
    assert decision["dispatch_authorized"] is False
    assert decision["external_effect_authorized"] is False
    assert len(list((state / "dispatch_outbox").glob("*.json"))) == 0
