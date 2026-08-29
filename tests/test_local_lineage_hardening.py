from __future__ import annotations

import json
from pathlib import Path

from janus_spi import JanusAckReconciler, JanusAuthenticatedAckFinalizer
from janus_spi.ack_provenance import HashLedger
from janus_spi.activator import ActivationEvent, JanusActivator, canonical_hash
from janus_spi.dispatch import JanusDispatchBroker
from janus_spi.local_lineage import HardenedJanusAckReconciler, HardenedJanusAuthenticatedAckFinalizer
from janus_spi.transport import JanusTransportBroker


class FakeResponse:
    def __init__(self, status: int = 204) -> None:
        self.status = status


class FakeOpener:
    def __call__(self, request, timeout=20.0):
        return FakeResponse(204)


def make_ack(packet: dict) -> dict:
    ack = {
        "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
        "created_at": 1.0,
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "accepted": True,
        "terminal": "ACK_ACCEPTED_NO_EXECUTION",
        "reasons": ["local lineage hardening test"],
        "execution_authorized": False,
        "execution_performed": False,
        "claim_authority_granted": False,
        "external_effect_authorized": False,
    }
    ack["ack_hash"] = canonical_hash(ack)
    return ack


def make_lineage(state: Path, suffix: str):
    activation = JanusActivator(state_dir=state).activate(
        ActivationEvent.build(
            source_kind="GITHUB_COMMIT",
            source_ref=f"Hawkar-usls/janus-meta-registry@{suffix}",
            payload={"kind": "registry_change", "suffix": suffix},
            classifications=["research_or_anomaly_investigation"],
            fresh=True,
        )
    )
    dispatch = JanusDispatchBroker(state_dir=state).dispatch(
        activation,
        target_organ="Hawkar-usls/Janus-Demiurge",
    )
    packet_path = Path(dispatch["packet_path"])
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    transport = JanusTransportBroker(state_dir=state, opener=FakeOpener()).send(packet, token="test-token")
    ack = make_ack(packet)
    return packet_path, packet, transport, ack


def make_authenticated_provenance(state: Path, structural: dict, marker: str) -> dict:
    ledger = HashLedger(state / "ack_provenance_ledger.jsonl", "parent_provenance_hash")
    receipt = {
        "schema": "janus.activator.ack_provenance_receipt.v0.6",
        "provenance_id": "ackp-" + canonical_hash({"marker": marker, "ack": structural["ack_hash"]}),
        "created_at": 1.0,
        "parent_provenance_hash": ledger.tip_hash(),
        "run_id": 1000 + len(ledger.read()),
        "repository": "Hawkar-usls/Janus-Demiurge",
        "workflow_id": 345454851,
        "workflow_path": ".github/workflows/janus-activator-dispatch-receiver.yml",
        "head_sha": "1" * 40,
        "run_event": "repository_dispatch",
        "run_status": "completed",
        "run_conclusion": "success",
        "workflow_blob_sha": "918b44dd543b179304d48b9d4f942092fda38919",
        "protocol_blob_sha": "f1c465e979e38aa534efc67b92cacd8643b23ee5",
        "handler_blob_sha": "a5f3a89c9d882d417dbbf1bfe12785180cc10180",
        "artifact_id": 7000 + len(ledger.read()),
        "artifact_name": "synthetic-local-provenance-test",
        "artifact_expired": False,
        "artifact_archive_sha256": "2" * 64,
        "ack_hash": structural["ack_hash"],
        "ack_packet_id": structural["packet_id"],
        "ack_packet_hash": structural["packet_hash"],
        "ack_accepted": structural["ack_accepted"],
        "ack_terminal": structural["ack_terminal"],
        "source_authenticated": True,
        "source_authentication_basis": "SYNTHETIC_TEST_ONLY",
        "trust_model": "GITHUB_ACTIONS_PLATFORM_AND_TLS_TRUST_MODEL",
        "credential_source": "ENV:JANUS_ACK_PROVENANCE_TOKEN",
        "credential_value_persisted": False,
        "target_execution_authorized": False,
        "target_execution_inferred": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "terminal": "ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL",
        "reasons": ["synthetic provenance row used only to attack local ledger integrity"],
    }
    return ledger.append(receipt)


def corrupt_first_row(path: Path) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["reasons"] = ["CORRUPTED_EARLIER_ROW_WITHOUT_REHASH"]
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def test_canonical_package_exports_are_hardened_classes():
    assert JanusAckReconciler is HardenedJanusAckReconciler
    assert JanusAuthenticatedAckFinalizer is HardenedJanusAuthenticatedAckFinalizer


def test_replaced_self_hashed_outbox_packet_is_rejected_without_matching_dispatch_receipt(tmp_path):
    state = tmp_path / "state"
    packet_path, packet, transport, ack = make_lineage(state, "replace-outbox")
    fabricated = dict(packet)
    fabricated["route_match"] = "fabricated-but-self-consistent"
    fabricated.pop("packet_hash", None)
    fabricated["packet_hash"] = canonical_hash(fabricated)
    packet_path.write_text(json.dumps(fabricated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fabricated_ack = make_ack(fabricated)

    receipt = HardenedJanusAckReconciler(state_dir=state).reconcile(fabricated, transport, fabricated_ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_PACKET_NOT_IN_LOCAL_OUTBOX"
    assert receipt["packet_local_outbox_bound"] is False
    assert receipt["delivery_confirmed"] is False


def test_corrupt_dispatch_parent_chain_invalidates_packet_lineage(tmp_path):
    state = tmp_path / "state"
    _, packet, transport, ack = make_lineage(state, "dispatch-chain")
    corrupt_first_row(state / "dispatch_ledger.jsonl")

    receipt = HardenedJanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_PACKET_NOT_IN_LOCAL_OUTBOX"
    assert receipt["packet_local_outbox_bound"] is False


def test_corrupt_transport_parent_chain_invalidates_exact_transport_row(tmp_path):
    state = tmp_path / "state"
    _, packet, transport, ack = make_lineage(state, "transport-chain")
    corrupt_first_row(state / "transport_ledger.jsonl")

    receipt = HardenedJanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)

    assert receipt["terminal"] == "ACK_RECONCILIATION_BLOCKED_TRANSPORT_NOT_IN_LOCAL_LEDGER"
    assert receipt["transport_local_ledger_bound"] is False


def test_corrupt_earlier_structural_row_blocks_finalization_even_when_target_row_is_exact(tmp_path):
    state = tmp_path / "state"
    _, packet1, transport1, ack1 = make_lineage(state, "structural-1")
    HardenedJanusAckReconciler(state_dir=state).reconcile(packet1, transport1, ack1)
    _, packet2, transport2, ack2 = make_lineage(state, "structural-2")
    structural2 = HardenedJanusAckReconciler(state_dir=state).reconcile(packet2, transport2, ack2)
    provenance2 = make_authenticated_provenance(state, structural2, "structural-chain")
    corrupt_first_row(state / "ack_reconciliation_ledger.jsonl")

    final = HardenedJanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural2, provenance2)

    assert final["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_BLOCKED_STRUCTURAL_RECEIPT_NOT_LOCAL"
    assert final["delivery_confirmed_under_github_trust_model"] is False


def test_corrupt_earlier_provenance_row_blocks_finalization_even_when_target_row_is_exact(tmp_path):
    state = tmp_path / "state"
    _, packet1, transport1, ack1 = make_lineage(state, "provenance-1")
    structural1 = HardenedJanusAckReconciler(state_dir=state).reconcile(packet1, transport1, ack1)
    make_authenticated_provenance(state, structural1, "provenance-row-1")
    _, packet2, transport2, ack2 = make_lineage(state, "provenance-2")
    structural2 = HardenedJanusAckReconciler(state_dir=state).reconcile(packet2, transport2, ack2)
    provenance2 = make_authenticated_provenance(state, structural2, "provenance-row-2")
    corrupt_first_row(state / "ack_provenance_ledger.jsonl")

    final = HardenedJanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural2, provenance2)

    assert final["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_BLOCKED_PROVENANCE_RECEIPT_NOT_LOCAL"
    assert final["delivery_confirmed_under_github_trust_model"] is False
