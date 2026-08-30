from __future__ import annotations

import json

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


def test_build_message_is_hash_bound_and_authority_bounded():
    message = build_message(packet(), "DISPATCH_PACKET")
    assert verify_message(message) is True
    assert message["source_repository"] == HOME_REPOSITORY
    assert message["target_repository"] == TARGET_REPOSITORY
    assert message["external_effect_authorized"] is False
    assert message["physical_runtime_effect_authorized"] is False


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
    assert broker.ledger.verify() is True


def test_missing_home_local_token_fails_before_publish(tmp_path):
    calls = []
    broker = JanusCredentiallessMailboxTransport(
        tmp_path,
        opener=lambda request, timeout=20.0: calls.append(request) or Response(201),
    )
    result = broker.publish(packet(), object_kind="DISPATCH_PACKET", local_github_token="")
    assert result["terminal"] == "MAILBOX_PUBLISH_BLOCKED_NO_LOCAL_GITHUB_TOKEN"
    assert result["published"] is False
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
    response["identity_proof"] = True
    response["response_hash"] = canonical_hash({k: v for k, v in response.items() if k != "response_hash"})
    assert verify_response(response, request) is False
