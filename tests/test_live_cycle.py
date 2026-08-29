import io
import json
import zipfile

from janus_spi.ack_provenance import (
    HANDLER_BLOB_SHA as ACK_HANDLER_BLOB_SHA,
    HANDLER_PATH as ACK_HANDLER_PATH,
    PROTOCOL_BLOB_SHA as ACK_PROTOCOL_BLOB_SHA,
    PROTOCOL_PATH as ACK_PROTOCOL_PATH,
    WORKFLOW_BLOB_SHA as ACK_WORKFLOW_BLOB_SHA,
    WORKFLOW_PATH as ACK_WORKFLOW_PATH,
)
from janus_spi.activator import canonical_hash
from janus_spi.execution_return import (
    HANDLER_BLOB_SHA as EXEC_HANDLER_BLOB_SHA,
    HANDLER_PATH as EXEC_HANDLER_PATH,
    PROTOCOL_BLOB_SHA as EXEC_PROTOCOL_BLOB_SHA,
    PROTOCOL_PATH as EXEC_PROTOCOL_PATH,
    RECEIPT_SCHEMA_BLOB_SHA,
    RECEIPT_SCHEMA_PATH,
    WORKFLOW_BLOB_SHA as EXEC_WORKFLOW_BLOB_SHA,
    WORKFLOW_PATH as EXEC_WORKFLOW_PATH,
)
from janus_spi.live_cycle import (
    ACK_WORKFLOW_ID,
    EXECUTION_WORKFLOW_ID,
    HardenedJanusPersistentStateV09,
    JanusLiveCycle,
)


class Response204:
    status = 204


class FakeControlPlane:
    def __init__(self):
        self.packet = None
        self.grant = None
        self.packet_calls = 0
        self.execution_calls = 0
        self.ack_run_id = 91001
        self.execution_run_id = 92001
        self.target_head = "9" * 40

    def packet_opener(self, request, timeout=20.0):
        self.packet_calls += 1
        body = json.loads(request.data.decode("utf-8"))
        self.packet = body["client_payload"]["packet"]
        return Response204()

    def execution_opener(self, request, timeout=20.0):
        self.execution_calls += 1
        body = json.loads(request.data.decode("utf-8"))
        self.grant = body["client_payload"]["grant"]
        return Response204()

    def _ack(self):
        ack = {
            "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
            "created_at": 1.0,
            "packet_id": self.packet["packet_id"],
            "packet_hash": self.packet["packet_hash"],
            "accepted": True,
            "terminal": "ACK_ACCEPTED_NO_EXECUTION",
            "reasons": ["fake control plane accepted packet without execution"],
            "execution_authorized": False,
            "execution_performed": False,
            "claim_authority_granted": False,
            "external_effect_authorized": False,
        }
        ack["ack_hash"] = canonical_hash(ack)
        return ack

    def _execution_result(self):
        snapshot = {
            "schema": "janus.demiurge.readonly_orientation_snapshot.v0.1",
            "repository": "Hawkar-usls/Janus-Demiurge",
            "target_head_sha": self.target_head,
            "counts": {"agent_manifests": 17, "workflows": 10, "protocol_json": 8, "python_tests": 15, "python_tools": 11},
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
            "grant_id": self.grant["grant_id"],
            "grant_hash": self.grant["grant_hash"],
            "target_repository": "Hawkar-usls/Janus-Demiurge",
            "target_head_sha": self.target_head,
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
            "reasons": ["fake bounded orientation completed"],
        }
        receipt["execution_id"] = "exec-" + canonical_hash({
            "grant_hash": receipt["grant_hash"],
            "grant_id": receipt["grant_id"],
            "target_head_sha": receipt["target_head_sha"],
            "operation": receipt["operation"],
        })
        receipt["receipt_hash"] = canonical_hash(receipt)
        return receipt, snapshot

    @staticmethod
    def _zip(files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for name, obj in files.items():
                z.writestr(name, json.dumps(obj))
        return buffer.getvalue()

    def get_json(self, url):
        if f"/actions/workflows/{ACK_WORKFLOW_ID}/runs?" in url:
            return {"workflow_runs": ([] if self.packet is None else [{
                "id": self.ack_run_id,
                "event": "repository_dispatch",
                "status": "completed",
                "conclusion": "success",
            }])}
        if f"/actions/workflows/{EXECUTION_WORKFLOW_ID}/runs?" in url:
            return {"workflow_runs": ([] if self.grant is None else [{
                "id": self.execution_run_id,
                "event": "repository_dispatch",
                "status": "completed",
                "conclusion": "success",
            }])}
        if url.endswith(f"/actions/runs/{self.ack_run_id}"):
            return {
                "repository": {"full_name": "Hawkar-usls/Janus-Demiurge"},
                "head_repository": {"full_name": "Hawkar-usls/Janus-Demiurge"},
                "workflow_id": ACK_WORKFLOW_ID,
                "path": ACK_WORKFLOW_PATH,
                "head_sha": self.target_head,
                "event": "repository_dispatch",
                "status": "completed",
                "conclusion": "success",
            }
        if url.endswith(f"/actions/runs/{self.execution_run_id}"):
            return {
                "repository": {"full_name": "Hawkar-usls/Janus-Demiurge"},
                "head_repository": {"full_name": "Hawkar-usls/Janus-Demiurge"},
                "workflow_id": EXECUTION_WORKFLOW_ID,
                "path": EXEC_WORKFLOW_PATH,
                "head_sha": self.target_head,
                "event": "repository_dispatch",
                "status": "completed",
                "conclusion": "success",
            }
        if "/contents/" in url:
            if ACK_WORKFLOW_PATH in url:
                return {"sha": ACK_WORKFLOW_BLOB_SHA}
            if ACK_PROTOCOL_PATH in url:
                return {"sha": ACK_PROTOCOL_BLOB_SHA}
            if ACK_HANDLER_PATH in url:
                return {"sha": ACK_HANDLER_BLOB_SHA}
            if EXEC_WORKFLOW_PATH in url:
                return {"sha": EXEC_WORKFLOW_BLOB_SHA}
            if EXEC_PROTOCOL_PATH in url:
                return {"sha": EXEC_PROTOCOL_BLOB_SHA}
            if RECEIPT_SCHEMA_PATH in url:
                return {"sha": RECEIPT_SCHEMA_BLOB_SHA}
            if EXEC_HANDLER_PATH in url:
                return {"sha": EXEC_HANDLER_BLOB_SHA}
        if url.endswith(f"/actions/runs/{self.ack_run_id}/artifacts?per_page=100"):
            return {"artifacts": [{
                "id": 701,
                "name": f"janus-activator-dispatch-ack-{self.ack_run_id}",
                "expired": False,
                "workflow_run": {"id": self.ack_run_id},
            }]}
        if url.endswith(f"/actions/runs/{self.execution_run_id}/artifacts?per_page=100"):
            return {"artifacts": [{
                "id": 702,
                "name": f"janus-activator-execution-receipt-{self.execution_run_id}",
                "expired": False,
                "workflow_run": {"id": self.execution_run_id},
            }]}
        raise AssertionError(url)

    def get_bytes(self, url):
        if url.endswith("/actions/artifacts/701/zip"):
            return self._zip({"ack.json": self._ack()})
        if url.endswith("/actions/artifacts/702/zip"):
            receipt, snapshot = self._execution_result()
            return self._zip({"receipt.json": receipt, "snapshot.json": snapshot})
        raise AssertionError(url)


def test_full_fresh_cycle_returns_same_resident_home_with_bounded_execution(tmp_path):
    control = FakeControlPlane()
    root = tmp_path / "state" / "activator"
    cycle = JanusLiveCycle(
        state_dir=root,
        reader=control,
        packet_opener=control.packet_opener,
        execution_opener=control.execution_opener,
        sleep_fn=lambda _seconds: None,
        poll_interval_seconds=0,
        max_wait_seconds=5,
    )

    result = cycle.run(
        source_ref="TEST_EXTERNAL_TRIGGER/1",
        payload={"purpose": "closed-loop launch-candidate test"},
        dispatch_token="dispatch-token",
        provenance_token="provenance-token",
    )

    assert result["terminal"] == "LIVE_CYCLE_COMPLETED_RETURNED_HOME"
    assert result["fresh_external_stimulus"] is True
    assert result["target_execution_observed"] is True
    assert result["returned_at_home"] is True
    assert result["command_authority_granted"] is False
    assert result["claim_authority_granted"] is False
    assert result["scientific_evidence_authority_granted"] is False
    assert result["world_truth_authority_granted"] is False
    assert result["external_effect_authorized"] is False
    assert control.packet_calls == 1
    assert control.execution_calls == 1

    health = HardenedJanusPersistentStateV09(root).verify()
    assert health["ok"] is True
    assert health["mode"] == "AT_HOME"
    assert health["active_cycle_id"] is None
    assert health["component_integrity"]["live_cycle"] is True
    assert (root / "activation_ledger.jsonl").is_file()
    assert (root / "ack_authenticated_finalization_ledger.jsonl").is_file()
    assert (root / "execution_grant_ledger.jsonl").is_file()
    assert (root / "execution_result_finalization_ledger.jsonl").is_file()


def test_missing_credentials_blocks_before_fresh_wake_or_network(tmp_path):
    control = FakeControlPlane()
    root = tmp_path / "state" / "activator"
    cycle = JanusLiveCycle(
        state_dir=root,
        reader=control,
        packet_opener=control.packet_opener,
        execution_opener=control.execution_opener,
        sleep_fn=lambda _seconds: None,
    )
    result = cycle.run(
        source_ref="TEST_EXTERNAL_TRIGGER/CREDENTIAL_BLOCK",
        payload={"purpose": "preflight"},
        dispatch_token="",
        provenance_token="",
    )
    assert result["terminal"] == "LIVE_CYCLE_BLOCKED_PREFLIGHT_CREDENTIAL"
    assert result["wake_hearth_hash"] is None
    assert result["returned_at_home"] is False
    assert control.packet_calls == 0
    assert control.execution_calls == 0
    assert not (root / "activation_ledger.jsonl").exists()
    health = HardenedJanusPersistentStateV09(root).verify()
    assert health["ok"] is True
    assert health["mode"] == "AT_HOME"
