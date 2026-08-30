from __future__ import annotations

import base64
import json
import urllib.error
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.mailbox_transport import (
    HOME_REPOSITORY,
    PROVENANCE_CLASS,
    TARGET_REPOSITORY,
    JanusCredentiallessMailboxTransport,
    build_message,
    verify_message,
    verify_response,
)


class Response:
    def __init__(self, status=201, body=b"{}"):
        self.status = status
        self._body = body

    def read(self):
        return self._body


def packet() -> dict:
    row = {
        "schema": "janus.activator.dispatch_packet.v0.3",
        "created_at": 1.0,
        "activation_id": "act-test",
        "activation_receipt_hash": "a" * 64,
        "route_match": "research_or_anomaly_investigation",
        "target_organ": TARGET_REPOSITORY,
        "operation": "WAKE_ORGAN_READ_ONLY",
        "risk_class": "R0_INTERNAL_READ_ONLY_ORGAN_WAKE",
        "required_gates": ["DEMIHEAD"],
        "dispatch_authorized": True,
        "external_effect_authorized": False,
        "claim_authority_granted": False,
        "command_authority_granted": False,
        "effect_scope": "GITHUB_INTERNAL_READ_ONLY_ANALYSIS",
        "delivery_terminal": "AUTHORIZED_INTERNAL_HANDOFF",
    }
    row["packet_id"] = "dsp-" + canonical_hash({
        "activation_receipt_hash": row["activation_receipt_hash"],
        "target_organ": row["target_organ"],
        "operation": row["operation"],
    })
    row["packet_hash"] = canonical_hash(row)
    return row


def test_build_message_is_hash_bound_authority_bounded_and_deterministic():
    obj = packet()
    first = build_message(obj, "DISPATCH_PACKET")
    second = build_message(obj, "DISPATCH_PACKET")
    assert first == second
    assert first["message_hash"] == second["message_hash"]
    assert first["created_at"] == obj["created_at"]
    assert verify_message(first) is True
    assert first["source_repository"] == HOME_REPOSITORY
    assert first["target_repository"] == TARGET_REPOSITORY
    assert first["external_effect_authorized"] is False
    assert first["physical_runtime_effect_authorized"] is False


def test_publish_uses_only_local_repository_token_and_records_no_cross_repo_credential(tmp_path):
    broker = JanusCredentiallessMailboxTransport(
        tmp_path,
        opener=lambda request, timeout=20.0: Response(201),
    )
    result = broker.publish(packet(), object_kind="DISPATCH_PACKET", local_github_token="home-local-token")
    assert result["terminal"] == "MAILBOX_PUBLISHED_AWAITING_PULL"
    assert result["published"] is True
    assert result["cross_repository_credential_used"] is False
    assert result["own_repository_credential_persisted"] is False
    assert result["external_effect_authorized"] is False
    assert result["message_path"] is not None
    local = json.loads(Path(result["message_path"]).read_text(encoding="utf-8"))
    assert verify_message(local) is True
    assert local["message_hash"] == result["message_hash"]
    assert broker.ledger.verify() is True


def test_republish_same_object_is_idempotent_not_conflict(tmp_path):
    stored = {}

    def opener(request, timeout=20.0):
        if request.get_method() == "PUT":
            if "message" in stored:
                raise urllib.error.HTTPError(request.full_url, 422, "already exists", {}, None)
            payload = json.loads(request.data.decode("utf-8"))
            stored["message"] = json.loads(base64.b64decode(payload["content"]).decode("utf-8"))
            return Response(201)
        return Response(200, (json.dumps(stored["message"]) + "\n").encode("utf-8"))

    broker = JanusCredentiallessMailboxTransport(tmp_path, opener=opener)
    obj = packet()
    first = broker.publish(obj, object_kind="DISPATCH_PACKET", local_github_token="home-local-token")
    second = broker.publish(obj, object_kind="DISPATCH_PACKET", local_github_token="home-local-token")
    assert first["terminal"] == "MAILBOX_PUBLISHED_AWAITING_PULL"
    assert second["terminal"] == "MAILBOX_ALREADY_PUBLISHED"
    assert first["message_hash"] == second["message_hash"]
    assert first["message_path"] == second["message_path"]
    assert broker.ledger.verify() is True


def test_missing_home_local_token_fails_before_publish_but_preserves_request(tmp_path):
    calls = []
    broker = JanusCredentiallessMailboxTransport(
        tmp_path,
        opener=lambda request, timeout=20.0: calls.append(request) or Response(201),
    )
    result = broker.publish(packet(), object_kind="DISPATCH_PACKET", local_github_token="")
    assert result["terminal"] == "MAILBOX_PUBLISH_BLOCKED_NO_LOCAL_GITHUB_TOKEN"
    assert result["published"] is False
    assert result["message_path"] is not None
    assert Path(result["message_path"]).is_file()
    assert calls == []


def test_public_response_is_accepted_only_as_non_identity_provenance():
    request = build_message(packet(), "DISPATCH_PACKET")
    response = {
        "schema": "janus.demiurge.mailbox_response.v1.0",
        "created_at": 3.0,
        "source_repository": TARGET_REPOSITORY,
        "target_repository": HOME_REPOSITORY,
        "request_message_hash": request["message_hash"],
        "request_object_kind": "DISPATCH_PACKET",
        "request_object_id": request["object_id"],
        "request_object_hash": request["object_hash"],
        "provenance_class": PROVENANCE_CLASS,
        "identity_proof": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "response_kind": "DELIVERY_ACK",
        "payload": {"ack": {"accepted": True}},
        "terminal": "MAILBOX_DELIVERY_ACK_EMITTED",
    }
    response["response_hash"] = canonical_hash(response)
    assert verify_response(response, request) is True

    wrong_kind = dict(response)
    wrong_kind["request_object_kind"] = "EXECUTION_GRANT"
    wrong_kind["response_hash"] = canonical_hash({k: v for k, v in wrong_kind.items() if k != "response_hash"})
    assert verify_response(wrong_kind, request) is False

    response["identity_proof"] = True
    response["response_hash"] = canonical_hash({k: v for k, v in response.items() if k != "response_hash"})
    assert verify_response(response, request) is False
