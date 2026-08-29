from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .activator import canonical_hash
from .dispatch import verify_dispatch_packet

ACK_SCHEMA = "janus.demiurge.activator_dispatch_ack.v0.1"
RECONCILABLE_TRANSPORT_TERMINALS = {
    "TRANSPORT_SENT_AWAITING_ACK",
    "TRANSPORT_OUTCOME_UNDETERMINED",
}
STRUCTURALLY_BOUND_TERMINALS = {
    "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
    "ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
}


class AckReconciliationLedger:
    """Append-only hash-chained ledger for offline ACK structural binding attempts."""

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
                raise ValueError("ACK_RECONCILIATION_LEDGER_ROW_NOT_OBJECT")
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
            if row.get("parent_reconciliation_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True

    def previously_structurally_bound(self, reconciliation_id: str) -> bool:
        for row in self.read():
            if row.get("reconciliation_id") != reconciliation_id:
                continue
            if row.get("terminal") in STRUCTURALLY_BOUND_TERMINALS:
                return True
        return False


def verify_sealed_object(value: Dict[str, Any], hash_field: str) -> bool:
    if not isinstance(value, dict):
        return False
    claimed = str(value.get(hash_field) or "")
    if len(claimed) != 64:
        return False
    body = dict(value)
    body.pop(hash_field, None)
    return canonical_hash(body) == claimed


def verify_transport_receipt(receipt: Dict[str, Any]) -> bool:
    if not verify_sealed_object(receipt, "receipt_hash"):
        return False
    return (
        receipt.get("schema") == "janus.activator.transport_receipt.v0.4"
        and receipt.get("endpoint_class") == "GITHUB_REPOSITORY_DISPATCH"
        and receipt.get("credential_source") == "ENV:JANUS_DEMIURGE_DISPATCH_TOKEN"
        and receipt.get("credential_value_persisted") is False
        and receipt.get("external_effect_authorized") is False
        and receipt.get("target_execution_authorized") is False
    )


def verify_receiver_ack(ack: Dict[str, Any]) -> bool:
    """Verify ACK self-integrity and schema only; this does NOT authenticate its source."""
    if not verify_sealed_object(ack, "ack_hash"):
        return False
    return ack.get("schema") == ACK_SCHEMA


class JanusAckReconciler:
    """Offline fail-closed structural binding of an ACK to exact HOME lineage.

    HOME-origin packet and transport objects are first required to be members of
    the local dispatch outbox and transport ledger. The receiver ACK currently
    carries a canonical self-hash, not a source signature. Therefore v0.5 may
    prove ACK internal integrity and exact matching to authenticated local HOME
    lineage, but it may not claim that Janus-Demiurge actually emitted the ACK.
    Source authenticity and delivery confirmation remain open until a separate
    GitHub Actions artifact provenance gate verifies origin.
    """

    def __init__(self, state_dir: str | Path = "state/activator") -> None:
        self.state_dir = Path(state_dir)
        self.ledger = AckReconciliationLedger(self.state_dir / "ack_reconciliation_ledger.jsonl")

    @staticmethod
    def _safe_hash(value: Dict[str, Any], field: str) -> str:
        claimed = str(value.get(field) or "") if isinstance(value, dict) else ""
        return claimed if len(claimed) == 64 else canonical_hash(value if isinstance(value, dict) else {})

    @classmethod
    def _reconciliation_id(cls, packet: Dict[str, Any], transport: Dict[str, Any], ack: Dict[str, Any]) -> str:
        return "ackr-" + canonical_hash({
            "packet_hash": cls._safe_hash(packet, "packet_hash"),
            "transport_receipt_hash": cls._safe_hash(transport, "receipt_hash"),
            "ack_hash": cls._safe_hash(ack, "ack_hash"),
        })

    def _packet_is_local_outbox_member(self, packet: Dict[str, Any]) -> bool:
        packet_id = str(packet.get("packet_id") or "")
        if not packet_id:
            return False
        path = self.state_dir / "dispatch_outbox" / f"{packet_id}.json"
        if not path.is_file():
            return False
        try:
            local = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(local, dict) or not verify_dispatch_packet(local):
            return False
        return local == packet

    def _transport_is_local_ledger_member(self, receipt: Dict[str, Any]) -> bool:
        path = self.state_dir / "transport_ledger.jsonl"
        if not path.is_file():
            return False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                return False
            if not isinstance(row, dict):
                return False
            if row.get("receipt_hash") == receipt.get("receipt_hash"):
                return row == receipt
        return False

    def _seal(
        self,
        packet: Dict[str, Any],
        transport: Dict[str, Any],
        ack: Dict[str, Any],
        *,
        terminal: str,
        reasons: list[str],
        packet_local_outbox_bound: bool,
        transport_local_ledger_bound: bool,
        ack_integrity_valid: bool,
    ) -> Dict[str, Any]:
        receipt = {
            "schema": "janus.activator.ack_reconciliation_receipt.v0.5",
            "reconciliation_id": self._reconciliation_id(packet, transport, ack),
            "created_at": time.time(),
            "parent_reconciliation_hash": self.ledger.tip_hash(),
            "packet_id": str(packet.get("packet_id") or ack.get("packet_id") or "UNKNOWN"),
            "packet_hash": self._safe_hash(packet, "packet_hash"),
            "transport_receipt_hash": self._safe_hash(transport, "receipt_hash"),
            "ack_hash": self._safe_hash(ack, "ack_hash"),
            "transport_terminal_before": str(transport.get("terminal") or "UNKNOWN"),
            "ack_terminal": str(ack.get("terminal") or "UNKNOWN"),
            "ack_accepted": ack.get("accepted") is True,
            "packet_local_outbox_bound": bool(packet_local_outbox_bound),
            "transport_local_ledger_bound": bool(transport_local_ledger_bound),
            "ack_integrity_valid": bool(ack_integrity_valid),
            "ack_source_authenticity": "UNVERIFIED_OFFLINE",
            "ack_source_authenticated": False,
            "delivery_confirmed": False,
            "transport_ambiguity_resolved": False,
            "execution_authorized": False,
            "execution_performed": False,
            "claim_authority_granted": False,
            "external_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("ACK_RECONCILIATION_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def reconcile(
        self,
        packet: Dict[str, Any],
        transport_receipt: Dict[str, Any],
        ack: Dict[str, Any],
    ) -> Dict[str, Any]:
        packet = packet if isinstance(packet, dict) else {}
        transport_receipt = transport_receipt if isinstance(transport_receipt, dict) else {}
        ack = ack if isinstance(ack, dict) else {}
        ack_integrity = verify_receiver_ack(ack)

        if not verify_dispatch_packet(packet):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_INVALID_PACKET",
                reasons=["Dispatch packet integrity or deterministic packet identity failed."],
                packet_local_outbox_bound=False,
                transport_local_ledger_bound=False,
                ack_integrity_valid=ack_integrity,
            )

        packet_local = self._packet_is_local_outbox_member(packet)
        if not packet_local:
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_PACKET_NOT_IN_LOCAL_OUTBOX",
                reasons=["Self-consistent dispatch packet is not the exact packet stored in the HOME dispatch outbox."],
                packet_local_outbox_bound=False,
                transport_local_ledger_bound=False,
                ack_integrity_valid=ack_integrity,
            )

        if not verify_transport_receipt(transport_receipt):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_INVALID_TRANSPORT_RECEIPT",
                reasons=["Transport receipt integrity, schema, transport class, credential provenance, or authority ceiling failed verification."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=False,
                ack_integrity_valid=ack_integrity,
            )

        transport_local = self._transport_is_local_ledger_member(transport_receipt)
        if not transport_local:
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_TRANSPORT_NOT_IN_LOCAL_LEDGER",
                reasons=["Self-consistent transport receipt is not an exact row in the HOME transport ledger."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=False,
                ack_integrity_valid=ack_integrity,
            )

        if transport_receipt.get("terminal") not in RECONCILABLE_TRANSPORT_TERMINALS:
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_TRANSPORT_NOT_RECONCILABLE",
                reasons=["Only transport states that crossed the network boundary are structurally ACK-reconcilable."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=ack_integrity,
            )

        if (
            transport_receipt.get("packet_id") != packet.get("packet_id")
            or transport_receipt.get("packet_hash") != packet.get("packet_hash")
            or transport_receipt.get("target_organ") != packet.get("target_organ")
        ):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_PACKET_MISMATCH",
                reasons=["Transport receipt does not bind to the supplied HOME dispatch packet id, hash, and target."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=ack_integrity,
            )

        if not ack_integrity:
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_INVALID_ACK",
                reasons=["Receiver ACK self-hash or schema failed verification."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=False,
            )

        if ack.get("packet_id") != packet.get("packet_id") or ack.get("packet_hash") != packet.get("packet_hash"):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_PACKET_MISMATCH",
                reasons=["ACK does not bind to the exact HOME dispatch packet id and hash."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=True,
            )

        if (
            ack.get("execution_authorized") is not False
            or ack.get("execution_performed") is not False
            or ack.get("claim_authority_granted") is not False
            or ack.get("external_effect_authorized") is not False
        ):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_RECONCILIATION_BLOCKED_AUTHORITY_ESCALATION",
                reasons=["ACK attempted to escalate execution, claim, or external-effect authority."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=True,
            )

        reconciliation_id = self._reconciliation_id(packet, transport_receipt, ack)
        if self.ledger.previously_structurally_bound(reconciliation_id):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_ALREADY_STRUCTURALLY_RECONCILED",
                reasons=["This exact packet/transport/ACK tuple was already structurally bound; no second state transition occurred."],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=True,
            )

        accepted = ack.get("accepted")
        ack_terminal = str(ack.get("terminal") or "")
        if accepted is True and ack_terminal == "ACK_ACCEPTED_NO_EXECUTION":
            reasons = [
                "ACK self-integrity verified and its packet id/hash structurally match exact HOME dispatch and transport lineage.",
                "ACK source authenticity remains UNVERIFIED_OFFLINE because a self-hash does not prove which system emitted the object.",
                "Delivery, target execution, evidence authority, claim authority, and external-effect authority are not inferred.",
            ]
            if transport_receipt.get("terminal") == "TRANSPORT_OUTCOME_UNDETERMINED":
                reasons.append("The candidate ACK is consistent with a resolution of transport ambiguity, but the ambiguity remains unresolved until ACK source provenance is independently verified.")
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
                reasons=reasons,
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=True,
            )

        if accepted is False and ack_terminal.startswith("ACK_REJECTED_"):
            return self._seal(
                packet,
                transport_receipt,
                ack,
                terminal="ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
                reasons=[
                    "ACK rejection self-integrity and packet binding are structurally valid and preserved in lineage.",
                    "ACK source authenticity remains UNVERIFIED_OFFLINE; rejection is not promoted to authenticated receiver evidence.",
                    "The candidate rejection does not authorize replay, execution, evidence promotion, or history deletion by itself.",
                ],
                packet_local_outbox_bound=True,
                transport_local_ledger_bound=True,
                ack_integrity_valid=True,
            )

        return self._seal(
            packet,
            transport_receipt,
            ack,
            terminal="ACK_RECONCILIATION_BLOCKED_INCONSISTENT_ACK_STATE",
            reasons=["ACK accepted flag and receiver terminal are internally inconsistent."],
            packet_local_outbox_bound=True,
            transport_local_ledger_bound=True,
            ack_integrity_valid=True,
        )


__all__ = [
    "ACK_SCHEMA",
    "AckReconciliationLedger",
    "JanusAckReconciler",
    "verify_receiver_ack",
    "verify_transport_receipt",
]
