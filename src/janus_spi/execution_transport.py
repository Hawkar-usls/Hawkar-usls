from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from .activator import canonical_hash
from .execution_grant import verify_execution_grant

TARGET_REPOSITORY = "Hawkar-usls/Janus-Demiurge"
ENDPOINT = "https://api.github.com/repos/Hawkar-usls/Janus-Demiurge/dispatches"
EVENT_TYPE = "janus-activator-execution-grant-v0.7"
CREDENTIAL_SOURCE = "ENV:JANUS_DEMIURGE_DISPATCH_TOKEN"
EXPECTED_HTTP_STATUS = 204


class UrlOpener(Protocol):
    def __call__(self, request: urllib.request.Request, timeout: float = ...) -> Any: ...


class ExecutionTransportLedger:
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
                raise ValueError("EXECUTION_TRANSPORT_LEDGER_ROW_NOT_OBJECT")
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
            if row.get("parent_execution_transport_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True

    def crossed_boundary_for_grant(self, grant_id: str) -> bool:
        return any(
            row.get("grant_id") == grant_id and row.get("network_boundary_entered") is True
            for row in self.read()
        )


def verify_execution_transport_receipt(receipt: Dict[str, Any]) -> bool:
    if not isinstance(receipt, dict):
        return False
    claimed = str(receipt.get("receipt_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(receipt)
    body.pop("receipt_hash", None)
    if canonical_hash(body) != claimed:
        return False
    if receipt.get("schema") != "janus.activator.execution_transport_receipt.v0.8":
        return False
    if receipt.get("target_repository") != TARGET_REPOSITORY:
        return False
    if receipt.get("external_effect_authorized") is not False:
        return False
    if receipt.get("claim_authority_granted") is not False:
        return False
    if receipt.get("scientific_evidence_authority_granted") is not False:
        return False
    return True


class JanusExecutionTransportBroker:
    """Transport an already-issued bounded execution grant to Janus-Demiurge.

    This is a GitHub-internal control-plane transport. It preserves the Third-Wish
    distinction between pre-effect rejection and ambiguous post-boundary outcome,
    and never automatically sends the same grant twice after the network boundary.
    """

    def __init__(
        self,
        state_dir: str | Path = "state/activator",
        *,
        opener: UrlOpener = urllib.request.urlopen,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.ledger = ExecutionTransportLedger(self.state_dir / "execution_transport_ledger.jsonl")
        self.opener = opener
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    @staticmethod
    def _transport_id(grant: Dict[str, Any]) -> str:
        return "xtx-" + canonical_hash({
            "grant_id": grant.get("grant_id"),
            "grant_hash": grant.get("grant_hash"),
            "target_repository": TARGET_REPOSITORY,
            "event_type": EVENT_TYPE,
        })

    def _seal(
        self,
        grant: Dict[str, Any],
        *,
        terminal: str,
        reasons: list[str],
        network_boundary_entered: bool,
        automatic_retry_allowed: bool,
        http_status: Optional[int] = None,
    ) -> Dict[str, Any]:
        grant_id = str(grant.get("grant_id") or "xg-" + "0" * 64)
        grant_hash = str(grant.get("grant_hash") or canonical_hash(grant))
        if len(grant_hash) != 64:
            grant_hash = canonical_hash(grant)
        receipt = {
            "schema": "janus.activator.execution_transport_receipt.v0.8",
            "execution_transport_id": self._transport_id(grant),
            "created_at": time.time(),
            "parent_execution_transport_hash": self.ledger.tip_hash(),
            "grant_id": grant_id,
            "grant_hash": grant_hash,
            "target_repository": TARGET_REPOSITORY,
            "event_type": EVENT_TYPE,
            "credential_source": CREDENTIAL_SOURCE,
            "credential_value_persisted": False,
            "network_boundary_entered": bool(network_boundary_entered),
            "automatic_retry_allowed": bool(automatic_retry_allowed),
            "http_status": http_status,
            "terminal": terminal,
            "reasons": list(dict.fromkeys(reasons)),
            "target_execution_authority_transported": verify_execution_grant(grant),
            "target_execution_observed": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("EXECUTION_TRANSPORT_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed

    def send(self, grant: Dict[str, Any], *, token: str) -> Dict[str, Any]:
        grant = grant if isinstance(grant, dict) else {}
        grant_id = str(grant.get("grant_id") or "")

        if not verify_execution_grant(grant):
            return self._seal(
                grant,
                terminal="EXECUTION_TRANSPORT_PRE_EFFECT_REJECTED_INVALID_GRANT",
                reasons=["Execution grant failed integrity, deterministic identity or authority-ceiling checks before transport."],
                network_boundary_entered=False,
                automatic_retry_allowed=True,
            )

        if self.ledger.crossed_boundary_for_grant(grant_id):
            return self._seal(
                grant,
                terminal="EXECUTION_TRANSPORT_REPLAY_BLOCKED",
                reasons=["This exact grant id already crossed the network boundary; automatic second send is forbidden."],
                network_boundary_entered=False,
                automatic_retry_allowed=False,
            )

        if not str(token).strip():
            return self._seal(
                grant,
                terminal="EXECUTION_TRANSPORT_BLOCKED_NO_CREDENTIAL",
                reasons=["Cross-repository broker credential is absent; no network call was attempted."],
                network_boundary_entered=False,
                automatic_retry_allowed=True,
            )

        payload = json.dumps({
            "event_type": EVENT_TYPE,
            "client_payload": {"grant": grant},
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "JANUS-Activator-Execution-Transport/0.8",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            response = self.opener(request, timeout=self.timeout_seconds)
            status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
            if status == EXPECTED_HTTP_STATUS:
                return self._seal(
                    grant,
                    terminal="EXECUTION_TRANSPORT_SENT_AWAITING_RESULT",
                    reasons=[
                        "GitHub repository-dispatch endpoint returned HTTP 204 for the bounded execution grant.",
                        "Submission is recorded; target execution and execution-receipt provenance remain separate gates.",
                    ],
                    network_boundary_entered=True,
                    automatic_retry_allowed=False,
                    http_status=status,
                )
            return self._seal(
                grant,
                terminal="EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED",
                reasons=[f"Network boundary returned unexpected HTTP status {status}; no automatic retry is permitted."],
                network_boundary_entered=True,
                automatic_retry_allowed=False,
                http_status=status or None,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            status = int(getattr(exc, "code", 0) or 0) or None
            return self._seal(
                grant,
                terminal="EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED",
                reasons=[
                    f"Execution transport entered the network boundary and ended with {type(exc).__name__}.",
                    "Whether target execution occurred is not inferred from silence/failure; automatic replay is forbidden until provenance adjudication.",
                ],
                network_boundary_entered=True,
                automatic_retry_allowed=False,
                http_status=status,
            )


__all__ = [
    "ExecutionTransportLedger",
    "JanusExecutionTransportBroker",
    "verify_execution_transport_receipt",
]
