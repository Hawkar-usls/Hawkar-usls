import io
import json
import urllib.error
import zipfile
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.execution_grant import ExecutionGrantLedger, verify_execution_grant
from janus_spi.execution_return import (
    HANDLER_BLOB_SHA,
    PROTOCOL_BLOB_SHA,
    RECEIPT_SCHEMA_BLOB_SHA,
    WORKFLOW_BLOB_SHA,
    WORKFLOW_ID,
    WORKFLOW_PATH,
    GitHubExecutionReturnVerifier,
    JanusExecutionResultFinalizer,
)
from janus_spi.execution_transport import JanusExecutionTransportBroker


def valid_grant(parent=None):
    grant = {
        "schema": "janus.activator.execution_grant.v0.7",
        "grant_id": "",
        "created_at": 1.0,
        "parent_grant_hash": parent,
        "authenticated_final_receipt_hash": "a" * 64,
        "finalization_id": "ackf-" + "b" * 64,
        "packet_id": "dsp-" + "c" * 64,
        "packet_hash": "d" * 64,
        "target_organ": "Hawkar-usls/Janus-Demiurge",
        "operation": "READ_ONLY_ORIENTATION_SNAPSHOT",
        "risk_class": "R0_INTERNAL_READ_ONLY_ORIENTATION",
        "execution_scope": "TARGET_REPOSITORY_LOCAL_READ_ONLY_METADATA",
        "target_execution_authorized": True,
        "repository_write_authorized": False,
        "network_access_authorized": False,
        "model_access_authorized": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "EXECUTION_GRANT_ISSUED_READ_ONLY_ORIENTATION",
        "reasons": ["v0.8 unit-test grant"],
    }
    grant["grant_id"] = "xg-" + canonical_hash({
        "authenticated_final_receipt_hash": grant["authenticated_final_receipt_hash"],
        "packet_id": grant["packet_id"],
        "packet_hash": grant["packet_hash"],
        "target_organ": grant["target_organ"],
        "operation": grant["operation"],
    })
    grant["grant_hash"] = canonical_hash(grant)
    assert verify_execution_grant(grant)
    return grant


class Fake204:
    status = 204


class CountingOpener:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or Fake204()

    def __call__(self, request, timeout=20.0):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def execution_artifact(grant, head_sha="9" * 40):
    snapshot = {
        "schema": "janus.demiurge.readonly_orientation_snapshot.v0.1",
        "repository": "Hawkar-usls/Janus-Demiurge",
        "target_head_sha": head_sha,
        "counts": {"agent_manifests": 17, "workflows": 8, "protocol_json": 6, "python_tests": 12, "python_tools": 9},
        "selected_control_file_sha256": {"PROJECT_STATUS.json": "e" * 64},
        "source_scope": "CHECKED_OUT_REPOSITORY_ONLY",
        "target_process_network_access": False,
        "model_access": False,
        "repository_write_performed": False,
        "external_effect_performed": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
    }
    snapshot["snapshot_hash"] = canonical_hash(snapshot)
    receipt = {
        "schema": "janus.demiurge.activator_execution_receipt.v0.1",
        "execution_id": "",
        "created_at": 2.0,
        "source_actor": "Hawkar-usls",
        "source_actor_trust_model": "PINNED_GITHUB_ACTOR:Hawkar-usls",
        "grant_id": grant["grant_id"],
        "grant_hash": grant["grant_hash"],
        "target_repository": "Hawkar-usls/Janus-Demiurge",
        "target_head_sha": head_sha,
        "operation": "READ_ONLY_ORIENTATION_SNAPSHOT",
        "risk_class": "R0_INTERNAL_READ_ONLY_ORIENTATION",
        "execution_scope": "TARGET_REPOSITORY_LOCAL_READ_ONLY_METADATA",
        "execution_authorized": True,
        "execution_performed": True,
        "snapshot_hash": snapshot["snapshot_hash"],
        "target_process_network_access": False,
        "model_access": False,
        "repository_write_performed": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "external_effect_performed": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "EXECUTED_READ_ONLY_ORIENTATION",
        "reasons": ["unit-test target result"],
    }
    receipt["execution_id"] = "exec-" + canonical_hash({
        "grant_hash": receipt["grant_hash"],
        "grant_id": receipt["grant_id"],
        "target_head_sha": receipt["target_head_sha"],
        "operation": receipt["operation"],
    })
    receipt["receipt_hash"] = canonical_hash(receipt)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("receipt.json", json.dumps(receipt))
        z.writestr("snapshot.json", json.dumps(snapshot))
    return buffer.getvalue(), receipt, snapshot


class FakeReader:
    def __init__(self, grant, run_id=12345, head_sha="9" * 40):
        self.run_id = run_id
        self.head_sha = head_sha
        self.archive, self.receipt, self.snapshot = execution_artifact(grant, head_sha)

    def get_json(self, url):
        if url.endswith(f"/actions/runs/{self.run_id}"):
            return {
                "repository": {"full_name": "Hawkar-usls/Janus-Demiurge"},
                "head_repository": {"full_name": "Hawkar-usls/Janus-Demiurge"},
                "workflow_id": WORKFLOW_ID,
                "path": WORKFLOW_PATH,
                "head_sha": self.head_sha,
                "event": "repository_dispatch",
                "status": "completed",
                "conclusion": "success",
            }
        if "/contents/" in url:
            if "janus-activator-readonly-execution.yml" in url:
                return {"sha": WORKFLOW_BLOB_SHA}
            if "ACTIVATOR_READONLY_EXECUTION-v0.1.json" in url:
                return {"sha": PROTOCOL_BLOB_SHA}
            if "ACTIVATOR_EXECUTION_RECEIPT-v0.1.schema.json" in url:
                return {"sha": RECEIPT_SCHEMA_BLOB_SHA}
            if "activator_readonly_execution.py" in url:
                return {"sha": HANDLER_BLOB_SHA}
        if url.endswith(f"/actions/runs/{self.run_id}/artifacts?per_page=100"):
            return {"artifacts": [{
                "id": 777,
                "name": f"janus-activator-execution-receipt-{self.run_id}",
                "expired": False,
                "workflow_run": {"id": self.run_id},
            }]}
        raise AssertionError(url)

    def get_bytes(self, url):
        assert url.endswith("/actions/artifacts/777/zip")
        return self.archive


def prepare_state(tmp_path):
    state = tmp_path / "state"
    grant_ledger = ExecutionGrantLedger(state / "execution_grant_ledger.jsonl")
    grant = valid_grant(grant_ledger.tip_hash())
    stored = grant_ledger.append(grant)
    assert stored == grant
    opener = CountingOpener()
    transport = JanusExecutionTransportBroker(state_dir=state, opener=opener).send(grant, token="token")
    assert transport["terminal"] == "EXECUTION_TRANSPORT_SENT_AWAITING_RESULT"
    assert opener.calls == 1
    return state, grant, transport


def test_execution_transport_success_and_replay_block(tmp_path):
    state = tmp_path / "state"
    grant = valid_grant()
    opener = CountingOpener()
    broker = JanusExecutionTransportBroker(state_dir=state, opener=opener)
    first = broker.send(grant, token="token")
    second = broker.send(grant, token="token")
    assert first["terminal"] == "EXECUTION_TRANSPORT_SENT_AWAITING_RESULT"
    assert first["network_boundary_entered"] is True
    assert first["automatic_retry_allowed"] is False
    assert second["terminal"] == "EXECUTION_TRANSPORT_REPLAY_BLOCKED"
    assert opener.calls == 1


def test_execution_transport_no_credential_is_pre_effect_and_retryable(tmp_path):
    state = tmp_path / "state"
    grant = valid_grant()
    opener = CountingOpener()
    broker = JanusExecutionTransportBroker(state_dir=state, opener=opener)
    blocked = broker.send(grant, token="")
    sent = broker.send(grant, token="token")
    assert blocked["terminal"] == "EXECUTION_TRANSPORT_BLOCKED_NO_CREDENTIAL"
    assert blocked["network_boundary_entered"] is False
    assert blocked["automatic_retry_allowed"] is True
    assert sent["terminal"] == "EXECUTION_TRANSPORT_SENT_AWAITING_RESULT"
    assert opener.calls == 1


def test_execution_transport_timeout_becomes_unknown_and_no_retry(tmp_path):
    grant = valid_grant()
    opener = CountingOpener(urllib.error.URLError("timeout"))
    broker = JanusExecutionTransportBroker(state_dir=tmp_path / "state", opener=opener)
    first = broker.send(grant, token="token")
    second = broker.send(grant, token="token")
    assert first["terminal"] == "EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED"
    assert first["network_boundary_entered"] is True
    assert first["automatic_retry_allowed"] is False
    assert second["terminal"] == "EXECUTION_TRANSPORT_REPLAY_BLOCKED"
    assert opener.calls == 1


def test_authenticated_execution_return_finalizes_observed_execution(tmp_path):
    state, grant, transport = prepare_state(tmp_path)
    reader = FakeReader(grant)
    verifier = GitHubExecutionReturnVerifier(state_dir=state, reader=reader)
    provenance, execution_receipt, snapshot = verifier.verify_run(reader.run_id, token="token")
    assert provenance["terminal"] == "EXECUTION_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL"
    assert provenance["source_authenticated"] is True
    assert provenance["target_execution_observed"] is True
    assert execution_receipt is not None
    assert snapshot is not None

    final = JanusExecutionResultFinalizer(state_dir=state).finalize(grant, transport, provenance, execution_receipt)
    assert final["terminal"] == "EXECUTION_RESULT_AUTHENTICATED_READ_ONLY_ORIENTATION_OBSERVED"
    assert final["target_execution_observed_under_github_trust_model"] is True
    assert final["claim_authority_granted"] is False
    assert final["scientific_evidence_authority_granted"] is False
    assert final["world_truth_authority_granted"] is False
    assert final["external_effect_authorized"] is False


def test_return_pin_mismatch_blocks_authentication(tmp_path):
    state, grant, _ = prepare_state(tmp_path)
    reader = FakeReader(grant)
    original = reader.get_json
    def wrong(url):
        value = original(url)
        if "/contents/" in url and "activator_readonly_execution.py" in url:
            return {"sha": "0" * 40}
        return value
    reader.get_json = wrong
    provenance, execution_receipt, snapshot = GitHubExecutionReturnVerifier(state_dir=state, reader=reader).verify_run(reader.run_id, token="token")
    assert provenance["terminal"] == "EXECUTION_PROVENANCE_BLOCKED_PIN_MISMATCH"
    assert provenance["source_authenticated"] is False
    assert execution_receipt is None
    assert snapshot is None


def test_return_grant_mismatch_blocks_finalization(tmp_path):
    state, grant, transport = prepare_state(tmp_path)
    reader = FakeReader(grant)
    verifier = GitHubExecutionReturnVerifier(state_dir=state, reader=reader)
    provenance, execution_receipt, _ = verifier.verify_run(reader.run_id, token="token")
    assert execution_receipt is not None
    forged = dict(execution_receipt)
    forged["grant_id"] = "xg-" + "1" * 64
    forged["execution_id"] = "exec-" + canonical_hash({
        "grant_hash": forged["grant_hash"],
        "grant_id": forged["grant_id"],
        "target_head_sha": forged["target_head_sha"],
        "operation": forged["operation"],
    })
    forged.pop("receipt_hash")
    forged["receipt_hash"] = canonical_hash(forged)
    final = JanusExecutionResultFinalizer(state_dir=state).finalize(grant, transport, provenance, forged)
    assert final["terminal"] == "EXECUTION_RESULT_BLOCKED_LINEAGE_MISMATCH"
    assert final["target_execution_observed_under_github_trust_model"] is False
