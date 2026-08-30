from __future__ import annotations

import json
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.mailbox_roundtrip import (
    SUCCESS_TERMINAL,
    JanusCredentiallessPacketRoundtrip,
    verify_delivery_ack,
)
from janus_spi.mailbox_transport import PROVENANCE_CLASS, build_message


class FakeDualBroker:
    def __init__(self, root: Path):
        self.root = root
        self.calls = 0

    def dispatch(self, packet, *, secret_token, local_github_token):
        self.calls += 1
        request = build_message(packet, "DISPATCH_PACKET")
        path = self.root / "fake-mailbox-request.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "receipt_hash": "1" * 64,
            "secret_push": {
                "terminal": "TRANSPORT_BLOCKED_NO_CREDENTIAL" if not secret_token else "TRANSPORT_SENT_AWAITING_ACK",
                "emitted": bool(secret_token),
            },
            "credentialless_pull": {
                "terminal": "MAILBOX_PUBLISHED_AWAITING_PULL",
                "emitted": True,
                "message_hash": request["message_hash"],
                "message_path": str(path),
            },
        }


class FakeReader:
    def read(self, request):
        packet = request["object"]
        ack = {
            "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
            "created_at": 3.0,
            "packet_id": packet["packet_id"],
            "packet_hash": packet["packet_hash"],
            "accepted": True,
            "terminal": "ACK_ACCEPTED_NO_EXECUTION",
            "reasons": ["fake bounded delivery"],
            "execution_authorized": False,
            "execution_performed": False,
            "claim_authority_granted": False,
            "external_effect_authorized": False,
        }
        ack["ack_hash"] = canonical_hash(ack)
        response = {
            "schema": "janus.demiurge.mailbox_response.v1.0",
            "created_at": 4.0,
            "source_repository": "Hawkar-usls/Janus-Demiurge",
            "target_repository": "Hawkar-usls/Hawkar-usls",
            "request_message_hash": request["message_hash"],
            "request_object_kind": request["object_kind"],
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
            "payload": {"ack": ack},
            "terminal": "MAILBOX_DELIVERY_ACK_EMITTED",
        }
        response["response_hash"] = canonical_hash(response)
        return response


def test_delivery_ack_requires_no_execution_and_exact_packet_binding():
    packet = {
        "schema": "janus.activator.dispatch_packet.v0.3",
        "packet_id": "",
        "created_at": 1.0,
        "activation_id": "act-test",
        "activation_receipt_hash": "a" * 64,
        "route_match": "research_or_anomaly_investigation",
        "target_organ": "Hawkar-usls/Janus-Demiurge",
        "operation": "WAKE_ORGAN_READ_ONLY",
        "risk_class": "R0_INTERNAL_READ_ONLY_ORGAN_WAKE",
        "required_gates": [],
        "dispatch_authorized": True,
        "external_effect_authorized": False,
        "claim_authority_granted": False,
        "command_authority_granted": False,
        "effect_scope": "GITHUB_INTERNAL_READ_ONLY_ANALYSIS",
        "delivery_terminal": "AUTHORIZED_INTERNAL_HANDOFF",
    }
    packet["packet_id"] = "dsp-" + canonical_hash({
        "activation_receipt_hash": packet["activation_receipt_hash"],
        "target_organ": packet["target_organ"],
        "operation": packet["operation"],
    })
    packet["packet_hash"] = canonical_hash(packet)
    ack = {
        "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
        "created_at": 2.0,
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "accepted": True,
        "terminal": "ACK_ACCEPTED_NO_EXECUTION",
        "reasons": ["test"],
        "execution_authorized": False,
        "execution_performed": False,
        "claim_authority_granted": False,
        "external_effect_authorized": False,
    }
    ack["ack_hash"] = canonical_hash(ack)
    assert verify_delivery_ack(ack, packet) is True
    ack["execution_performed"] = True
    ack["ack_hash"] = canonical_hash({k: v for k, v in ack.items() if k != "ack_hash"})
    assert verify_delivery_ack(ack, packet) is False


def test_local_roundtrip_logic_succeeds_without_elevating_public_provenance(tmp_path):
    dual = FakeDualBroker(tmp_path)
    witness = JanusCredentiallessPacketRoundtrip(
        state_dir=tmp_path / "state",
        reader=FakeReader(),
        dual_broker=dual,
        sleep_fn=lambda _seconds: None,
        poll_interval_seconds=1,
        max_wait_seconds=5,
    )
    result = witness.run(
        source_ref="TEST_CREDENTIALLESS_ROUNDTRIP/1",
        payload={"purpose": "test dual-lane mailbox ACK"},
        secret_dispatch_token="",
        local_github_token="home-local-token",
    )
    assert dual.calls == 1
    assert result["terminal"] == SUCCESS_TERMINAL
    assert result["credentialless_ack_observed"] is True
    assert result["credentialless_identity_proof"] is False
    assert result["target_execution_observed"] is False
    assert result["secret_lane_emitted"] is False
    assert result["credentialless_lane_emitted"] is True
    assert result["external_effect_authorized"] is False
    assert result["physical_runtime_effect_authorized"] is False
