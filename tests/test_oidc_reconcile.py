from __future__ import annotations

from janus_spi.oidc_reconcile import (
    BLOCKED_TERMINAL,
    PENDING_TERMINAL,
    SUCCESS_TERMINAL,
    reconcile_requests,
)


def req(object_id: str = "dsp-" + "a" * 64, message_hash: str = "b" * 64):
    return {"object_id": object_id, "message_hash": message_hash}


def verified_request(_request):
    return {"ok": True, "identity_proof": True, "terminal": "TEST_SOURCE_VERIFIED"}


class PendingReader:
    def read_verified(self, request_envelope):
        return None


class VerifiedReader:
    def read_verified(self, request_envelope):
        response = {"response_hash": "c" * 64, "response_core_hash": "d" * 64}
        verification = {"ok": True, "identity_proof": True, "verification_hash": "e" * 64}
        return response, verification


class RejectingReader:
    def read_verified(self, request_envelope):
        raise ValueError("bad target signature")


def test_missing_ack_is_pending_not_negative_evidence():
    result = reconcile_requests([req()], reader=PendingReader(), request_verifier=verified_request)
    assert result["terminal"] == PENDING_TERMINAL
    assert result["verified_source_request_count"] == 1
    assert result["pending_count"] == 1
    assert result["verified_ack_count"] == 0
    assert result["target_execution_observed"] is False
    assert result["p12_execution_authority_granted"] is False
    assert result["external_effect_authorized"] is False


def test_later_target_ack_promotes_only_bidirectional_identity_reconciliation():
    result = reconcile_requests([req()], reader=VerifiedReader(), request_verifier=verified_request)
    assert result["terminal"] == SUCCESS_TERMINAL
    assert result["verified_ack_count"] == 1
    assert result["pending_count"] == 0
    assert result["verified"][0]["response_hash"] == "c" * 64
    assert result["command_authority_granted"] is False
    assert result["claim_authority_granted"] is False
    assert result["world_truth_authority_granted"] is False
    assert result["is_launch_witness"] is False


def test_observed_invalid_target_response_fails_closed():
    result = reconcile_requests([req()], reader=RejectingReader(), request_verifier=verified_request)
    assert result["terminal"] == BLOCKED_TERMINAL
    assert result["rejected_response_count"] == 1


def test_duplicate_request_object_id_fails_closed():
    result = reconcile_requests([req(), req(message_hash="f" * 64)], reader=PendingReader(), request_verifier=verified_request)
    assert result["terminal"] == BLOCKED_TERMINAL
    assert result["invalid_count"] == 1
