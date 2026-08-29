from __future__ import annotations

import hashlib
import io
import json
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Protocol

from .ack import verify_receiver_ack, verify_sealed_object
from .activator import canonical_hash

REPOSITORY = "Hawkar-usls/Janus-Demiurge"
API_BASE = "https://api.github.com"
WORKFLOW_ID = 345454851
WORKFLOW_PATH = ".github/workflows/janus-activator-dispatch-receiver.yml"
WORKFLOW_BLOB_SHA = "918b44dd543b179304d48b9d4f942092fda38919"
PROTOCOL_PATH = "protocol/ACTIVATOR_DISPATCH_RECEIVER-v0.1.json"
PROTOCOL_BLOB_SHA = "f1c465e979e38aa534efc67b92cacd8643b23ee5"
HANDLER_PATH = "tools/activator_dispatch_receiver.py"
HANDLER_BLOB_SHA = "a5f3a89c9d882d417dbbf1bfe12785180cc10180"
CREDENTIAL_SOURCE = "ENV:JANUS_ACK_PROVENANCE_TOKEN"
TRUST_MODEL = "GITHUB_ACTIONS_PLATFORM_AND_TLS_TRUST_MODEL"
SOURCE_BASIS = "GITHUB_API_RUN_METADATA_PLUS_EXACT_RUN_ARTIFACT_PLUS_PINNED_RECEIVER_BLOBS_UNDER_GITHUB_TLS_AND_PLATFORM_TRUST"
ALLOWED_EVENTS = {"repository_dispatch", "workflow_dispatch"}
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_MEMBERS = 20
MAX_UNCOMPRESSED_BYTES = 1024 * 1024


class GitHubReader(Protocol):
    def get_json(self, url: str) -> Any: ...
    def get_bytes(self, url: str) -> bytes: ...


class GitHubAPIReader:
    def __init__(self, token: str, *, opener=urllib.request.urlopen, timeout_seconds: float = 20.0) -> None:
        self.token = token
        self.opener = opener
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "JANUS-Activator-ACK-Provenance/0.6",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def get_json(self, url: str) -> Any:
        with self.opener(self._request(url), timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_bytes(self, url: str) -> bytes:
        with self.opener(self._request(url), timeout=self.timeout_seconds) as response:
            return response.read()


class HashLedger:
    def __init__(self, path: str | Path, parent_field: str) -> None:
        self.path = Path(path)
        self.parent_field = parent_field
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("HASH_LEDGER_ROW_NOT_OBJECT")
            rows.append(row)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["receipt_hash"]) if rows else None

    def append(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(receipt)
        body.pop("receipt_hash", None)
        body["receipt_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return body

    def verify(self) -> bool:
        previous: Optional[str] = None
        for row in self.read():
            if row.get(self.parent_field) != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True

    def contains_exact(self, receipt: Dict[str, Any]) -> bool:
        claimed = receipt.get("receipt_hash") if isinstance(receipt, dict) else None
        return any(row.get("receipt_hash") == claimed and row == receipt for row in self.read())


def _contents_url(path: str, head_sha: str) -> str:
    encoded_path = urllib.parse.quote(path, safe="/")
    return f"{API_BASE}/repos/{REPOSITORY}/contents/{encoded_path}?ref={urllib.parse.quote(head_sha, safe='')}"


def _safe_ack_from_zip(data: bytes) -> Dict[str, Any]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("ACK_ARTIFACT_ARCHIVE_EMPTY")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("ACK_ARTIFACT_ARCHIVE_TOO_LARGE")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("ACK_ARTIFACT_NOT_VALID_ZIP") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("ACK_ARTIFACT_TOO_MANY_MEMBERS")
        total = 0
        candidates: list[zipfile.ZipInfo] = []
        for info in infos:
            normalized = info.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if normalized.startswith("/") or path.is_absolute() or ".." in path.parts:
                raise ValueError("ACK_ARTIFACT_PATH_TRAVERSAL")
            if path.parts and ":" in path.parts[0]:
                raise ValueError("ACK_ARTIFACT_DRIVE_PATH")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError("ACK_ARTIFACT_SYMLINK_REJECTED")
            if info.flag_bits & 0x1:
                raise ValueError("ACK_ARTIFACT_ENCRYPTED_MEMBER_REJECTED")
            if info.is_dir():
                continue
            total += int(info.file_size)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("ACK_ARTIFACT_UNCOMPRESSED_LIMIT_EXCEEDED")
            if path.name == "ack.json":
                candidates.append(info)

        if len(candidates) != 1:
            raise ValueError("ACK_ARTIFACT_REQUIRES_EXACTLY_ONE_ACK_JSON")
        try:
            raw = archive.read(candidates[0])
            ack = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RuntimeError, KeyError) as exc:
            raise ValueError("ACK_ARTIFACT_ACK_JSON_INVALID") from exc
        if not isinstance(ack, dict):
            raise ValueError("ACK_ARTIFACT_ACK_JSON_NOT_OBJECT")
        return ack


class GitHubAckProvenanceVerifier:
    def __init__(self, state_dir: str | Path = "state/activator", *, reader: Optional[GitHubReader] = None) -> None:
        self.state_dir = Path(state_dir)
        self.reader = reader
        self.ledger = HashLedger(self.state_dir / "ack_provenance_ledger.jsonl", "parent_provenance_hash")

    @staticmethod
    def _provenance_id(run_id: int, artifact_id: Optional[int], archive_sha: Optional[str], ack_hash: Optional[str]) -> str:
        return "ackp-" + canonical_hash({
            "run_id": int(run_id),
            "artifact_id": artifact_id,
            "archive_sha256": archive_sha,
            "ack_hash": ack_hash,
        })

    def _seal(
        self,
        run_id: int,
        *,
        terminal: str,
        reasons: list[str],
        observed: Optional[Dict[str, Any]] = None,
        source_authenticated: bool = False,
    ) -> Dict[str, Any]:
        observed = observed or {}
        receipt = {
            "schema": "janus.activator.ack_provenance_receipt.v0.6",
            "provenance_id": self._provenance_id(
                run_id,
                observed.get("artifact_id"),
                observed.get("artifact_archive_sha256"),
                observed.get("ack_hash"),
            ),
            "created_at": time.time(),
            "parent_provenance_hash": self.ledger.tip_hash(),
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
            "handler_blob_sha": observed.get("handler_blob_sha"),
            "artifact_id": observed.get("artifact_id"),
            "artifact_name": observed.get("artifact_name"),
            "artifact_expired": observed.get("artifact_expired"),
            "artifact_archive_sha256": observed.get("artifact_archive_sha256"),
            "ack_hash": observed.get("ack_hash"),
            "ack_packet_id": observed.get("ack_packet_id"),
            "ack_packet_hash": observed.get("ack_packet_hash"),
            "ack_accepted": observed.get("ack_accepted"),
            "ack_terminal": observed.get("ack_terminal"),
            "source_authenticated": bool(source_authenticated),
            "source_authentication_basis": SOURCE_BASIS,
            "trust_model": TRUST_MODEL,
            "credential_source": CREDENTIAL_SOURCE,
            "credential_value_persisted": False,
            "target_execution_authorized": False,
            "target_execution_inferred": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("ACK_PROVENANCE_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def verify_run(self, run_id: int, *, token: str) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        run_id = int(run_id)
        if run_id < 1:
            raise ValueError("RUN_ID_MUST_BE_POSITIVE")
        if not str(token).strip():
            return self._seal(
                run_id,
                terminal="ACK_PROVENANCE_BLOCKED_NO_CREDENTIAL",
                reasons=["Broker credential is absent; no GitHub provenance request was attempted."],
            ), None

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
                or not isinstance(observed["head_sha"], str)
                or len(observed["head_sha"]) < 40
            ):
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_RUN_METADATA",
                    reasons=["GitHub run metadata does not match the admitted repository/workflow/completed-success contract."],
                    observed=observed,
                ), None

            if observed["run_event"] not in ALLOWED_EVENTS:
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_UNADMITTED_EVENT",
                    reasons=["Only repository_dispatch or workflow_dispatch receiver runs may authenticate an ACK artifact."],
                    observed=observed,
                ), None

            head_sha = str(observed["head_sha"])
            pins = [
                ("workflow_blob_sha", WORKFLOW_PATH, WORKFLOW_BLOB_SHA),
                ("protocol_blob_sha", PROTOCOL_PATH, PROTOCOL_BLOB_SHA),
                ("handler_blob_sha", HANDLER_PATH, HANDLER_BLOB_SHA),
            ]
            for field, path, expected_sha in pins:
                node = reader.get_json(_contents_url(path, head_sha))
                actual = node.get("sha") if isinstance(node, dict) else None
                observed[field] = actual
                if actual != expected_sha:
                    return self._seal(
                        run_id,
                        terminal="ACK_PROVENANCE_BLOCKED_PIN_MISMATCH",
                        reasons=[f"Pinned receiver source mismatch for {path}."],
                        observed=observed,
                    ), None

            artifact_listing = reader.get_json(
                f"{API_BASE}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"
            )
            artifacts = artifact_listing.get("artifacts") if isinstance(artifact_listing, dict) else None
            if not isinstance(artifacts, list):
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_ARTIFACT",
                    reasons=["Exact-run artifact listing is missing or malformed."],
                    observed=observed,
                ), None
            expected_name = f"janus-activator-dispatch-ack-{run_id}"
            matches = [a for a in artifacts if isinstance(a, dict) and a.get("name") == expected_name]
            if len(matches) != 1:
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_ARTIFACT",
                    reasons=["Exact run must contain exactly one admitted ACK artifact name."],
                    observed=observed,
                ), None
            artifact = matches[0]
            artifact_id = artifact.get("id")
            artifact_run = artifact.get("workflow_run") if isinstance(artifact.get("workflow_run"), dict) else {}
            observed.update({
                "artifact_id": artifact_id,
                "artifact_name": artifact.get("name"),
                "artifact_expired": artifact.get("expired"),
            })
            if (
                not isinstance(artifact_id, int)
                or artifact_id < 1
                or artifact.get("expired") is not False
                or (artifact_run.get("id") is not None and artifact_run.get("id") != run_id)
            ):
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_ARTIFACT",
                    reasons=["ACK artifact id/expiry/exact-run binding failed verification."],
                    observed=observed,
                ), None

            archive_bytes = reader.get_bytes(
                f"{API_BASE}/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"
            )
            observed["artifact_archive_sha256"] = hashlib.sha256(archive_bytes).hexdigest()
            try:
                ack = _safe_ack_from_zip(archive_bytes)
            except ValueError as exc:
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_ARCHIVE",
                    reasons=[str(exc)],
                    observed=observed,
                ), None

            observed.update({
                "ack_hash": ack.get("ack_hash"),
                "ack_packet_id": ack.get("packet_id"),
                "ack_packet_hash": ack.get("packet_hash"),
                "ack_accepted": ack.get("accepted"),
                "ack_terminal": ack.get("terminal"),
            })
            if not verify_receiver_ack(ack):
                return self._seal(
                    run_id,
                    terminal="ACK_PROVENANCE_BLOCKED_INVALID_ACK",
                    reasons=["ACK inside the exact-run artifact failed self-integrity or schema verification."],
                    observed=observed,
                ), None

            return self._seal(
                run_id,
                terminal="ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL",
                reasons=[
                    "GitHub run repository/workflow/path/event/status/conclusion match the admitted receiver contract.",
                    "Exact-run receiver workflow, protocol, and handler blobs match pinned admitted revisions.",
                    "Exactly one non-expired exact-run ACK artifact was located and its archive passed safe extraction checks.",
                    "ACK self-integrity was verified from artifact bytes.",
                    "Source authentication is bounded to the GitHub Actions platform/TLS trust model and grants no execution, claim, scientific-evidence, or external-effect authority.",
                ],
                observed=observed,
                source_authenticated=True,
            ), ack
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
            return self._seal(
                run_id,
                terminal="ACK_PROVENANCE_UNRESOLVED_FETCH_ERROR",
                reasons=[f"GitHub provenance read failed with {type(exc).__name__}; source authentication remains unresolved."],
                observed=observed,
            ), None


class JanusAuthenticatedAckFinalizer:
    def __init__(self, state_dir: str | Path = "state/activator") -> None:
        self.state_dir = Path(state_dir)
        self.structural_ledger = HashLedger(self.state_dir / "ack_reconciliation_ledger.jsonl", "parent_reconciliation_hash")
        self.provenance_ledger = HashLedger(self.state_dir / "ack_provenance_ledger.jsonl", "parent_provenance_hash")
        self.final_ledger = HashLedger(self.state_dir / "ack_authenticated_finalization_ledger.jsonl", "parent_finalization_hash")

    @staticmethod
    def _finalization_id(structural: Dict[str, Any], provenance: Dict[str, Any]) -> str:
        return "ackf-" + canonical_hash({
            "structural_receipt_hash": structural.get("receipt_hash"),
            "provenance_receipt_hash": provenance.get("receipt_hash"),
        })

    def _seal(
        self,
        structural: Dict[str, Any],
        provenance: Dict[str, Any],
        *,
        terminal: str,
        reasons: list[str],
        source_authenticated: bool = False,
        delivery_confirmed: bool = False,
        ambiguity_resolved: bool = False,
    ) -> Dict[str, Any]:
        receipt = {
            "schema": "janus.activator.ack_authenticated_final_receipt.v0.6",
            "finalization_id": self._finalization_id(structural, provenance),
            "created_at": time.time(),
            "parent_finalization_hash": self.final_ledger.tip_hash(),
            "structural_reconciliation_receipt_hash": str(structural.get("receipt_hash") or canonical_hash(structural)),
            "provenance_receipt_hash": str(provenance.get("receipt_hash") or canonical_hash(provenance)),
            "packet_id": str(structural.get("packet_id") or provenance.get("ack_packet_id") or "UNKNOWN"),
            "packet_hash": str(structural.get("packet_hash") or provenance.get("ack_packet_hash") or canonical_hash({})),
            "ack_hash": str(structural.get("ack_hash") or provenance.get("ack_hash") or canonical_hash({})),
            "ack_accepted": structural.get("ack_accepted") is True,
            "ack_terminal": str(structural.get("ack_terminal") or provenance.get("ack_terminal") or "UNKNOWN"),
            "source_authenticated_under_github_trust_model": bool(source_authenticated),
            "delivery_confirmed_under_github_trust_model": bool(delivery_confirmed),
            "transport_ambiguity_resolved": bool(ambiguity_resolved),
            "target_execution_authorized": False,
            "target_execution_inferred": False,
            "target_execution_observed": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
        }
        sealed = self.final_ledger.append(receipt)
        if not self.final_ledger.verify():
            raise RuntimeError("ACK_AUTHENTICATED_FINALIZATION_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def finalize(self, structural: Dict[str, Any], provenance: Dict[str, Any]) -> Dict[str, Any]:
        structural = structural if isinstance(structural, dict) else {}
        provenance = provenance if isinstance(provenance, dict) else {}

        if not verify_sealed_object(structural, "receipt_hash") or structural.get("schema") != "janus.activator.ack_reconciliation_receipt.v0.5":
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_INVALID_STRUCTURAL_RECEIPT",
                reasons=["v0.5 structural reconciliation receipt failed integrity or schema verification."],
            )
        if not self.structural_ledger.contains_exact(structural):
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_STRUCTURAL_RECEIPT_NOT_LOCAL",
                reasons=["Structural reconciliation receipt is not an exact row in the local HOME ACK reconciliation ledger."],
            )
        if not verify_sealed_object(provenance, "receipt_hash") or provenance.get("schema") != "janus.activator.ack_provenance_receipt.v0.6":
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_INVALID_PROVENANCE_RECEIPT",
                reasons=["v0.6 provenance receipt failed integrity or schema verification."],
            )
        if not self.provenance_ledger.contains_exact(provenance):
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_PROVENANCE_RECEIPT_NOT_LOCAL",
                reasons=["Provenance receipt is not an exact row in the local HOME ACK provenance ledger."],
            )
        if provenance.get("terminal") != "ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL" or provenance.get("source_authenticated") is not True:
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_SOURCE_UNAUTHENTICATED",
                reasons=["Provenance receipt did not authenticate ACK source under the admitted GitHub Actions trust model."],
            )

        structural_terminal = str(structural.get("terminal") or "")
        if structural_terminal not in {
            "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
            "ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
        }:
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_INCONSISTENT_ACK_STATE",
                reasons=["Structural receipt is not a source-unverified accepted/rejected terminal eligible for provenance finalization."],
            )

        if (
            structural.get("ack_hash") != provenance.get("ack_hash")
            or structural.get("packet_id") != provenance.get("ack_packet_id")
            or structural.get("packet_hash") != provenance.get("ack_packet_hash")
            or structural.get("ack_accepted") != provenance.get("ack_accepted")
            or structural.get("ack_terminal") != provenance.get("ack_terminal")
        ):
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_LINEAGE_MISMATCH",
                reasons=["Authenticated artifact ACK does not match the exact v0.5 structural ACK lineage."],
            )

        finalization_id = self._finalization_id(structural, provenance)
        if any(
            row.get("finalization_id") == finalization_id
            and row.get("terminal") in {
                "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION",
                "ACK_AUTHENTICATED_REJECTION_CONFIRMED_NO_EXECUTION",
            }
            for row in self.final_ledger.read()
        ):
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_ALREADY_RECORDED",
                reasons=["This exact structural/provenance tuple was already finalized; no second delivery transition occurred."],
                source_authenticated=True,
                delivery_confirmed=True,
                ambiguity_resolved=structural.get("transport_terminal_before") == "TRANSPORT_OUTCOME_UNDETERMINED",
            )

        accepted = structural.get("ack_accepted") is True
        ack_terminal = str(structural.get("ack_terminal") or "")
        ambiguity_resolved = structural.get("transport_terminal_before") == "TRANSPORT_OUTCOME_UNDETERMINED"
        if accepted and ack_terminal == "ACK_ACCEPTED_NO_EXECUTION" and structural_terminal == "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION":
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION",
                reasons=[
                    "The exact ACK previously bound to local HOME lineage is authenticated as an artifact of the pinned Janus-Demiurge receiver workflow under the GitHub Actions trust model.",
                    "Delivery to the receiver is confirmed under that trust model; target execution is neither authorized nor inferred.",
                    "Authenticated delivery does not grant scientific-evidence, claim, command, physical-runtime, or external-effect authority.",
                ] + (["The prior transport delivery ambiguity is resolved by the authenticated receiver ACK without replaying the packet."] if ambiguity_resolved else []),
                source_authenticated=True,
                delivery_confirmed=True,
                ambiguity_resolved=ambiguity_resolved,
            )
        if (not accepted) and ack_terminal.startswith("ACK_REJECTED_") and structural_terminal == "ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION":
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_REJECTION_CONFIRMED_NO_EXECUTION",
                reasons=[
                    "The exact rejection ACK previously bound to local HOME lineage is authenticated under the GitHub Actions trust model.",
                    "Receiver delivery and rejection are confirmed under that trust model; no target execution is authorized or inferred.",
                    "The rejection remains append-only evidence about the receiver transaction and is not permission to replay or erase history.",
                ] + (["The prior transport delivery ambiguity is resolved by the authenticated receiver rejection without replaying the packet."] if ambiguity_resolved else []),
                source_authenticated=True,
                delivery_confirmed=True,
                ambiguity_resolved=ambiguity_resolved,
            )
        return self._seal(
            structural,
            provenance,
            terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_INCONSISTENT_ACK_STATE",
            reasons=["Accepted/rejected ACK state is inconsistent across structural and provenance receipts."],
        )


__all__ = [
    "GitHubAPIReader",
    "GitHubAckProvenanceVerifier",
    "JanusAuthenticatedAckFinalizer",
    "HashLedger",
]
