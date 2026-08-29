from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .activator import canonical_hash


READ_ONLY_OPERATION = "WAKE_ORGAN_READ_ONLY"
READ_ONLY_RISK_CLASS = "R0_INTERNAL_READ_ONLY_ORGAN_WAKE"
READ_ONLY_EFFECT_SCOPE = "GITHUB_INTERNAL_READ_ONLY_ANALYSIS"
FORBIDDEN_AUTO_TARGETS = {"Hawkar-usls/-Terminal-for-Janus"}


class DispatchLedger:
    """Append-only hash-chained dispatch-attempt ledger.

    A repeated attempt may point to an already-emitted deterministic packet, but
    it is still recorded as a new receipt. This preserves retries without
    replaying the downstream operation.
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
                raise ValueError("DISPATCH_LEDGER_ROW_NOT_OBJECT")
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
            if row.get("parent_dispatch_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True


def verify_sealed_receipt(receipt: Dict[str, Any]) -> bool:
    if not isinstance(receipt, dict):
        return False
    claimed = str(receipt.get("receipt_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(receipt)
    body.pop("receipt_hash", None)
    return canonical_hash(body) == claimed


def verify_dispatch_packet(packet: Dict[str, Any]) -> bool:
    if not isinstance(packet, dict):
        return False
    claimed = str(packet.get("packet_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(packet)
    body.pop("packet_hash", None)
    if canonical_hash(body) != claimed:
        return False
    expected_id = "dsp-" + canonical_hash({
        "activation_receipt_hash": packet.get("activation_receipt_hash"),
        "target_organ": packet.get("target_organ"),
        "operation": packet.get("operation"),
    })
    return packet.get("packet_id") == expected_id


class JanusDispatchBroker:
    """Fail-closed broker for low-risk internal organ wake packets.

    v0.3 does not perform cross-repository transport or target execution. It
    authorizes and emits deterministic handoff packets into a local outbox only
    after verifying the parent activation receipt and selected route.
    """

    def __init__(self, state_dir: str | Path = "state/activator") -> None:
        self.state_dir = Path(state_dir)
        self.outbox_dir = self.state_dir / "dispatch_outbox"
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = DispatchLedger(self.state_dir / "dispatch_ledger.jsonl")

    @staticmethod
    def _route_for_target(receipt: Dict[str, Any], target_organ: str) -> Optional[Dict[str, Any]]:
        routes = receipt.get("routes_selected")
        if not isinstance(routes, list):
            return None
        for route in routes:
            if not isinstance(route, dict):
                continue
            organs = route.get("organs")
            if isinstance(organs, list) and target_organ in organs:
                return route
        return None

    @staticmethod
    def _packet_id(receipt_hash: str, target_organ: str, operation: str) -> str:
        return "dsp-" + canonical_hash({
            "activation_receipt_hash": receipt_hash,
            "target_organ": target_organ,
            "operation": operation,
        })

    def _seal_receipt(
        self,
        *,
        parent_activation: Dict[str, Any],
        target_organ: str,
        operation: str,
        dispatch_id: str,
        terminal: str,
        authorized: bool,
        reasons: list[str],
        packet_path: Optional[str] = None,
        packet_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        receipt = {
            "schema": "janus.activator.dispatch_receipt.v0.3",
            "dispatch_id": dispatch_id,
            "created_at": time.time(),
            "parent_dispatch_hash": self.ledger.tip_hash(),
            "activation_id": str(parent_activation.get("activation_id") or "UNKNOWN"),
            "activation_receipt_hash": str(parent_activation.get("receipt_hash") or ""),
            "target_organ": target_organ,
            "operation": operation,
            "dispatch_authorized": bool(authorized),
            "external_effect_authorized": False,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
            "packet_path": packet_path,
            "packet_hash": packet_hash,
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("DISPATCH_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def dispatch(
        self,
        activation_receipt: Dict[str, Any],
        *,
        target_organ: str,
        operation: str = READ_ONLY_OPERATION,
    ) -> Dict[str, Any]:
        target_organ = str(target_organ).strip()
        operation = str(operation).strip().upper()
        receipt_hash = str(activation_receipt.get("receipt_hash") or "") if isinstance(activation_receipt, dict) else ""
        dispatch_id = self._packet_id(receipt_hash, target_organ, operation)

        if not verify_sealed_receipt(activation_receipt):
            return self._seal_receipt(
                parent_activation=activation_receipt if isinstance(activation_receipt, dict) else {},
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="BLOCKED_INVALID_ACTIVATION_RECEIPT",
                authorized=False,
                reasons=["Parent activation receipt hash did not verify."],
            )

        if activation_receipt.get("terminal") != "ROUTE_PROPOSED":
            return self._seal_receipt(
                parent_activation=activation_receipt,
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="BLOCKED_ACTIVATION_NOT_ROUTE_PROPOSED",
                authorized=False,
                reasons=["Only a sealed ROUTE_PROPOSED activation may enter the dispatch broker."],
            )

        if operation != READ_ONLY_OPERATION:
            return self._seal_receipt(
                parent_activation=activation_receipt,
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="BLOCKED_OPERATION",
                authorized=False,
                reasons=["v0.3 auto-dispatch allows only WAKE_ORGAN_READ_ONLY."],
            )

        route = self._route_for_target(activation_receipt, target_organ)
        if route is None:
            return self._seal_receipt(
                parent_activation=activation_receipt,
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="BLOCKED_TARGET_NOT_SELECTED",
                authorized=False,
                reasons=["Target organ was not selected by the sealed activation route."],
            )

        if target_organ in FORBIDDEN_AUTO_TARGETS:
            return self._seal_receipt(
                parent_activation=activation_receipt,
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="BLOCKED_FORBIDDEN_AUTO_TARGET",
                authorized=False,
                reasons=["Human operator effect surface is never auto-dispatched by HOME."],
            )

        if activation_receipt.get("external_effect_authorized") is not False or route.get("external_effect_authorized") is not False:
            return self._seal_receipt(
                parent_activation=activation_receipt,
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="BLOCKED_ROUTE_EFFECT_AUTHORITY",
                authorized=False,
                reasons=["Auto-dispatch requires parent and route external_effect_authorized=false."],
            )

        packet_path = self.outbox_dir / f"{dispatch_id}.json"
        if packet_path.exists():
            existing = json.loads(packet_path.read_text(encoding="utf-8"))
            if not verify_dispatch_packet(existing):
                return self._seal_receipt(
                    parent_activation=activation_receipt,
                    target_organ=target_organ,
                    operation=operation,
                    dispatch_id=dispatch_id,
                    terminal="BLOCKED_INVALID_ACTIVATION_RECEIPT",
                    authorized=False,
                    reasons=["Existing deterministic packet failed integrity verification; no overwrite or retry performed."],
                )
            return self._seal_receipt(
                parent_activation=activation_receipt,
                target_organ=target_organ,
                operation=operation,
                dispatch_id=dispatch_id,
                terminal="ALREADY_EMITTED",
                authorized=True,
                reasons=["Deterministic dispatch packet already exists; downstream operation was not emitted twice."],
                packet_path=str(packet_path),
                packet_hash=str(existing["packet_hash"]),
            )

        packet = {
            "schema": "janus.activator.dispatch_packet.v0.3",
            "packet_id": dispatch_id,
            "created_at": time.time(),
            "activation_id": str(activation_receipt.get("activation_id")),
            "activation_receipt_hash": receipt_hash,
            "route_match": str(route.get("match") or ""),
            "target_organ": target_organ,
            "operation": operation,
            "risk_class": READ_ONLY_RISK_CLASS,
            "required_gates": list(dict.fromkeys(str(x) for x in (route.get("required_gates") or []) if str(x))),
            "dispatch_authorized": True,
            "external_effect_authorized": False,
            "claim_authority_granted": False,
            "command_authority_granted": False,
            "effect_scope": READ_ONLY_EFFECT_SCOPE,
            "delivery_terminal": "AUTHORIZED_INTERNAL_HANDOFF",
        }
        packet["packet_hash"] = canonical_hash(packet)
        packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not verify_dispatch_packet(json.loads(packet_path.read_text(encoding="utf-8"))):
            raise RuntimeError("DISPATCH_PACKET_INTEGRITY_FAILURE_AFTER_WRITE")

        return self._seal_receipt(
            parent_activation=activation_receipt,
            target_organ=target_organ,
            operation=operation,
            dispatch_id=dispatch_id,
            terminal="AUTHORIZED_INTERNAL_HANDOFF",
            authorized=True,
            reasons=[
                "Target was selected by a sealed activation route.",
                "Only low-risk internal read-only organ wake is authorized.",
                "Cross-repository transport and target execution remain separate gates.",
            ],
            packet_path=str(packet_path),
            packet_hash=str(packet["packet_hash"]),
        )


__all__ = [
    "DispatchLedger",
    "JanusDispatchBroker",
    "READ_ONLY_OPERATION",
    "verify_dispatch_packet",
    "verify_sealed_receipt",
]
