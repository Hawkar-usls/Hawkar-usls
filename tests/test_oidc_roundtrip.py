from __future__ import annotations

import json
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.oidc_mailbox import IDENTITY_SCHEMA, REQUEST_SCHEMA
from janus_spi.oidc_roundtrip import JanusOIDCPacketRoundtrip, SUCCESS_TERMINAL


class FakeSecretLane:
    def __init__(self):
        self.calls = []

    def send(self, packet, *, token):
        self.calls.append((packet["packet_id"], token))
        return {
            "terminal": "TRANSPORT_SENT_AWAITING_ACK" if token else "TRANSPORT_BLOCKED_NO_CREDENTIAL",
            "receipt_hash": "1" * 64,
        }


class FakeOIDCPublisher:
    def __init__(self, root: Path):
        self.root = root
        self.calls = []

    def publish(self, packet, *, local_github_token):
        self.calls.append((packet["packet_id"], local_github_token))
        audience = f"urn:janus:mailbox-request:v1.1:DISPATCH_PACKET:{packet['packet_id']}:{packet['packet_hash']}"
        request = {
            "schema": REQUEST_SCHEMA,
            "created_at": packet["created_at"],
            "source_repository": "Hawkar-usls/Hawkar-usls",
            "target_repository": "Hawkar-usls/Janus-Demiurge",
            "object_kind": "DISPATCH_PACKET",
            "object_id": packet["packet_id"],
            "object_hash": packet["packet_hash"],
            "object": packet,
            "source_identity": {
                "schema": IDENTITY_SCHEMA,
                "provider": "GITHUB_ACTIONS_OIDC",
                "role": "HOME_REQUEST_SOURCE",
                "audience": audience,
                "bound_at": 1.0,
                "jwt": "fake.source.jwt",
            },
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
        }
        request["message_hash"] = canonical_hash(request)
        path = self.root / "request.json"
        path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "terminal": "OIDC_MAILBOX_PUBLISHED_AWAITING_SIGNED_ACK",
            "published": True,
            "identity_proof": True,
            "message_hash": request["message_hash"],
            "message_path": str(path),
        }


class FakeOIDCReader:
    def __init__(self):
        self.calls = 0

    def read_verified(self, request):
        self.calls += 1
        response = {
            "schema": "janus.demiurge.mailbox_response.v1.1",
            "response_hash": "2" * 64,
            "response_core_hash": "3" * 64,
            "identity_proof": True,
        }
        verification = {
            "ok": True,
            "identity_proof": True,
            "terminal": "OIDC_RESPONSE_VERIFIED_BIDIRECTIONAL_OBJECT_BOUND_IDENTITY",
        }
        return response, verification


def test_roundtrip_attempts_both_lanes_even_when_secret_is_missing(tmp_path, monkeypatch):
    secret = FakeSecretLane()
    publisher = FakeOIDCPublisher(tmp_path)
    reader = FakeOIDCReader()
    monkeypatch.setattr(
        "janus_spi.oidc_roundtrip.verify_request_envelope",
        lambda request: {"ok": True, "identity_proof": True, "terminal": "TEST_SOURCE_VERIFIED"},
    )
    witness = JanusOIDCPacketRoundtrip(
        state_dir=tmp_path / "state",
        secret_lane=secret,
        oidc_publisher=publisher,
        oidc_reader=reader,
        sleep_fn=lambda _seconds: None,
        poll_interval_seconds=1,
        max_wait_seconds=5,
    )
    result = witness.run(
        source_ref="TEST_OIDC_ROUNDTRIP/1",
        payload={"purpose": "test"},
        secret_dispatch_token="",
        local_github_token="home-local-token",
    )
    assert result["terminal"] == SUCCESS_TERMINAL
    assert result["lanes_attempted"] == ["SECRET_PUSH", "OIDC_CREDENTIALLESS_PULL"]
    assert result["secret_lane_attempted"] is True
    assert result["secret_lane_emitted"] is False
    assert result["secret_lane_terminal"] == "TRANSPORT_BLOCKED_NO_CREDENTIAL"
    assert result["oidc_lane_attempted"] is True
    assert result["oidc_lane_emitted"] is True
    assert result["oidc_source_identity_verified"] is True
    assert result["oidc_target_identity_verified"] is True
    assert result["bidirectional_identity_proof"] is True
    assert result["target_execution_observed"] is False
    assert result["p12_execution_authority_granted"] is False
    assert result["is_launch_witness"] is False
    assert result["external_effect_authorized"] is False
    assert len(secret.calls) == 1
    assert len(publisher.calls) == 1
    assert reader.calls == 1


def test_local_source_identity_failure_blocks_before_accepting_target_response(tmp_path, monkeypatch):
    secret = FakeSecretLane()
    publisher = FakeOIDCPublisher(tmp_path)
    reader = FakeOIDCReader()
    monkeypatch.setattr(
        "janus_spi.oidc_roundtrip.verify_request_envelope",
        lambda request: {"ok": False, "identity_proof": False, "terminal": "OIDC_TEST_SOURCE_REJECT"},
    )
    witness = JanusOIDCPacketRoundtrip(
        state_dir=tmp_path / "state",
        secret_lane=secret,
        oidc_publisher=publisher,
        oidc_reader=reader,
        sleep_fn=lambda _seconds: None,
        max_wait_seconds=5,
    )
    result = witness.run(
        source_ref="TEST_OIDC_ROUNDTRIP/2",
        payload={"purpose": "test"},
        secret_dispatch_token="secret-token",
        local_github_token="home-local-token",
    )
    assert result["terminal"] == "OIDC_ROUNDTRIP_BLOCKED_LOCAL_SOURCE_IDENTITY"
    assert result["bidirectional_identity_proof"] is False
    assert reader.calls == 0
