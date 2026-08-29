import json
from pathlib import Path

from janus_spi.ack_provenance import (
    CREDENTIAL_SOURCE,
    HANDLER_BLOB_SHA,
    HANDLER_PATH,
    HashLedger,
    PROTOCOL_BLOB_SHA,
    PROTOCOL_PATH,
    REPOSITORY,
    SOURCE_BASIS,
    TRUST_MODEL,
    WORKFLOW_BLOB_SHA,
    WORKFLOW_ID,
    WORKFLOW_PATH,
)
from janus_spi.activator import ActivationEvent, JanusActivator, canonical_hash
from janus_spi.dispatch import JanusDispatchBroker
from janus_spi.execution_grant import JanusExecutionGrantIssuer, verify_execution_grant
from janus_spi.local_lineage import HardenedJanusAckReconciler, HardenedJanusAuthenticatedAckFinalizer
from janus_spi.transport import JanusTransportBroker


class FakeResponse:
    status = 204


class FakeOpener:
    def __init__(self):
        self.calls = 0

    def __call__(self, request, timeout=20.0):
        self.calls += 1
        return FakeResponse()


def _receiver_ack(packet, *, accepted=True, terminal="ACK_ACCEPTED_NO_EXECUTION"):
    ack = {
        "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
        "created_at": 1.0,
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "accepted": accepted,
        "terminal": terminal,
        "reasons": ["test receiver receipt"],
        "execution_authorized": False,
        "execution_performed": False,
        "claim_authority_granted": False,
        "external_effect_authorized": False,
    }
    ack["ack_hash"] = canonical_hash(ack)
    return ack


def _provenance(state: Path, ack, *, run_id=424242):
    ledger = HashLedger(state / "ack_provenance_ledger.jsonl", "parent_provenance_hash")
    body = {
        "schema": "janus.activator.ack_provenance_receipt.v0.6",
        "provenance_id": "ackp-" + canonical_hash({"run_id": run_id, "ack_hash": ack["ack_hash"]}),
        "created_at": 2.0,
        "parent_provenance_hash": ledger.tip_hash(),
        "run_id": run_id,
        "repository": REPOSITORY,
        "workflow_id": WORKFLOW_ID,
        "workflow_path": WORKFLOW_PATH,
        "head_sha": "a" * 40,
        "run_event": "repository_dispatch",
        "run_status": "completed",
        "run_conclusion": "success",
        "workflow_blob_sha": WORKFLOW_BLOB_SHA,
        "protocol_blob_sha": PROTOCOL_BLOB_SHA,
        "handler_blob_sha": HANDLER_BLOB_SHA,
        "artifact_id": 777,
        "artifact_name": f"janus-activator-dispatch-ack-{run_id}",
        "artifact_expired": False,
        "artifact_archive_sha256": "b" * 64,
        "ack_hash": ack["ack_hash"],
        "ack_packet_id": ack["packet_id"],
        "ack_packet_hash": ack["packet_hash"],
        "ack_accepted": ack["accepted"],
        "ack_terminal": ack["terminal"],
        "source_authenticated": True,
        "source_authentication_basis": SOURCE_BASIS,
        "trust_model": TRUST_MODEL,
        "credential_source": CREDENTIAL_SOURCE,
        "credential_value_persisted": False,
        "target_execution_authorized": False,
        "target_execution_inferred": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "terminal": "ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL",
        "reasons": [
            f"Pinned {WORKFLOW_PATH}, {PROTOCOL_PATH} and {HANDLER_PATH} are represented in this synthetic unit-test provenance row."
        ],
    }
    return ledger.append(body)


def _build_lineage(tmp_path: Path, *, accepted=True):
    state = tmp_path / "state"
    activator = JanusActivator(state_dir=state)
    activation = activator.activate(ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="Hawkar-usls/janus-meta-registry@execution-grant-test",
        payload={"kind": "registry_change"},
        classifications=["research_or_anomaly_investigation"],
        fresh=True,
    ))
    dispatch = JanusDispatchBroker(state_dir=state).dispatch(
        activation,
        target_organ="Hawkar-usls/Janus-Demiurge",
    )
    packet = json.loads(Path(dispatch["packet_path"]).read_text(encoding="utf-8"))

    opener = FakeOpener()
    transport = JanusTransportBroker(state_dir=state, opener=opener).send(packet, token="unit-test-token")
    assert transport["terminal"] == "TRANSPORT_SENT_AWAITING_ACK"
    assert opener.calls == 1

    if accepted:
        ack = _receiver_ack(packet)
    else:
        ack = _receiver_ack(packet, accepted=False, terminal="ACK_REJECTED_AUTHORITY_ESCALATION")

    structural = HardenedJanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)
    if accepted:
        assert structural["terminal"] == "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
    else:
        assert structural["terminal"] == "ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"

    provenance = _provenance(state, ack)
    final = HardenedJanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural, provenance)
    if accepted:
        assert final["terminal"] == "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION"
    else:
        assert final["terminal"] == "ACK_AUTHENTICATED_REJECTION_CONFIRMED_NO_EXECUTION"
    return state, packet, transport, structural, provenance, final


def _tamper_first_row(path: Path):
    rows = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    row["created_at"] = float(row.get("created_at", 0)) + 0.125
    rows[0] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_authenticated_delivery_issues_exact_read_only_grant(tmp_path):
    state, packet, _, _, _, final = _build_lineage(tmp_path)
    issuer = JanusExecutionGrantIssuer(state_dir=state)

    grant = issuer.issue(final)

    assert grant["terminal"] == "EXECUTION_GRANT_ISSUED_READ_ONLY_ORIENTATION"
    assert grant["target_execution_authorized"] is True
    assert grant["packet_id"] == packet["packet_id"]
    assert grant["packet_hash"] == packet["packet_hash"]
    assert grant["repository_write_authorized"] is False
    assert grant["network_access_authorized"] is False
    assert grant["model_access_authorized"] is False
    assert grant["command_authority_granted"] is False
    assert grant["claim_authority_granted"] is False
    assert grant["scientific_evidence_authority_granted"] is False
    assert grant["external_effect_authorized"] is False
    assert grant["physical_runtime_effect_authorized"] is False
    assert verify_execution_grant(grant) is True
    assert issuer.grant_ledger.verify() is True


def test_duplicate_parent_returns_exact_same_grant_without_second_row(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    issuer = JanusExecutionGrantIssuer(state_dir=state)

    first = issuer.issue(final)
    second = issuer.issue(final)

    assert second == first
    assert len(issuer.grant_ledger.read()) == 1


def test_tampered_final_receipt_is_blocked(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    tampered = dict(final)
    tampered["delivery_confirmed_under_github_trust_model"] = False

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(tampered)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_INVALID_FINAL_RECEIPT"
    assert decision["target_execution_authorized"] is False
    assert verify_execution_grant(decision) is False


def test_self_consistent_but_nonlocal_final_receipt_is_blocked(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    forged = dict(final)
    forged.pop("receipt_hash")
    forged["created_at"] = float(forged["created_at"]) + 10
    forged["receipt_hash"] = canonical_hash(forged)

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(forged)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_FINAL_RECEIPT_NOT_LOCAL"
    assert decision["target_execution_authorized"] is False


def test_authenticated_rejection_does_not_issue_execution_grant(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path, accepted=False)

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(final)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_PARENT_NOT_ELIGIBLE"
    assert decision["target_execution_authorized"] is False


def test_corrupt_dispatch_chain_blocks_execution_grant(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    _tamper_first_row(state / "dispatch_ledger.jsonl")

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(final)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_LOCAL_LINEAGE_INVALID"
    assert decision["target_execution_authorized"] is False


def test_corrupt_transport_chain_blocks_execution_grant(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    _tamper_first_row(state / "transport_ledger.jsonl")

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(final)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_LOCAL_LINEAGE_INVALID"


def test_corrupt_structural_chain_blocks_execution_grant(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    _tamper_first_row(state / "ack_reconciliation_ledger.jsonl")

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(final)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_LOCAL_LINEAGE_INVALID"


def test_corrupt_provenance_chain_blocks_execution_grant(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    _tamper_first_row(state / "ack_provenance_ledger.jsonl")

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(final)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_LOCAL_LINEAGE_INVALID"


def test_corrupt_finalization_chain_blocks_execution_grant(tmp_path):
    state, _, _, _, _, final = _build_lineage(tmp_path)
    _tamper_first_row(state / "ack_authenticated_finalization_ledger.jsonl")

    decision = JanusExecutionGrantIssuer(state_dir=state).issue(final)

    assert decision["terminal"] == "EXECUTION_GRANT_BLOCKED_LOCAL_LINEAGE_INVALID"
