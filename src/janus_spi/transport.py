from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from .activator import canonical_hash
from .dispatch import verify_dispatch_packet

TARGET_ORGAN = "Hawkar-usls/Janus-Demiurge"
ENDPOINT = "https://api.github.com/repos/Hawkar-usls/Janus-Demiurge/dispatches"
EVENT_TYPE = "janus-activator-dispatch-v0.3"
CREDENTIAL_SOURCE = "ENV:JANUS_DEMIURGE_DISPATCH_TOKEN"
EXPECTED_HTTP_STATUS = 204


class UrlOpener(Protocol):
    def __call__(self, request: urllib.request.Request, timeout: float = ...) -> Any: ...


class TransportLedger:
    """Append-only transport-attempt ledger with replay adjudication."""

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
                raise ValueError("TRANSPORT_LEDGER_ROW_NOT_OBJECT")
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
            if row.get("parent_transport_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True

    def crossed_boundary_for_packet(self, packet_id: str) -> bool:
        for row in self.read():
            if row.get("packet_id") != packet_id:
                continue
            if row.get("network_boundary_entered") is True:
                return True
        return False


class JanusTransportBroker:
    """GitHub-internal transport with Third-Wish ambiguous-outcome semantics.

    This broker transports an already-authorized read-only handoff packet to the
    admitted Janus-Demiurge repository-dispatch receiver. It does not authorize
    target execution, claim promotion or any physical/external-world effect.
    """

    def __init__(
        self,
        state_dir: str | Path = "state/activator",
        *,
        opener: UrlOpener = urllib.request.urlopen,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.ledger = TransportLedger(self.state_dir / "transport_ledger.jsonl")
        self.opener = opener
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    @staticmethod
    def _transport_id(packet: Dict[str, Any]) -> str:
        return "tx-" + canonical_hash({
            "packet_id": packet.get("packet_id"),
            "packet_hash": packet.get("packet_hash"),
            "target_organ": packet.get("target_organ"),
            "transport": "GITHUB_REPOSITORY_DISPATCH",
        })

    def _seal(
        self,
        packet: Dict[str, Any],
        *,
        terminal: str,
        reasons: list[str],
        network_boundary_entered: bool,
        automatic_retry_allowed: bool,
        http_status: Optional[int] = None,
    ) -> Dict[str, Any]:
        packet_id = str(packet.get("packet_id") or "dsp-" + "0" * 64)
        packet_hash = str(packet.get("packet_hash") or canonical_hash(packet))
        if len(packet_hash) != 64:
            packet_hash = canonical_hash(packet)
        receipt = {
            "schema": "janus.activator.transport_receipt.v0.4",
            "transport_id": self._transport_id(packet),
            "created_at": time.time(),
            "parent_transport_hash": self.ledger.tip_hash(),
            "packet_id": packet_id,
            "packet_hash": packet_hash,
            "target_organ": str(packet.get("target_organ") or "UNKNOWN"),
            "endpoint_class": "GITHUB_REPOSITORY_DISPATCH",
            "credential_source": CREDENTIAL_SOURCE,
            "credential_value_persisted": False,
            "network_boundary_entered": bool(network_boundary_entered),
            "automatic_retry_allowed": bool(automatic_retry_allowed),
            "http_status": http_status,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
            "external_effect_authorized": False,
            "target_execution_authorized": False,
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("TRANSPORT_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def send(self, packet: Dict[str, Any], *, token: str) -> Dict[str, Any]:
        packet = packet if isinstance(packet, dict) else {}
        packet_id = str(packet.get("packet_id") or "")

        if not verify_dispatch_packet(packet):
            return self._seal(
                packet,
                terminal="TRANSPORT_PRE_EFFECT_REJECTED_INVALID_PACKET",
                reasons=["Dispatch packet integrity or deterministic identity failed before transport."],
                network_boundary_entered=False,
                automatic_retry_allowed=True,
            )

        if packet.get("target_organ") != TARGET_ORGAN:
            return self._seal(
                packet,
                terminal="TRANSPORT_PRE_EFFECT_REJECTED_UNSUPPORTED_TARGET",
                reasons=["v0.4 transport admits only the Janus-Demiurge receiver."],
                network_boundary_entered=False,
                automatic_retry_allowed=True,
            )

        if self.ledger.crossed_boundary_for_packet(packet_id):
            return self._seal(
                packet,
                terminal="TRANSPORT_REPLAY_BLOCKED",
                reasons=["This packet id already crossed the network boundary; automatic second send is forbidden."],
                network_boundary_entered=False,
                automatic_retry_allowed=False,
            )

        if not str(token).strip():
            return self._seal(
                packet,
                terminal="TRANSPORT_BLOCKED_NO_CREDENTIAL",
                reasons=["Broker credential is absent; no network call was attempted."],
                network_boundary_entered=False,
                automatic_retry_allowed=True,
            )

        payload = json.dumps({
            "event_type": EVENT_TYPE,
            "client_payload": {"packet": packet},
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "JANUS-Activator-Transport/0.4",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            response = self.opener(request, timeout=self.timeout_seconds)
            status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
            if status == EXPECTED_HTTP_STATUS:
                return self._seal(
                    packet,
                    terminal="TRANSPORT_SENT_AWAITING_ACK",
                    reasons=[
                        "GitHub repository-dispatch endpoint returned HTTP 204.",
                        "Transport submission is recorded; receiver ACK and target execution remain separate gates.",
                    ],
                    network_boundary_entered=True,
                    automatic_retry_allowed=False,
                    http_status=status,
                )
            return self._seal(
                packet,
                terminal="TRANSPORT_OUTCOME_UNDETERMINED",
                reasons=[f"Network boundary returned unexpected HTTP status {status}; no automatic retry is permitted."],
                network_boundary_entered=True,
                automatic_retry_allowed=False,
                http_status=status or None,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            status = int(getattr(exc, "code", 0) or 0) or None
            return self._seal(
                packet,
                terminal="TRANSPORT_OUTCOME_UNDETERMINED",
                reasons=[
                    f"Transport call entered the network boundary and ended with {type(exc).__name__}.",
                    "Whether the receiver event was created is not inferred from transport silence/failure; automatic retry is forbidden until adjudicated.",
                ],
                network_boundary_entered=True,
                automatic_retry_allowed=False,
                http_status=status,
            )


__all__ = ["JanusTransportBroker", "TransportLedger", "TARGET_ORGAN"]
