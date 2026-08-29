from __future__ import annotations

import hashlib
import io
import json
import stat
import time
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Protocol

from .ack import verify_sealed_object
from .ack_provenance import GitHubAPIReader, HashLedger
from .activator import canonical_hash
from .execution_grant import ExecutionGrantLedger, verify_execution_grant
from .execution_transport import ExecutionTransportLedger, verify_execution_transport_receipt

REPOSITORY = "Hawkar-usls/Janus-Demiurge"
API_BASE = "https://api.github.com"
WORKFLOW_ID = 345491145
WORKFLOW_PATH = ".github/workflows/janus-activator-readonly-execution.yml"
WORKFLOW_BLOB_SHA = "8cb52d643c87fca38c844f4f2eee5ea9ecea5317"
PROTOCOL_PATH = "protocol/ACTIVATOR_READONLY_EXECUTION-v0.1.json"
PROTOCOL_BLOB_SHA = "7343dc9272f6199c99126c30258fee417f1c0063"
RECEIPT_SCHEMA_PATH = "protocol/ACTIVATOR_EXECUTION_RECEIPT-v0.1.schema.json"
RECEIPT_SCHEMA_BLOB_SHA = "83100c112ab54811858bb2587386d028ed964cc9"
HANDLER_PATH = "tools/activator_readonly_execution.py"
HANDLER_BLOB_SHA = "584e134d674854c21f2f28f686391ee791534a2e"
CREDENTIAL_SOURCE = "ENV:JANUS_ACK_PROVENANCE_TOKEN"
TRUST_MODEL = "GITHUB_ACTIONS_PLATFORM_AND_TLS_TRUST_MODEL"
SOURCE_BASIS = "GITHUB_API_RUN_METADATA_PLUS_EXACT_EXECUTION_ARTIFACT_PLUS_PINNED_EXECUTOR_BLOBS_UNDER_GITHUB_TLS_AND_PLATFORM_TRUST"
ALLOWED_EVENTS = {"repository_dispatch", "workflow_dispatch"}
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_MEMBERS = 20
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024


class GitHubReader(Protocol):
    def get_json(self, url: str) -> Any: ...
    def get_bytes(self, url: str) -> bytes: ...


def _contents_url(path: str, head_sha: str) -> str:
    encoded_path = urllib.parse.quote(path, safe="/")
    return f"{API_BASE}/repos/{REPOSITORY}/contents/{encoded_path}?ref={urllib.parse.quote(head_sha, safe='')}"


def _safe_execution_artifact(data: bytes) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("EXECUTION_ARTIFACT_ARCHIVE_EMPTY")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("EXECUTION_ARTIFACT_ARCHIVE_TOO_LARGE")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("EXECUTION_ARTIFACT_NOT_VALID_ZIP") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("EXECUTION_ARTIFACT_TOO_MANY_MEMBERS")
        total = 0
        candidates: Dict[str, list[zipfile.ZipInfo]] = {"receipt.json": [], "snapshot.json": []}
        for info in infos:
            normalized = info.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if normalized.startswith("/") or path.is_absolute() or ".." in path.parts:
                raise ValueError("EXECUTION_ARTIFACT_PATH_TRAVERSAL")
            if path.parts and ":" in path.parts[0]:
                raise ValueError("EXECUTION_ARTIFACT_DRIVE_PATH")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError("EXECUTION_ARTIFACT_SYMLINK_REJECTED")
            if info.flag_bits & 0x1:
                raise ValueError("EXECUTION_ARTIFACT_ENCRYPTED_MEMBER_REJECTED")
            if info.is_dir():
                continue
            total += int(info.file_size)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("EXECUTION_ARTIFACT_UNCOMPRESSED_LIMIT_EXCEEDED")
            if path.name in candidates:
                candidates[path.name].append(info)
        if any(len(candidates[name]) != 1 for name in candidates):
            raise ValueError("EXECUTION_ARTIFACT_REQUIRES_EXACTLY_ONE_RECEIPT_AND_SNAPSHOT")
        try:
            receipt = json.loads(archive.read(candidates["receipt.json"][0]).decode("utf-8"))
            snapshot = json.loads(archive.read(candidates["snapshot.json"][0]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RuntimeError, KeyError) as exc:
            raise ValueError("EXECUTION_ARTIFACT_JSON_INVALID") from exc
        if not isinstance(receipt, dict) or not isinstance(snapshot, dict):
            raise ValueError("EXECUTION_ARTIFACT_JSON_NOT_OBJECT")
        return receipt, snapshot


def verify_execution_receipt(receipt: Dict[str, Any]) -> bool:
    if not isinstance(receipt, dict):
        return False
    claimed = str(receipt.get("receipt_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(receipt)
    body.pop("receipt_hash", None)
    if canonical_hash(body) != claimed:
        return False
    expected_id = "exec-" + canonical_hash({
        "grant_hash": receipt.get("grant_hash"),
        "grant_id": receipt.get("grant_id"),
        "target_head_sha": receipt.get("target_head_sha"),
        "operation": "READ_ONLY_ORIENTATION_SNAPSHOT",
    })
    return all([
        receipt.get("schema") == "janus.demiurge.activator_execution_receipt.v0.1",
        receipt.get("execution_id") == expected_id,
        receipt.get("source_actor") == "Hawkar-usls",
        receipt.get("source_actor_trust_model") == "PINNED_GITHUB_ACTOR:Hawkar-usls",
        receipt.get("target_repository") == REPOSITORY,
        isinstance(receipt.get("target_head_sha"), str) and len(receipt["target_head_sha"]) == 40,
        receipt.get("operation") == "READ_ONLY_ORIENTATION_SNAPSHOT",
        receipt.get("risk_class") == "R0_INTERNAL_READ_ONLY_ORIENTATION",
        receipt.get("execution_scope") == "TARGET_REPOSITORY_LOCAL_READ_ONLY_METADATA",
        receipt.get("terminal") == "EXECUTED_READ_ONLY_ORIENTATION",
        receipt.get("execution_authorized") is True,
        receipt.get("execution_performed") is True,
        isinstance(receipt.get("snapshot_hash"), str) and len(receipt["snapshot_hash"]) == 64,
        receipt.get("target_process_network_access") is False,
        receipt.get("model_access") is False,
        receipt.get("repository_write_performed") is False,
        receipt.get("command_authority_granted") is False,
        receipt.get("claim_authority_granted") is False,
        receipt.get("scientific_evidence_authority_granted") is False,
        receipt.get("external_effect_authorized") is False,
        receipt.get("external_effect_performed") is False,
        receipt.get("physical_runtime_effect_authorized") is False,
    ])


def verify_orientation_snapshot(snapshot: Dict[str, Any], receipt: Dict[str, Any]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    claimed = str(snapshot.get("snapshot_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(snapshot)
    body.pop("snapshot_hash", None)
    if canonical_hash(body) != claimed:
        return False
    return all([
        snapshot.get("schema") == "janus.demiurge.readonly_orientation_snapshot.v0.1",
        snapshot.get("repository") == REPOSITORY,
        snapshot.get("target_head_sha") == receipt.get("target_head_sha"),
        snapshot.get("snapshot_hash") == receipt.get("snapshot_hash"),
        snapshot.get("source_scope") == "CHECKED_OUT_REPOSITORY_ONLY",
        snapshot.get("target_process_network_access") is False,
        snapshot.get("model_access") is False,
        snapshot.get("repository_write_performed") is False,
        snapshot.get("external_effect_performed") is False,
        snapshot.get("claim_authority_granted") is False,
        snapshot.get("scientific_evidence_authority_granted") is False,
        isinstance(snapshot.get("counts"), dict),
        isinstance(snapshot.get("selected_control_file_sha256"), dict),
    ])


class GitHubExecutionReturnVerifier:
    def __init__(self, state_dir: str | Path = "state/activator", *, reader: Optional[GitHubReader] = None) -> None:
        self.state_dir = Path(state_dir)
        self.reader = reader
        self.ledger = HashLedger(self.state_dir / "execution_provenance_ledger.jsonl", "parent_execution_provenance_hash")

    @staticmethod
    def _provenance_id(run_id: int, artifact_id: Optional[int], archive_sha: Optional[str], receipt_hash: Optional[str]) -> str:
        return "execp-" + canonical_hash({
            "run_id": int(run_id),
            "artifact_id": artifact_id,
            "archive_sha256": archive_sha,
            "execution_receipt_hash": receipt_hash,
        })

    def _seal(self, run_id: int, *, terminal: str, reasons: list[str], observed: Optional[Dict[str, Any]] = None, source_authenticated: bool = False) -> Dict[str, Any]:
        observed = observed or {}
        receipt = {
            "schema": "janus.activator.execution_provenance_receipt.v0.8",
            "execution_provenance_id": self._provenance_id(run_id, observed.get("artifact_id"), observed.get("artifact_archive_sha256"), observed.get("execution_receipt_hash")),
            "created_at": time.time(),
            "parent_execution_provenance_hash": self.ledger.tip_hash(),
            "run_id": int(run_id),
            "repository": str(observed.get("repository") or REPOSITORY),
            "workflow_id": observed.get("workflow_id"),
            "workflow_path": observed.get("workflow_path"),
            "head_sha": observed.get("head_sha"),
            "run_event": observed.get("run_event"),
            "run_status": observed.get("run_status"),
            "run_conclusion": observed.get("run_conclusion"),
            "workflow_blob_sha": observed.get("workflow_blob_sha"),
            "protocol_blob_sha": observed.get("protocol_blob_sha"),
            "receipt_schema_blob_sha": observed.get("receipt_schema_blob_sha"),
            "handler_blob_sha": observed.get("handler_blob_sha"),
            "artifact_id": observed.get("artifact_id"),
            "artifact_name": observed.get("artifact_name"),
            "artifact_expired": observed.get("artifact_expired"),
            "artifact_archive_sha256": observed.get("artifact_archive_sha256"),
            "execution_receipt_hash": observed.get("execution_receipt_hash"),
            "execution_id": observed.get("execution_id"),
            "grant_id": observed.get("grant_id"),
            "grant_hash": observed.get("grant_hash"),
            "snapshot_hash": observed.get("snapshot_hash"),
            "source_authenticated": bool(source_authenticated),
            "source_authentication_basis": SOURCE_BASIS,
            "trust_model": TRUST_MODEL,
            "credential_source": CREDENTIAL_SOURCE,
            "credential_value_persisted": False,
            "target_execution_observed": bool(source_authenticated and observed.get("execution_terminal") == "EXECUTED_READ_ONLY_ORIENTATION"),
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("EXECUTION_PROVENANCE_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def verify_run(self, run_id: int, *, token: str) -> tuple[Dict[str, Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        run_id = int(run_id)
        if run_id < 1:
            raise ValueError("RUN_ID_MUST_BE_POSITIVE")
        if not str(token).strip():
            return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_NO_CREDENTIAL", reasons=["GitHub provenance credential is absent; no API request was attempted."]), None, None

        reader: GitHubReader = self.reader or GitHubAPIReader(str(token))
        observed: Dict[str, Any] = {"repository": REPOSITORY}
        try:
            run = reader.get_json(f"{API_BASE}/repos/{REPOSITORY}/actions/runs/{run_id}")
            if not isinstance(run, dict):
                raise ValueError("RUN_METADATA_NOT_OBJECT")
            observed.update({
                "repository": str(((run.get("repository") or {}) if isinstance(run.get("repository"), dict) else {}).get("full_name") or ""),
                "workflow_id": run.get("workflow_id"),
                "workflow_path": run.get("path"),
                "head_sha": run.get("head_sha"),
                "run_event": run.get("event"),
                "run_status": run.get("status"),
                "run_conclusion": run.get("conclusion"),
            })
            head_repo = run.get("head_repository") if isinstance(run.get("head_repository"), dict) else {}
            if (
                observed["repository"] != REPOSITORY
                or (head_repo.get("full_name") not in {None, REPOSITORY})
                or observed["workflow_id"] != WORKFLOW_ID
                or observed["workflow_path"] != WORKFLOW_PATH
                or observed["run_status"] != "completed"
                or observed["run_conclusion"] != "success"
                or observed["run_event"] not in ALLOWED_EVENTS
                or not isinstance(observed["head_sha"], str)
                or len(observed["head_sha"]) != 40
            ):
                return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_RUN_METADATA", reasons=["Run metadata does not match the admitted successful execution endpoint contract."], observed=observed), None, None

            head_sha = str(observed["head_sha"])
            pins = [
                ("workflow_blob_sha", WORKFLOW_PATH, WORKFLOW_BLOB_SHA),
                ("protocol_blob_sha", PROTOCOL_PATH, PROTOCOL_BLOB_SHA),
                ("receipt_schema_blob_sha", RECEIPT_SCHEMA_PATH, RECEIPT_SCHEMA_BLOB_SHA),
                ("handler_blob_sha", HANDLER_PATH, HANDLER_BLOB_SHA),
            ]
            for field, path, expected_sha in pins:
                node = reader.get_json(_contents_url(path, head_sha))
                actual = node.get("sha") if isinstance(node, dict) else None
                observed[field] = actual
                if actual != expected_sha:
                    return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_PIN_MISMATCH", reasons=[f"Pinned execution source mismatch for {path}."], observed=observed), None, None

            listing = reader.get_json(f"{API_BASE}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100")
            artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
            if not isinstance(artifacts, list):
                return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_ARTIFACT", reasons=["Exact-run artifact listing is missing or malformed."], observed=observed), None, None
            expected_name = f"janus-activator-execution-receipt-{run_id}"
            matches = [a for a in artifacts if isinstance(a, dict) and a.get("name") == expected_name]
            if len(matches) != 1:
                return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_ARTIFACT", reasons=["Exact run must contain exactly one admitted execution receipt artifact."], observed=observed), None, None
            artifact = matches[0]
            artifact_id = artifact.get("id")
            artifact_run = artifact.get("workflow_run") if isinstance(artifact.get("workflow_run"), dict) else {}
            observed.update({"artifact_id": artifact_id, "artifact_name": artifact.get("name"), "artifact_expired": artifact.get("expired")})
            if not isinstance(artifact_id, int) or artifact_id < 1 or artifact.get("expired") is not False or (artifact_run.get("id") is not None and artifact_run.get("id") != run_id):
                return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_ARTIFACT", reasons=["Execution artifact id/expiry/exact-run binding failed."], observed=observed), None, None

            archive = reader.get_bytes(f"{API_BASE}/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip")
            observed["artifact_archive_sha256"] = hashlib.sha256(archive).hexdigest()
            execution_receipt, snapshot = _safe_execution_artifact(archive)
            observed.update({
                "execution_receipt_hash": execution_receipt.get("receipt_hash"),
                "execution_id": execution_receipt.get("execution_id"),
                "grant_id": execution_receipt.get("grant_id"),
                "grant_hash": execution_receipt.get("grant_hash"),
                "snapshot_hash": execution_receipt.get("snapshot_hash"),
                "execution_terminal": execution_receipt.get("terminal"),
            })
            if not verify_execution_receipt(execution_receipt) or not verify_orientation_snapshot(snapshot, execution_receipt):
                return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_INVALID_RESULT", reasons=["Execution receipt or orientation snapshot failed independent HOME integrity/authority checks."], observed=observed), None, None
            if execution_receipt.get("target_head_sha") != head_sha:
                return self._seal(run_id, terminal="EXECUTION_PROVENANCE_BLOCKED_HEAD_MISMATCH", reasons=["Execution receipt target HEAD does not equal the authenticated GitHub workflow run head SHA."], observed=observed), None, None

            return self._seal(
                run_id,
                terminal="EXECUTION_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL",
                reasons=[
                    "GitHub execution run metadata matches the pinned successful Janus-Demiurge endpoint.",
                    "Workflow, execution protocol, receipt schema and handler blobs match pinned admitted revisions at the exact target HEAD.",
                    "Exactly one non-expired exact-run execution artifact passed safe ZIP extraction.",
                    "Execution receipt and snapshot independently passed HOME integrity, deterministic identity and authority-ceiling verification.",
                    "Observed execution is bounded to repository-local orientation and grants no claim, scientific-evidence or external-effect authority.",
                ],
                observed=observed,
                source_authenticated=True,
            ), execution_receipt, snapshot
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            return self._seal(run_id, terminal="EXECUTION_PROVENANCE_UNRESOLVED_FETCH_ERROR", reasons=[f"GitHub execution provenance read failed with {type(exc).__name__}; execution remains unresolved."], observed=observed), None, None


class JanusExecutionResultFinalizer:
    def __init__(self, state_dir: str | Path = "state/activator") -> None:
        self.state_dir = Path(state_dir)
        self.grant_ledger = ExecutionGrantLedger(self.state_dir / "execution_grant_ledger.jsonl")
        self.transport_ledger = ExecutionTransportLedger(self.state_dir / "execution_transport_ledger.jsonl")
        self.provenance_ledger = HashLedger(self.state_dir / "execution_provenance_ledger.jsonl", "parent_execution_provenance_hash")
        self.final_ledger = HashLedger(self.state_dir / "execution_result_finalization_ledger.jsonl", "parent_execution_result_hash")

    @staticmethod
    def _finalization_id(grant: Dict[str, Any], transport: Dict[str, Any], provenance: Dict[str, Any]) -> str:
        return "execf-" + canonical_hash({
            "grant_hash": grant.get("grant_hash"),
            "execution_transport_receipt_hash": transport.get("receipt_hash"),
            "execution_provenance_receipt_hash": provenance.get("receipt_hash"),
        })

    def _seal(self, grant: Dict[str, Any], transport: Dict[str, Any], provenance: Dict[str, Any], execution_receipt: Dict[str, Any], *, terminal: str, reasons: list[str], execution_observed: bool = False) -> Dict[str, Any]:
        receipt = {
            "schema": "janus.activator.execution_result_final_receipt.v0.8",
            "execution_result_id": self._finalization_id(grant, transport, provenance),
            "created_at": time.time(),
            "parent_execution_result_hash": self.final_ledger.tip_hash(),
            "grant_hash": str(grant.get("grant_hash") or canonical_hash(grant)),
            "grant_id": str(grant.get("grant_id") or "UNKNOWN"),
            "execution_transport_receipt_hash": str(transport.get("receipt_hash") or canonical_hash(transport)),
            "execution_provenance_receipt_hash": str(provenance.get("receipt_hash") or canonical_hash(provenance)),
            "target_execution_receipt_hash": execution_receipt.get("receipt_hash"),
            "execution_id": execution_receipt.get("execution_id"),
            "target_head_sha": execution_receipt.get("target_head_sha"),
            "snapshot_hash": execution_receipt.get("snapshot_hash"),
            "source_authenticated_under_github_trust_model": provenance.get("source_authenticated") is True,
            "target_execution_observed_under_github_trust_model": bool(execution_observed),
            "target_execution_operation": "READ_ONLY_ORIENTATION_SNAPSHOT",
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
        }
        sealed = self.final_ledger.append(receipt)
        if not self.final_ledger.verify():
            raise RuntimeError("EXECUTION_RESULT_FINALIZATION_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def finalize(self, grant: Dict[str, Any], transport: Dict[str, Any], provenance: Dict[str, Any], execution_receipt: Dict[str, Any]) -> Dict[str, Any]:
        objects = [grant, transport, provenance, execution_receipt]
        if not all(isinstance(x, dict) for x in objects):
            return self._seal({}, {}, {}, {}, terminal="EXECUTION_RESULT_BLOCKED_INVALID_INPUT", reasons=["Execution result finalization requires four object inputs."])
        if not self.grant_ledger.verify() or not self.transport_ledger.verify() or not self.provenance_ledger.verify() or not self.final_ledger.verify():
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_LOCAL_LINEAGE_INVALID", reasons=["At least one required HOME execution parent/hash chain is invalid."])
        if not verify_execution_grant(grant) or not any(row == grant for row in self.grant_ledger.read()):
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_GRANT_NOT_LOCAL", reasons=["Execution grant is not an exact valid row in persistent HOME grant lineage."])
        if not verify_execution_transport_receipt(transport) or not any(row == transport for row in self.transport_ledger.read()):
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_TRANSPORT_NOT_LOCAL", reasons=["Execution transport receipt is not an exact valid row in persistent HOME transport lineage."])
        if transport.get("grant_id") != grant.get("grant_id") or transport.get("grant_hash") != grant.get("grant_hash") or transport.get("network_boundary_entered") is not True or transport.get("terminal") not in {"EXECUTION_TRANSPORT_SENT_AWAITING_RESULT", "EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED"}:
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_TRANSPORT_BINDING", reasons=["Execution transport is not a reconciliable network-boundary row for this exact grant."])
        if not verify_sealed_object(provenance, "receipt_hash") or provenance.get("schema") != "janus.activator.execution_provenance_receipt.v0.8" or not any(row == provenance for row in self.provenance_ledger.read()):
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_PROVENANCE_NOT_LOCAL", reasons=["Execution provenance receipt is not an exact valid persistent HOME row."])
        if provenance.get("terminal") != "EXECUTION_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL" or provenance.get("source_authenticated") is not True:
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_SOURCE_UNAUTHENTICATED", reasons=["Target execution source was not authenticated under the pinned GitHub Actions trust model."])
        if not verify_execution_receipt(execution_receipt):
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_INVALID_TARGET_RECEIPT", reasons=["Target execution receipt failed independent HOME verification."])
        if (
            execution_receipt.get("grant_id") != grant.get("grant_id")
            or execution_receipt.get("grant_hash") != grant.get("grant_hash")
            or provenance.get("grant_id") != grant.get("grant_id")
            or provenance.get("grant_hash") != grant.get("grant_hash")
            or provenance.get("execution_receipt_hash") != execution_receipt.get("receipt_hash")
            or provenance.get("execution_id") != execution_receipt.get("execution_id")
            or provenance.get("snapshot_hash") != execution_receipt.get("snapshot_hash")
        ):
            return self._seal(grant, transport, provenance, execution_receipt, terminal="EXECUTION_RESULT_BLOCKED_LINEAGE_MISMATCH", reasons=["Grant, execution transport, authenticated target receipt and provenance bindings disagree."])

        finalization_id = self._finalization_id(grant, transport, provenance)
        existing = [row for row in self.final_ledger.read() if row.get("execution_result_id") == finalization_id and row.get("terminal") == "EXECUTION_RESULT_AUTHENTICATED_READ_ONLY_ORIENTATION_OBSERVED"]
        if existing:
            return existing[0]

        return self._seal(
            grant,
            transport,
            provenance,
            execution_receipt,
            terminal="EXECUTION_RESULT_AUTHENTICATED_READ_ONLY_ORIENTATION_OBSERVED",
            reasons=[
                "Persistent HOME grant and execution-transport lineage bind to the authenticated Janus-Demiurge execution artifact.",
                "A bounded READ_ONLY_ORIENTATION_SNAPSHOT execution is observed under the pinned GitHub Actions platform/TLS trust model.",
                "This observation grants no command, claim, scientific-evidence, world-truth, external-effect or physical-runtime authority.",
            ],
            execution_observed=True,
        )


__all__ = [
    "GitHubExecutionReturnVerifier",
    "JanusExecutionResultFinalizer",
    "verify_execution_receipt",
    "verify_orientation_snapshot",
]
