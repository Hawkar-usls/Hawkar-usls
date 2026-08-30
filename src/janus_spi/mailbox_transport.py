from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .activator import canonical_hash
from .dispatch import verify_dispatch_packet
from .execution_grant import verify_execution_grant

HOME_REPOSITORY = "Hawkar-usls/Hawkar-usls"
TARGET_REPOSITORY = "Hawkar-usls/Janus-Demiurge"
HOME_BRANCH = "janus/transport-mailbox"
TARGET_BRANCH = "janus/activator-mailbox"
OUTBOX = ".janus/mailbox/outbox"
TARGET_INBOX = ".janus/mailbox/inbox"
MESSAGE_SCHEMA = "janus.activator.mailbox_message.v1.0"
RESPONSE_SCHEMA = "janus.demiurge.mailbox_response.v1.0"
PROVENANCE_CLASS = "PUBLIC_REPOSITORY_ORIGIN_HASH_BOUND_NOT_IDENTITY_PROOF"


class MailboxTransportLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("MAILBOX_TRANSPORT_LEDGER_ROW_NOT_OBJECT")
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
        return body

    def verify(self) -> bool:
        previous = None
        for row in self.read():
            if row.get("parent_mailbox_transport_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True


def build_message(obj: Dict[str, Any], object_kind: str) -> Dict[str, Any]:
    if object_kind == "DISPATCH_PACKET":
        if not verify_dispatch_packet(obj):
            raise ValueError("MAILBOX_INVALID_DISPATCH_PACKET")
        object_id = str(obj["packet_id"])
        object_hash = str(obj["packet_hash"])
    elif object_kind == "EXECUTION_GRANT":
        if not verify_execution_grant(obj):
            raise ValueError("MAILBOX_INVALID_EXECUTION_GRANT")
        object_id = str(obj["grant_id"])
        object_hash = str(obj["grant_hash"])
    else:
        raise ValueError("MAILBOX_OBJECT_KIND_UNSUPPORTED")
    row = {
        "schema": MESSAGE_SCHEMA,
        "created_at": time.time(),
        "source_repository": HOME_REPOSITORY,
        "target_repository": TARGET_REPOSITORY,
        "object_kind": object_kind,
        "object_id": object_id,
        "object_hash": object_hash,
        "object": obj,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    row["message_hash"] = canonical_hash(row)
    return row


def verify_message(row: Dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    claimed = str(row.get("message_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(row)
    body.pop("message_hash", None)
    if canonical_hash(body) != claimed:
        return False
    if row.get("schema") != MESSAGE_SCHEMA:
        return False
    if row.get("source_repository") != HOME_REPOSITORY or row.get("target_repository") != TARGET_REPOSITORY:
        return False
    if any(row.get(field) is not False for field in (
        "command_authority_granted", "claim_authority_granted", "scientific_evidence_authority_granted",
        "external_effect_authorized", "physical_runtime_effect_authorized",
    )):
        return False
    obj = row.get("object")
    if not isinstance(obj, dict):
        return False
    if row.get("object_kind") == "DISPATCH_PACKET":
        return verify_dispatch_packet(obj) and row.get("object_id") == obj.get("packet_id") and row.get("object_hash") == obj.get("packet_hash")
    if row.get("object_kind") == "EXECUTION_GRANT":
        return verify_execution_grant(obj) and row.get("object_id") == obj.get("grant_id") and row.get("object_hash") == obj.get("grant_hash")
    return False


def verify_response(row: Dict[str, Any], request: Dict[str, Any]) -> bool:
    if not isinstance(row, dict) or not verify_message(request):
        return False
    claimed = str(row.get("response_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(row)
    body.pop("response_hash", None)
    if canonical_hash(body) != claimed:
        return False
    if row.get("schema") != RESPONSE_SCHEMA:
        return False
    if row.get("source_repository") != TARGET_REPOSITORY or row.get("target_repository") != HOME_REPOSITORY:
        return False
    if row.get("request_message_hash") != request.get("message_hash"):
        return False
    if row.get("request_object_id") != request.get("object_id") or row.get("request_object_hash") != request.get("object_hash"):
        return False
    if any(row.get(field) is not False for field in (
        "command_authority_granted", "claim_authority_granted", "scientific_evidence_authority_granted",
        "external_effect_authorized", "physical_runtime_effect_authorized",
    )):
        return False
    return row.get("provenance_class") == PROVENANCE_CLASS and row.get("identity_proof") is False


def _request(url: str, *, token: str = "", data: bytes | None = None, method: str = "GET") -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "JANUS-HOME-Mailbox-Transport/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, method=method, headers=headers)


class JanusCredentiallessMailboxTransport:
    def __init__(self, state_dir: str | Path = "state/activator", *, opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.state_dir = Path(state_dir)
        self.ledger = MailboxTransportLedger(self.state_dir / "mailbox_transport_ledger.jsonl")
        self.opener = opener

    @staticmethod
    def _filename(message: Dict[str, Any]) -> str:
        suffix = "packet" if message["object_kind"] == "DISPATCH_PACKET" else "grant"
        return f"{message['object_id']}.{suffix}.json"

    @staticmethod
    def _api_url(filename: str) -> str:
        path = urllib.parse.quote(f"{OUTBOX}/{filename}", safe="/")
        return f"https://api.github.com/repos/{HOME_REPOSITORY}/contents/{path}"

    @staticmethod
    def _raw_url(filename: str) -> str:
        return f"https://raw.githubusercontent.com/{HOME_REPOSITORY}/{HOME_BRANCH}/{OUTBOX}/{filename}"

    def _existing(self, filename: str) -> Dict[str, Any] | None:
        try:
            response = self.opener(_request(self._raw_url(filename)), timeout=15.0)
            return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def publish(self, obj: Dict[str, Any], *, object_kind: str, local_github_token: str) -> Dict[str, Any]:
        message = build_message(obj, object_kind)
        filename = self._filename(message)
        base = {
            "schema": "janus.activator.mailbox_transport_receipt.v1.0",
            "created_at": time.time(),
            "parent_mailbox_transport_hash": self.ledger.tip_hash(),
            "message_hash": message["message_hash"],
            "object_kind": object_kind,
            "object_id": message["object_id"],
            "object_hash": message["object_hash"],
            "home_mailbox_branch": HOME_BRANCH,
            "cross_repository_credential_used": False,
            "own_repository_credential_persisted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
        }
        if not str(local_github_token).strip():
            base.update({"terminal": "MAILBOX_PUBLISH_BLOCKED_NO_LOCAL_GITHUB_TOKEN", "published": False})
            return self.ledger.append(base)

        encoded = base64.b64encode((json.dumps(message, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")).decode("ascii")
        payload = json.dumps({
            "message": f"Activator mailbox publish {message['object_id']}",
            "content": encoded,
            "branch": HOME_BRANCH,
        }, separators=(",", ":")).encode("utf-8")
        try:
            response = self.opener(_request(self._api_url(filename), token=local_github_token, data=payload, method="PUT"), timeout=20.0)
            status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
            base.update({
                "terminal": "MAILBOX_PUBLISHED_AWAITING_PULL" if status in {200, 201} else "MAILBOX_PUBLISH_OUTCOME_UNDETERMINED",
                "published": status in {200, 201},
                "http_status": status,
            })
        except urllib.error.HTTPError as exc:
            if exc.code in {409, 422}:
                existing = self._existing(filename)
                if verify_message(existing or {}) and existing.get("message_hash") == message["message_hash"]:
                    base.update({"terminal": "MAILBOX_ALREADY_PUBLISHED", "published": True, "http_status": exc.code})
                else:
                    base.update({"terminal": "MAILBOX_PUBLISH_CONFLICT", "published": False, "http_status": exc.code})
            else:
                base.update({"terminal": "MAILBOX_PUBLISH_OUTCOME_UNDETERMINED", "published": False, "http_status": exc.code})
        except (urllib.error.URLError, TimeoutError, OSError):
            base.update({"terminal": "MAILBOX_PUBLISH_OUTCOME_UNDETERMINED", "published": False})
        sealed = self.ledger.append(base)
        if not self.ledger.verify():
            raise RuntimeError("MAILBOX_TRANSPORT_LEDGER_INVALID")
        return sealed


class JanusCredentiallessMailboxReader:
    def __init__(self, *, opener: Callable[..., Any] = urllib.request.urlopen) -> None:
        self.opener = opener

    @staticmethod
    def response_url(request: Dict[str, Any]) -> str:
        suffix = "ack" if request["object_kind"] == "DISPATCH_PACKET" else "execution"
        return (
            f"https://raw.githubusercontent.com/{TARGET_REPOSITORY}/{TARGET_BRANCH}/"
            f"{TARGET_INBOX}/{request['object_id']}.{suffix}.json"
        )

    def read(self, request: Dict[str, Any]) -> Dict[str, Any] | None:
        if not verify_message(request):
            raise ValueError("MAILBOX_REQUEST_INVALID")
        try:
            response = self.opener(_request(self.response_url(request)), timeout=15.0)
            row = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        if not verify_response(row, request):
            raise ValueError("MAILBOX_RESPONSE_INVALID")
        return row


__all__ = [
    "JanusCredentiallessMailboxTransport",
    "JanusCredentiallessMailboxReader",
    "MailboxTransportLedger",
    "build_message",
    "verify_message",
    "verify_response",
]
