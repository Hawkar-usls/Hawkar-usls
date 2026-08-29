from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .ack import JanusAckReconciler as LegacyJanusAckReconciler
from .ack_provenance import JanusAuthenticatedAckFinalizer as LegacyJanusAuthenticatedAckFinalizer
from .dispatch import DispatchLedger, verify_dispatch_packet
from .transport import TransportLedger


AUTHORIZED_DISPATCH_TERMINALS = {"AUTHORIZED_INTERNAL_HANDOFF", "ALREADY_EMITTED"}


class HardenedJanusAckReconciler(LegacyJanusAckReconciler):
    """Governed v0.6.1 reconciler that authenticates full HOME local lineage.

    The v0.5 reconciler established exact outbox/ledger membership. v0.6.1 adds
    the missing parent-chain requirement and binds dispatch packet bytes back to
    an authorized receipt in the hash-chained dispatch ledger.
    """

    def _packet_is_local_outbox_member(self, packet: Dict[str, Any]) -> bool:
        if not super()._packet_is_local_outbox_member(packet):
            return False
        packet_id = str(packet.get("packet_id") or "")
        packet_hash = str(packet.get("packet_hash") or "")
        expected_path = str(self.state_dir / "dispatch_outbox" / f"{packet_id}.json")
        ledger = DispatchLedger(self.state_dir / "dispatch_ledger.jsonl")
        try:
            if not ledger.verify():
                return False
            rows = ledger.read()
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (
                row.get("dispatch_id") == packet_id
                and row.get("packet_hash") == packet_hash
                and row.get("packet_path") == expected_path
                and row.get("target_organ") == packet.get("target_organ")
                and row.get("operation") == packet.get("operation")
                and row.get("dispatch_authorized") is True
                and row.get("external_effect_authorized") is False
                and row.get("terminal") in AUTHORIZED_DISPATCH_TERMINALS
            ):
                return True
        return False

    def _transport_is_local_ledger_member(self, receipt: Dict[str, Any]) -> bool:
        ledger = TransportLedger(self.state_dir / "transport_ledger.jsonl")
        try:
            if not ledger.verify():
                return False
            rows = ledger.read()
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        claimed = receipt.get("receipt_hash") if isinstance(receipt, dict) else None
        return any(row.get("receipt_hash") == claimed and row == receipt for row in rows)


class HardenedJanusAuthenticatedAckFinalizer(LegacyJanusAuthenticatedAckFinalizer):
    """Governed v0.6.1 finalizer requiring intact structural/provenance chains."""

    def finalize(self, structural: Dict[str, Any], provenance: Dict[str, Any]) -> Dict[str, Any]:
        structural = structural if isinstance(structural, dict) else {}
        provenance = provenance if isinstance(provenance, dict) else {}
        try:
            structural_chain_valid = self.structural_ledger.verify()
        except (OSError, ValueError, json.JSONDecodeError):
            structural_chain_valid = False
        if not structural_chain_valid:
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_STRUCTURAL_RECEIPT_NOT_LOCAL",
                reasons=[
                    "HOME ACK reconciliation ledger parent/hash chain is invalid; exact row membership cannot establish trusted lineage."
                ],
            )
        try:
            provenance_chain_valid = self.provenance_ledger.verify()
        except (OSError, ValueError, json.JSONDecodeError):
            provenance_chain_valid = False
        if not provenance_chain_valid:
            return self._seal(
                structural,
                provenance,
                terminal="ACK_AUTHENTICATED_FINALIZATION_BLOCKED_PROVENANCE_RECEIPT_NOT_LOCAL",
                reasons=[
                    "HOME ACK provenance ledger parent/hash chain is invalid; exact row membership cannot establish trusted lineage."
                ],
            )
        return super().finalize(structural, provenance)


__all__ = [
    "HardenedJanusAckReconciler",
    "HardenedJanusAuthenticatedAckFinalizer",
]
