from __future__ import annotations

from janus_spi.activator import canonical_hash
from janus_spi.dual_transport import JanusDualTransportBroker
from janus_spi.mailbox_transport import TARGET_REPOSITORY


class FakePacketLane:
    def __init__(self):
        self.calls = []

    def send(self, packet, *, token):
        self.calls.append((packet["packet_id"], token))
        if token:
            return {"terminal": "TRANSPORT_SENT_AWAITING_ACK", "receipt_hash": "1" * 64}
        return {"terminal": "TRANSPORT_BLOCKED_NO_CREDENTIAL", "receipt_hash": "2" * 64}


class FakeGrantLane:
    def __init__(self):
        self.calls = []

    def send(self, grant, *, token):
        self.calls.append((grant["grant_id"], token))
        if token:
            return {"terminal": "EXECUTION_TRANSPORT_SENT_AWAITING_RESULT", "receipt_hash": "3" * 64}
        return {"terminal": "EXECUTION_TRANSPORT_BLOCKED_NO_CREDENTIAL", "receipt_hash": "4" * 64}


class FakeMailboxLane:
    def __init__(self, *, emitted=True):
        self.emitted = emitted
        self.calls = []

    def publish(self, obj, *, object_kind, local_github_token):
        self.calls.append((object_kind, obj.get("packet_id") or obj.get("grant_id"), local_github_token))
        if self.emitted and local_github_token:
            return {
                "terminal": "MAILBOX_PUBLISHED_AWAITING_PULL",
                "receipt_hash": "5" * 64,
                "message_hash": "6" * 64,
                "message_path": "/tmp/request.json",
            }
        return {
            "terminal": "MAILBOX_PUBLISH_BLOCKED_NO_LOCAL_GITHUB_TOKEN",
            "receipt_hash": "7" * 64,
            "message_hash": "8" * 64,
            "message_path": "/tmp/request.json",
        }


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


def grant() -> dict:
    row = {
        "schema": "janus.activator.execution_grant.v0.7",
        "created_at": 2.0,
        "parent_grant_hash": None,
        "authenticated_final_receipt_hash": "b" * 64,
        "finalization_id": "ackf-" + "c" * 64,
        "packet_id": packet()["packet_id"],
        "packet_hash": packet()["packet_hash"],
        "target_organ": TARGET_REPOSITORY,
        "operation": "READ_ONLY_ORIENTATION_SNAPSHOT",
        "risk_class": "R0_INTERNAL_READ_ONLY_ORIENTATION",
        "execution_scope": "TARGET_REPOSITORY_LOCAL_READ_ONLY_METADATA",
        "target_execution_authorized": True,
        "repository_write_authorized": False,
        "network_access_authorized": False,
        "model_access_authorized": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "EXECUTION_GRANT_ISSUED_READ_ONLY_ORIENTATION",
        "reasons": ["test grant"],
    }
    row["grant_id"] = "xg-" + canonical_hash({
        "authenticated_final_receipt_hash": row["authenticated_final_receipt_hash"],
        "packet_id": row["packet_id"],
        "packet_hash": row["packet_hash"],
        "target_organ": row["target_organ"],
        "operation": row["operation"],
    })
    row["grant_hash"] = canonical_hash(row)
    return row


def test_dispatch_attempts_both_lanes_and_records_both(tmp_path):
    secret = FakePacketLane()
    mailbox = FakeMailboxLane()
    broker = JanusDualTransportBroker(
        tmp_path,
        packet_lane=secret,
        grant_lane=FakeGrantLane(),
        mailbox_lane=mailbox,
    )
    result = broker.dispatch(packet(), secret_token="secret-token", local_github_token="home-token")
    assert result["terminal"] == "DUAL_PACKET_BOTH_EMITTED"
    assert result["lanes_attempted"] == ["SECRET_PUSH", "CREDENTIALLESS_PULL"]
    assert len(secret.calls) == 1
    assert len(mailbox.calls) == 1
    assert result["secret_push"]["emitted"] is True
    assert result["credentialless_pull"]["emitted"] is True
    assert result["strict_identity_provenance_available"] is True
    assert result["external_effect_authorized"] is False
    assert result["physical_runtime_effect_authorized"] is False
    assert broker.ledger.verify() is True


def test_missing_secret_does_not_select_away_mailbox_lane(tmp_path):
    secret = FakePacketLane()
    mailbox = FakeMailboxLane()
    broker = JanusDualTransportBroker(
        tmp_path,
        packet_lane=secret,
        grant_lane=FakeGrantLane(),
        mailbox_lane=mailbox,
    )
    result = broker.dispatch(packet(), secret_token="", local_github_token="home-token")
    assert result["terminal"] == "DUAL_PACKET_MAILBOX_ONLY_SECRET_DEGRADED"
    assert len(secret.calls) == 1
    assert len(mailbox.calls) == 1
    assert result["at_least_one_lane_emitted"] is True
    assert result["strict_identity_provenance_available"] is False
    assert result["credentialless_identity_proof"] is False


def test_missing_mailbox_local_token_does_not_select_away_secret_lane(tmp_path):
    secret = FakePacketLane()
    mailbox = FakeMailboxLane()
    broker = JanusDualTransportBroker(
        tmp_path,
        packet_lane=secret,
        grant_lane=FakeGrantLane(),
        mailbox_lane=mailbox,
    )
    result = broker.dispatch(packet(), secret_token="secret-token", local_github_token="")
    assert result["terminal"] == "DUAL_PACKET_SECRET_ONLY_MAILBOX_DEGRADED"
    assert len(secret.calls) == 1
    assert len(mailbox.calls) == 1
    assert result["at_least_one_lane_emitted"] is True


def test_execution_grant_is_emitted_on_both_lanes_but_execution_authority_is_not_multiplied(tmp_path):
    grant_lane = FakeGrantLane()
    mailbox = FakeMailboxLane()
    broker = JanusDualTransportBroker(
        tmp_path,
        packet_lane=FakePacketLane(),
        grant_lane=grant_lane,
        mailbox_lane=mailbox,
    )
    result = broker.execute(grant(), secret_token="secret-token", local_github_token="home-token")
    assert result["terminal"] == "DUAL_GRANT_BOTH_EMITTED"
    assert len(grant_lane.calls) == 1
    assert len(mailbox.calls) == 1
    assert result["duplicate_execution_prevention"] == "TARGET_CREATE_ONLY_CLAIM_BY_GRANT_ID"
    assert result["command_authority_granted"] is False
    assert result["claim_authority_granted"] is False
    assert result["scientific_evidence_authority_granted"] is False
    assert result["world_truth_authority_granted"] is False
    assert result["external_effect_authorized"] is False
    assert result["physical_runtime_effect_authorized"] is False
