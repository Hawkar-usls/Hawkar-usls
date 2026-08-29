from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .ack import AckReconciliationLedger, verify_sealed_object, verify_transport_receipt
from .ack_provenance import HashLedger
from .activator import canonical_hash
from .dispatch import DispatchLedger, verify_dispatch_packet
from .transport import TransportLedger

TARGET_ORGAN = "Hawkar-usls/Janus-Demiurge"
OPERATION = "READ_ONLY_ORIENTATION_SNAPSHOT"
RISK_CLASS = "R0_INTERNAL_READ_ONLY_ORIENTATION"
EXECUTION_SCOPE = "TARGET_REPOSITORY_LOCAL_READ_ONLY_METADATA"
ELIGIBLE_FINAL_TERMINAL = "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION"
ELIGIBLE_STRUCTURAL_TERMINAL = "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION"
ELIGIBLE_PROVENANCE_TERMINAL = "ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL"
AUTHORIZED_DISPATCH_TERMINALS = {"AUTHORIZED_INTERNAL_HANDOFF", "ALREADY_EMITTED"}
RECONCILABLE_TRANSPORT_TERMINALS = {"TRANSPORT_SENT_AWAITING_ACK", "TRANSPORT_OUTCOME_UNDETERMINED"}


class ExecutionGrantLedger:
    """Append-only hash-chained issuance-decision ledger.

    A successful grant is immutable and deterministic by parent authenticated
    delivery + packet + target + operation. Re-issuing the same eligible grant
    returns the exact existing row rather than creating a second grant.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
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
                raise ValueError("EXECUTION_GRANT_LEDGER_ROW_NOT_OBJECT")
            rows.append(row)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["grant_hash"]) if rows else None

    def append(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(decision)
        body.pop("grant_hash", None)
        body["grant_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return body

    def verify(self) -> bool:
        previous: Optional[str] = None
        for row in self.read():
            if row.get("parent_grant_hash") != previous:
                return False
            claimed = str(row.get("grant_hash") or "")
            body = dict(row)
            body.pop("grant_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True

    def issued(self, grant_id: str) -> Optional[Dict[str, Any]]:
        for row in self.read():
            if (
                row.get("grant_id") == grant_id
                and row.get("terminal") == "EXECUTION_GRANT_ISSUED_READ_ONLY_ORIENTATION"
                and row.get("target_execution_authorized") is True
            ):
                return row
        return None


def _exact_row_by_hash(rows: list[Dict[str, Any]], value: str, hash_field: str) -> Optional[Dict[str, Any]]:
    matches = [row for row in rows if isinstance(row, dict) and row.get(hash_field) == value]
    return matches[0] if len(matches) == 1 else None


def verify_execution_grant(grant: Dict[str, Any]) -> bool:
    if not isinstance(grant, dict):
        return False
    claimed = str(grant.get("grant_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(grant)
    body.pop("grant_hash", None)
    if canonical_hash(body) != claimed:
        return False
    if (
        grant.get("schema") != "janus.activator.execution_grant.v0.7"
        or grant.get("terminal") != "EXECUTION_GRANT_ISSUED_READ_ONLY_ORIENTATION"
        or grant.get("target_organ") != TARGET_ORGAN
        or grant.get("operation") != OPERATION
        or grant.get("risk_class") != RISK_CLASS
        or grant.get("execution_scope") != EXECUTION_SCOPE
        or grant.get("target_execution_authorized") is not True
        or grant.get("repository_write_authorized") is not False
        or grant.get("network_access_authorized") is not False
        or grant.get("model_access_authorized") is not False
        or grant.get("command_authority_granted") is not False
        or grant.get("claim_authority_granted") is not False
        or grant.get("scientific_evidence_authority_granted") is not False
        or grant.get("external_effect_authorized") is not False
        or grant.get("physical_runtime_effect_authorized") is not False
    ):
        return False
    expected_id = "xg-" + canonical_hash({
        "authenticated_final_receipt_hash": grant.get("authenticated_final_receipt_hash"),
        "packet_id": grant.get("packet_id"),
        "packet_hash": grant.get("packet_hash"),
        "target_organ": grant.get("target_organ"),
        "operation": grant.get("operation"),
    })
    return grant.get("grant_id") == expected_id


class JanusExecutionGrantIssuer:
    """Issue the first explicit bounded target-execution authority.

    The issuer does not trust a final receipt merely because it self-hashes or
    appears in the final ledger. It re-walks the local authenticated delivery
    ancestry down through provenance, structural reconciliation, transport,
    dispatch ledger and exact dispatch outbox bytes before issuing a grant.
    """

    def __init__(self, state_dir: str | Path = "state/activator") -> None:
        self.state_dir = Path(state_dir)
        self.dispatch_ledger = DispatchLedger(self.state_dir / "dispatch_ledger.jsonl")
        self.transport_ledger = TransportLedger(self.state_dir / "transport_ledger.jsonl")
        self.structural_ledger = AckReconciliationLedger(self.state_dir / "ack_reconciliation_ledger.jsonl")
        self.provenance_ledger = HashLedger(self.state_dir / "ack_provenance_ledger.jsonl", "parent_provenance_hash")
        self.final_ledger = HashLedger(self.state_dir / "ack_authenticated_finalization_ledger.jsonl", "parent_finalization_hash")
        self.grant_ledger = ExecutionGrantLedger(self.state_dir / "execution_grant_ledger.jsonl")

    @staticmethod
    def _grant_id(final_receipt: Dict[str, Any], packet_id: str, packet_hash: str) -> str:
        final_hash = str(final_receipt.get("receipt_hash") or canonical_hash(final_receipt))
        return "xg-" + canonical_hash({
            "authenticated_final_receipt_hash": final_hash,
            "packet_id": packet_id,
            "packet_hash": packet_hash,
            "target_organ": TARGET_ORGAN,
            "operation": OPERATION,
        })

    def _seal(
        self,
        final_receipt: Dict[str, Any],
        *,
        packet_id: str,
        packet_hash: str,
        terminal: str,
        reasons: list[str],
        authorized: bool,
    ) -> Dict[str, Any]:
        final_hash = str(final_receipt.get("receipt_hash") or canonical_hash(final_receipt))
        if len(final_hash) != 64:
            final_hash = canonical_hash(final_receipt)
        decision = {
            "schema": "janus.activator.execution_grant.v0.7",
            "grant_id": self._grant_id(final_receipt, packet_id, packet_hash),
            "created_at": time.time(),
            "parent_grant_hash": self.grant_ledger.tip_hash(),
            "authenticated_final_receipt_hash": final_hash,
            "finalization_id": str(final_receipt.get("finalization_id") or "ackf-" + "0" * 64),
            "packet_id": packet_id if packet_id else "dsp-" + "0" * 64,
            "packet_hash": packet_hash if len(packet_hash) == 64 else canonical_hash({}),
            "target_organ": TARGET_ORGAN,
            "operation": OPERATION,
            "risk_class": RISK_CLASS,
            "execution_scope": EXECUTION_SCOPE,
            "target_execution_authorized": bool(authorized),
            "repository_write_authorized": False,
            "network_access_authorized": False,
            "model_access_authorized": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
        }
        sealed = self.grant_ledger.append(decision)
        if not self.grant_ledger.verify():
            raise RuntimeError("EXECUTION_GRANT_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def _validate_full_lineage(self, final_receipt: Dict[str, Any]) -> Tuple[bool, str, list[str], Optional[Dict[str, Any]]]:
        if not isinstance(final_receipt, dict) or not verify_sealed_object(final_receipt, "receipt_hash"):
            return False, "EXECUTION_GRANT_BLOCKED_INVALID_FINAL_RECEIPT", [
                "Authenticated final receipt failed self-integrity verification."
            ], None
        if final_receipt.get("schema") != "janus.activator.ack_authenticated_final_receipt.v0.6":
            return False, "EXECUTION_GRANT_BLOCKED_INVALID_FINAL_RECEIPT", [
                "Parent object is not the admitted v0.6 authenticated final receipt schema."
            ], None

        try:
            ledgers_valid = all([
                self.dispatch_ledger.verify(),
                self.transport_ledger.verify(),
                self.structural_ledger.verify(),
                self.provenance_ledger.verify(),
                self.final_ledger.verify(),
                self.grant_ledger.verify(),
            ])
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            ledgers_valid = False
        if not ledgers_valid:
            return False, "EXECUTION_GRANT_BLOCKED_LOCAL_LINEAGE_INVALID", [
                "At least one required HOME local parent/hash chain is invalid or unreadable."
            ], None

        final_hash = str(final_receipt.get("receipt_hash") or "")
        final_local = _exact_row_by_hash(self.final_ledger.read(), final_hash, "receipt_hash")
        if final_local != final_receipt:
            return False, "EXECUTION_GRANT_BLOCKED_FINAL_RECEIPT_NOT_LOCAL", [
                "Authenticated final receipt is not the exact unique row in the HOME finalization ledger."
            ], None

        if (
            final_receipt.get("terminal") != ELIGIBLE_FINAL_TERMINAL
            or final_receipt.get("source_authenticated_under_github_trust_model") is not True
            or final_receipt.get("delivery_confirmed_under_github_trust_model") is not True
            or final_receipt.get("ack_accepted") is not True
            or final_receipt.get("ack_terminal") != "ACK_ACCEPTED_NO_EXECUTION"
            or final_receipt.get("target_execution_authorized") is not False
            or final_receipt.get("target_execution_inferred") is not False
            or final_receipt.get("target_execution_observed") is not False
            or final_receipt.get("claim_authority_granted") is not False
            or final_receipt.get("external_effect_authorized") is not False
        ):
            return False, "EXECUTION_GRANT_BLOCKED_PARENT_NOT_ELIGIBLE", [
                "Only an authenticated accepted delivery finalization with no prior execution/effect authority may enter P12."
            ], None

        structural_hash = str(final_receipt.get("structural_reconciliation_receipt_hash") or "")
        provenance_hash = str(final_receipt.get("provenance_receipt_hash") or "")
        structural = _exact_row_by_hash(self.structural_ledger.read(), structural_hash, "receipt_hash")
        provenance = _exact_row_by_hash(self.provenance_ledger.read(), provenance_hash, "receipt_hash")
        if structural is None or provenance is None:
            return False, "EXECUTION_GRANT_BLOCKED_PARENT_LINEAGE_MISSING", [
                "Final receipt does not bind to exact unique local structural and provenance parent rows."
            ], None
        if not verify_sealed_object(structural, "receipt_hash") or not verify_sealed_object(provenance, "receipt_hash"):
            return False, "EXECUTION_GRANT_BLOCKED_PARENT_LINEAGE_INVALID", [
                "Structural or provenance parent failed self-integrity verification."
            ], None
        if (
            structural.get("schema") != "janus.activator.ack_reconciliation_receipt.v0.5"
            or structural.get("terminal") != ELIGIBLE_STRUCTURAL_TERMINAL
            or structural.get("ack_accepted") is not True
            or structural.get("packet_local_outbox_bound") is not True
            or structural.get("transport_local_ledger_bound") is not True
            or structural.get("ack_integrity_valid") is not True
            or structural.get("execution_authorized") is not False
            or structural.get("execution_performed") is not False
            or structural.get("claim_authority_granted") is not False
            or structural.get("external_effect_authorized") is not False
        ):
            return False, "EXECUTION_GRANT_BLOCKED_PARENT_LINEAGE_INVALID", [
                "Structural reconciliation parent is not the admitted accepted/no-execution state."
            ], None
        if (
            provenance.get("schema") != "janus.activator.ack_provenance_receipt.v0.6"
            or provenance.get("terminal") != ELIGIBLE_PROVENANCE_TERMINAL
            or provenance.get("source_authenticated") is not True
            or provenance.get("ack_accepted") is not True
            or provenance.get("ack_terminal") != "ACK_ACCEPTED_NO_EXECUTION"
            or provenance.get("target_execution_authorized") is not False
            or provenance.get("target_execution_inferred") is not False
            or provenance.get("claim_authority_granted") is not False
            or provenance.get("external_effect_authorized") is not False
        ):
            return False, "EXECUTION_GRANT_BLOCKED_PARENT_LINEAGE_INVALID", [
                "ACK provenance parent is not the admitted authenticated accepted/no-execution state."
            ], None

        packet_id = str(final_receipt.get("packet_id") or "")
        packet_hash = str(final_receipt.get("packet_hash") or "")
        ack_hash = str(final_receipt.get("ack_hash") or "")
        if (
            structural.get("packet_id") != packet_id
            or structural.get("packet_hash") != packet_hash
            or provenance.get("ack_packet_id") != packet_id
            or provenance.get("ack_packet_hash") != packet_hash
            or structural.get("ack_hash") != ack_hash
            or provenance.get("ack_hash") != ack_hash
        ):
            return False, "EXECUTION_GRANT_BLOCKED_PARENT_LINEAGE_MISMATCH", [
                "Final, structural and provenance packet/ACK bindings disagree."
            ], None

        packet_path = self.state_dir / "dispatch_outbox" / f"{packet_id}.json"
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "EXECUTION_GRANT_BLOCKED_DISPATCH_LINEAGE_INVALID", [
                "Exact HOME dispatch outbox packet is missing or unreadable."
            ], None
        if (
            not isinstance(packet, dict)
            or not verify_dispatch_packet(packet)
            or packet.get("packet_id") != packet_id
            or packet.get("packet_hash") != packet_hash
            or packet.get("target_organ") != TARGET_ORGAN
            or packet.get("external_effect_authorized") is not False
            or packet.get("claim_authority_granted") is not False
            or packet.get("command_authority_granted") is not False
        ):
            return False, "EXECUTION_GRANT_BLOCKED_DISPATCH_LINEAGE_INVALID", [
                "HOME dispatch outbox bytes fail packet integrity, target, identity or authority-ceiling checks."
            ], None

        dispatch_rows = self.dispatch_ledger.read()
        dispatch_matches = [
            row for row in dispatch_rows
            if isinstance(row, dict)
            and row.get("dispatch_id") == packet_id
            and row.get("packet_hash") == packet_hash
            and row.get("packet_path") == str(packet_path)
            and row.get("target_organ") == TARGET_ORGAN
            and row.get("operation") == packet.get("operation")
            and row.get("dispatch_authorized") is True
            and row.get("external_effect_authorized") is False
            and row.get("terminal") in AUTHORIZED_DISPATCH_TERMINALS
        ]
        if len(dispatch_matches) < 1:
            return False, "EXECUTION_GRANT_BLOCKED_DISPATCH_LINEAGE_INVALID", [
                "Dispatch packet is not bound to an authorized row in the intact HOME dispatch ledger."
            ], None

        transport_hash = str(structural.get("transport_receipt_hash") or "")
        transport = _exact_row_by_hash(self.transport_ledger.read(), transport_hash, "receipt_hash")
        if (
            transport is None
            or not verify_transport_receipt(transport)
            or transport.get("packet_id") != packet_id
            or transport.get("packet_hash") != packet_hash
            or transport.get("target_organ") != TARGET_ORGAN
            or transport.get("terminal") not in RECONCILABLE_TRANSPORT_TERMINALS
            or transport.get("network_boundary_entered") is not True
            or transport.get("target_execution_authorized") is not False
        ):
            return False, "EXECUTION_GRANT_BLOCKED_TRANSPORT_LINEAGE_INVALID", [
                "Structural receipt is not bound to the exact reconciliable transport row in the intact HOME transport ledger."
            ], None

        return True, "EXECUTION_GRANT_ISSUED_READ_ONLY_ORIENTATION", [
            "Authenticated delivery finalization is an exact row in an intact HOME finalization chain.",
            "Structural and provenance parents are exact, intact, mutually bound and preserve the no-execution authority ceiling.",
            "Dispatch packet bytes are exact HOME outbox bytes and bind to an authorized row in the intact dispatch ledger.",
            "Transport receipt is the exact reconciliable network-boundary row in the intact transport ledger.",
            "P12 grants only a local read-only orientation snapshot; repository writes, network/model access, claims and external effects remain forbidden."
        ], packet

    def issue(self, final_receipt: Dict[str, Any]) -> Dict[str, Any]:
        final_receipt = final_receipt if isinstance(final_receipt, dict) else {}
        packet_id = str(final_receipt.get("packet_id") or "")
        packet_hash = str(final_receipt.get("packet_hash") or "")
        grant_id = self._grant_id(final_receipt, packet_id, packet_hash)

        try:
            existing = self.grant_ledger.issued(grant_id)
        except (OSError, ValueError, json.JSONDecodeError):
            existing = None
        if existing is not None:
            return existing

        ok, terminal, reasons, packet = self._validate_full_lineage(final_receipt)
        if packet is not None:
            packet_id = str(packet.get("packet_id") or packet_id)
            packet_hash = str(packet.get("packet_hash") or packet_hash)
        return self._seal(
            final_receipt,
            packet_id=packet_id,
            packet_hash=packet_hash,
            terminal=terminal,
            reasons=reasons,
            authorized=ok,
        )


__all__ = [
    "ExecutionGrantLedger",
    "JanusExecutionGrantIssuer",
    "verify_execution_grant",
]
