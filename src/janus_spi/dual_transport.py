from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from .activator import canonical_hash
from .dispatch import verify_dispatch_packet
from .execution_grant import verify_execution_grant
from .execution_transport import JanusExecutionTransportBroker
from .mailbox_transport import JanusCredentiallessMailboxTransport
from .transport import JanusTransportBroker


class PacketLane(Protocol):
    def send(self, packet: Dict[str, Any], *, token: str) -> Dict[str, Any]: ...


class GrantLane(Protocol):
    def send(self, grant: Dict[str, Any], *, token: str) -> Dict[str, Any]: ...


class MailboxLane(Protocol):
    def publish(self, obj: Dict[str, Any], *, object_kind: str, local_github_token: str) -> Dict[str, Any]: ...


class DualTransportLedger:
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
                raise ValueError("DUAL_TRANSPORT_LEDGER_ROW_NOT_OBJECT")
            rows.append(row)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["receipt_hash"]) if rows else None

    def append(self, row: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(row)
        body.pop("receipt_hash", None)
        body["receipt_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return body

    def verify(self) -> bool:
        previous: Optional[str] = None
        for row in self.read():
            if row.get("parent_dual_transport_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True


def _secret_packet_emitted(receipt: Dict[str, Any]) -> bool:
    return receipt.get("terminal") in {"TRANSPORT_SENT_AWAITING_ACK", "TRANSPORT_OUTCOME_UNDETERMINED"}


def _secret_grant_emitted(receipt: Dict[str, Any]) -> bool:
    return receipt.get("terminal") in {"EXECUTION_TRANSPORT_SENT_AWAITING_RESULT", "EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED"}


def _mailbox_emitted(receipt: Dict[str, Any]) -> bool:
    return receipt.get("terminal") in {"MAILBOX_PUBLISHED_AWAITING_PULL", "MAILBOX_ALREADY_PUBLISHED"}


def _dual_terminal(*, secret_emitted: bool, mailbox_emitted: bool, object_kind: str) -> str:
    prefix = "DUAL_PACKET" if object_kind == "DISPATCH_PACKET" else "DUAL_GRANT"
    if secret_emitted and mailbox_emitted:
        return prefix + "_BOTH_EMITTED"
    if secret_emitted:
        return prefix + "_SECRET_ONLY_MAILBOX_DEGRADED"
    if mailbox_emitted:
        return prefix + "_MAILBOX_ONLY_SECRET_DEGRADED"
    return prefix + "_NO_LANE_EMITTED"


class JanusDualTransportBroker:
    """Always attempts both independent transport lanes for one sealed object.

    The broker does not select a winner and cannot multiply authority. For P12
    execution grants, duplicate deliveries converge on the deterministic
    grant_id and the target-side create-only execution claim decides which
    arrival may execute at most once.
    """

    def __init__(
        self,
        state_dir: str | Path = "state/activator",
        *,
        packet_lane: PacketLane | None = None,
        grant_lane: GrantLane | None = None,
        mailbox_lane: MailboxLane | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.packet_lane = packet_lane or JanusTransportBroker(self.state_dir)
        self.grant_lane = grant_lane or JanusExecutionTransportBroker(self.state_dir)
        self.mailbox_lane = mailbox_lane or JanusCredentiallessMailboxTransport(self.state_dir)
        self.ledger = DualTransportLedger(self.state_dir / "dual_transport_ledger.jsonl")

    def _seal(
        self,
        *,
        object_kind: str,
        object_id: str,
        object_hash: str,
        secret: Dict[str, Any],
        mailbox: Dict[str, Any],
        secret_emitted: bool,
        mailbox_emitted: bool,
    ) -> Dict[str, Any]:
        row = {
            "schema": "janus.activator.dual_transport_receipt.v1.0",
            "created_at": time.time(),
            "parent_dual_transport_hash": self.ledger.tip_hash(),
            "object_kind": object_kind,
            "object_id": object_id,
            "object_hash": object_hash,
            "lanes_attempted": ["SECRET_PUSH", "CREDENTIALLESS_PULL"],
            "secret_push": {
                "attempted": True,
                "emitted": bool(secret_emitted),
                "terminal": secret.get("terminal"),
                "receipt_hash": secret.get("receipt_hash"),
            },
            "credentialless_pull": {
                "attempted": True,
                "emitted": bool(mailbox_emitted),
                "terminal": mailbox.get("terminal"),
                "receipt_hash": mailbox.get("receipt_hash"),
                "message_hash": mailbox.get("message_hash"),
                "message_path": mailbox.get("message_path"),
            },
            "at_least_one_lane_emitted": bool(secret_emitted or mailbox_emitted),
            "strict_identity_provenance_available": bool(secret_emitted),
            "credentialless_identity_proof": False,
            "duplicate_execution_prevention": "TARGET_CREATE_ONLY_CLAIM_BY_GRANT_ID" if object_kind == "EXECUTION_GRANT" else "NOT_EXECUTION_OBJECT",
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": _dual_terminal(
                secret_emitted=secret_emitted,
                mailbox_emitted=mailbox_emitted,
                object_kind=object_kind,
            ),
        }
        sealed = self.ledger.append(row)
        if not self.ledger.verify():
            raise RuntimeError("DUAL_TRANSPORT_LEDGER_CHAIN_INVALID")
        return sealed

    def dispatch(
        self,
        packet: Dict[str, Any],
        *,
        secret_token: str,
        local_github_token: str,
    ) -> Dict[str, Any]:
        if not verify_dispatch_packet(packet):
            raise ValueError("DUAL_TRANSPORT_INVALID_DISPATCH_PACKET")

        # Both lanes are attempted unconditionally. Missing credentials are
        # represented as bounded lane terminals, never as a lane-selection
        # decision and never as permission to elevate the other lane.
        secret = self.packet_lane.send(packet, token=secret_token)
        mailbox = self.mailbox_lane.publish(
            packet,
            object_kind="DISPATCH_PACKET",
            local_github_token=local_github_token,
        )
        return self._seal(
            object_kind="DISPATCH_PACKET",
            object_id=str(packet["packet_id"]),
            object_hash=str(packet["packet_hash"]),
            secret=secret,
            mailbox=mailbox,
            secret_emitted=_secret_packet_emitted(secret),
            mailbox_emitted=_mailbox_emitted(mailbox),
        )

    def execute(
        self,
        grant: Dict[str, Any],
        *,
        secret_token: str,
        local_github_token: str,
    ) -> Dict[str, Any]:
        if not verify_execution_grant(grant):
            raise ValueError("DUAL_TRANSPORT_INVALID_EXECUTION_GRANT")

        secret = self.grant_lane.send(grant, token=secret_token)
        mailbox = self.mailbox_lane.publish(
            grant,
            object_kind="EXECUTION_GRANT",
            local_github_token=local_github_token,
        )
        return self._seal(
            object_kind="EXECUTION_GRANT",
            object_id=str(grant["grant_id"]),
            object_hash=str(grant["grant_hash"]),
            secret=secret,
            mailbox=mailbox,
            secret_emitted=_secret_grant_emitted(secret),
            mailbox_emitted=_mailbox_emitted(mailbox),
        )


__all__ = ["DualTransportLedger", "JanusDualTransportBroker"]
