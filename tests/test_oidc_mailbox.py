from __future__ import annotations

import base64
import json
import urllib.error

from janus_spi.activator import canonical_hash
from janus_spi.oidc_mailbox import (
    HOME_REPOSITORY,
    HOME_REPOSITORY_ID,
    HOME_WORKFLOW_REFS,
    IDENTITY_SCHEMA,
    ISSUER,
    OWNER,
    OWNER_ID,
    PROVENANCE_CLASS,
    TARGET_REPOSITORY,
    TARGET_REPOSITORY_ID,
    TARGET_WORKFLOW_REFS,
    JanusOIDCMailboxReader,
    JanusOIDCMailboxTransport,
    build_request_envelope,
    request_audience,
    request_github_oidc_token,
    response_audience,
    verify_no_execution_ack,
    verify_request_envelope,
    verify_signed_response,
)


class Response:
    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def read(self):
        return self._body


def packet() -> dict:
    row = {
        "schema": "janus.activator.dispatch_packet.v0.3",
        "created_at": 10.0,
        "activation_id": "act-oidc-test",
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


def claims(*, target: bool, audience: str, repository_id: str | None = None) -> dict:
    return {
        "iss": ISSUER,
        "aud": audience,
        "iat": 100,
        "nbf": 100,
        "exp": 700,
        "repository": TARGET_REPOSITORY if target else HOME_REPOSITORY,
        "repository_id": repository_id or (TARGET_REPOSITORY_ID if target else HOME_REPOSITORY_ID),
        "repository_owner": OWNER,
        "repository_owner_id": OWNER_ID,
        "ref": "refs/heads/main",
        "event_name": "schedule" if target else "push",
        "workflow_ref": next(iter(TARGET_WORKFLOW_REFS if target else HOME_WORKFLOW_REFS)),
        "workflow_sha": ("2" if target else "1") * 40,
        "run_id": "2" if target else "1",
        "run_attempt": "1",
    }


def decoder(token: str, audience: str) -> dict:
    if token.startswith("home."):
        return claims(target=False, audience=audience)
    if token.startswith("target."):
        return claims(target=True, audience=audience)
    raise ValueError("unknown fake token")


def home_issuer(audience: str) -> dict:
    return {
        "schema": IDENTITY_SCHEMA,
        "provider": "GITHUB_ACTIONS_OIDC",
        "role": "HOME_REQUEST_SOURCE",
        "audience": audience,
        "bound_at": 150.0,
        "jwt": "home.fake.jwt",
    }


def target_issuer(audience: str) -> dict:
    return {
        "schema": IDENTITY_SCHEMA,
        "provider": "GITHUB_ACTIONS_OIDC",
        "role": "DEMIURGE_RESPONSE_SOURCE",
        "audience": audience,
        "bound_at": 160.0,
        "jwt": "target.fake.jwt",
    }


def oidc_request() -> dict:
    obj = packet()
    return build_request_envelope(obj, home_issuer(request_audience("DISPATCH_PACKET", obj["packet_id"], obj["packet_hash"])))


def signed_response(request: dict, *, target_repository_id: str | None = None) -> dict:
    ack = {
        "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
        "created_at": 155.0,
        "packet_id": request["object_id"],
        "packet_hash": request["object_hash"],
        "accepted": True,
        "terminal": "ACK_ACCEPTED_NO_EXECUTION",
        "reasons": ["test"],
        "execution_authorized": False,
        "execution_performed": False,
        "claim_authority_granted": False,
        "external_effect_authorized": False,
    }
    ack["ack_hash"] = canonical_hash(ack)
    source_verification = verify_request_envelope(request, decoder=decoder)
    core = {
        "schema": "janus.demiurge.mailbox_response_core.v1.1",
        "created_at": 155.0,
        "source_repository": TARGET_REPOSITORY,
        "target_repository": HOME_REPOSITORY,
        "target_head_sha": "9" * 40,
        "request_message_hash": request["message_hash"],
        "request_object_kind": "DISPATCH_PACKET",
        "request_object_id": request["object_id"],
        "request_object_hash": request["object_hash"],
        "response_kind": "DELIVERY_ACK",
        "payload": {"ack": ack},
        "source_identity_verified": True,
        "source_identity_verification_hash": source_verification["verification_hash"],
        "source_identity_verification": source_verification,
        "target_execution_authorized": False,
        "target_execution_performed": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "OIDC_MAILBOX_DELIVERY_ACK_CORE_READY",
    }
    core_hash = canonical_hash(core)
    audience = response_audience(request["message_hash"], core_hash)
    identity = target_issuer(audience)
    response = {
        "schema": "janus.demiurge.mailbox_response.v1.1",
        "response_core": core,
        "response_core_hash": core_hash,
        "target_identity": identity,
        "provenance_class": PROVENANCE_CLASS,
        "identity_proof": True,
    }
    response["response_hash"] = canonical_hash(response)
    return response


def rebind_packet(request: dict, mutated: dict) -> dict:
    body = dict(mutated)
    body.pop("packet_hash", None)
    mutated["packet_hash"] = canonical_hash(body)
    request["object"] = mutated
    request["object_id"] = mutated["packet_id"]
    request["object_hash"] = mutated["packet_hash"]
    request["source_identity"]["audience"] = request_audience(
        "DISPATCH_PACKET", mutated["packet_id"], mutated["packet_hash"]
    )
    body = dict(request)
    body.pop("message_hash", None)
    request["message_hash"] = canonical_hash(body)
    return request


def resign_response(request: dict, response: dict) -> dict:
    core_hash = canonical_hash(response["response_core"])
    response["response_core_hash"] = core_hash
    response["target_identity"]["audience"] = response_audience(request["message_hash"], core_hash)
    body = dict(response)
    body.pop("response_hash", None)
    response["response_hash"] = canonical_hash(body)
    return response


def test_oidc_request_url_rejects_non_github_actions_host_before_bearer_send():
    calls = []
    try:
        request_github_oidc_token(
            "urn:janus:test",
            request_url="https://evil.example/token",
            request_token="sensitive",
            opener=lambda request, timeout=20.0: calls.append(request) or Response(),
        )
    except ValueError as exc:
        assert "HOST_REJECTED" in str(exc)
    else:
        raise AssertionError("non-GitHub OIDC host accepted")
    assert calls == []


def test_request_explicit_world_truth_escalation_is_rejected():
    request = oidc_request()
    request["world_truth_authority_granted"] = True
    request["message_hash"] = canonical_hash({k: v for k, v in request.items() if k != "message_hash"})
    verified = verify_request_envelope(request, decoder=decoder)
    assert verified["ok"] is False
    assert verified["terminal"] == "OIDC_REQUEST_AUTHORITY_OR_KIND_REJECTED"


def test_well_hashed_embedded_authority_escalation_is_rejected_before_publish():
    for field in ("external_effect_authorized", "command_authority_granted"):
        request = oidc_request()
        mutated = dict(request["object"])
        mutated[field] = True
        request = rebind_packet(request, mutated)

        verified = verify_request_envelope(request, decoder=decoder)
        assert verified["ok"] is False
        assert verified["terminal"] == "OIDC_REQUEST_PACKET_SCOPE_REJECTED"

        try:
            build_request_envelope(mutated, home_issuer(request["source_identity"]["audience"]))
        except ValueError as exc:
            assert "INVALID_DISPATCH_PACKET" in str(exc)
        else:
            raise AssertionError("authority-bearing embedded packet reached OIDC publication")


def test_publisher_uses_local_repo_token_and_preserves_exact_verified_request(tmp_path):
    calls = []

    def opener(request, timeout=20.0):
        calls.append(request)
        if request.get_method() == "GET":
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
        return Response(status=201)

    transport = JanusOIDCMailboxTransport(
        tmp_path,
        opener=opener,
        decoder=decoder,
        identity_issuer=home_issuer,
    )
    result = transport.publish(packet(), local_github_token="home-local-token")
    assert result["terminal"] == "OIDC_MAILBOX_PUBLISHED_AWAITING_SIGNED_ACK"
    assert result["identity_proof"] is True
    assert result["cross_repository_credential_used"] is False
    assert result["message_hash"]
    assert any(request.get_method() == "PUT" and request.headers.get("Authorization") == "Bearer home-local-token" for request in calls)
    saved = json.load(open(result["message_path"], encoding="utf-8"))
    assert verify_request_envelope(saved, decoder=decoder)["ok"] is True


def test_existing_valid_oidc_packet_is_reused_without_new_identity_issue(tmp_path):
    existing = oidc_request()
    issue_calls = []

    def opener(request, timeout=20.0):
        if request.get_method() == "GET":
            return Response(body=(json.dumps(existing) + "\n").encode("utf-8"))
        raise AssertionError("existing valid request must not be rewritten")

    transport = JanusOIDCMailboxTransport(
        tmp_path,
        opener=opener,
        decoder=decoder,
        identity_issuer=lambda audience: issue_calls.append(audience) or home_issuer(audience),
    )
    result = transport.publish(existing["object"], local_github_token="home-local-token")
    assert result["terminal"] == "OIDC_MAILBOX_ALREADY_PUBLISHED_VERIFIED"
    assert issue_calls == []
    assert result["message_hash"] == existing["message_hash"]


def test_reader_accepts_only_target_signed_exact_response(tmp_path):
    request = oidc_request()
    response = signed_response(request)
    reader = JanusOIDCMailboxReader(
        opener=lambda req, timeout=15.0: Response(body=(json.dumps(response) + "\n").encode("utf-8")),
        decoder=decoder,
    )
    observed = reader.read_verified(request)
    assert observed is not None
    row, verification = observed
    assert row["identity_proof"] is True
    assert verification["ok"] is True
    assert verification["identity_proof"] is True


def test_target_must_attest_exact_source_identity_verification():
    request = oidc_request()
    response = signed_response(request)
    response["response_core"]["source_identity_verified"] = False
    response = resign_response(request, response)

    verified = verify_signed_response(response, request_envelope=request, decoder=decoder)
    assert verified["ok"] is False
    assert verified["terminal"] == "OIDC_RESPONSE_SOURCE_IDENTITY_ATTESTATION_REJECTED"
    assert verify_no_execution_ack(response, request) is False


def test_target_source_verification_hash_must_bind_embedded_result():
    request = oidc_request()
    response = signed_response(request)
    response["response_core"]["source_identity_verification_hash"] = "f" * 64
    response = resign_response(request, response)

    verified = verify_signed_response(response, request_envelope=request, decoder=decoder)
    assert verified["ok"] is False
    assert verified["terminal"] == "OIDC_RESPONSE_SOURCE_IDENTITY_ATTESTATION_REJECTED"


def test_wrong_target_repository_id_rejects_signed_response():
    request = oidc_request()
    response = signed_response(request)

    def wrong_decoder(token: str, audience: str) -> dict:
        if token.startswith("home."):
            return claims(target=False, audience=audience)
        return claims(target=True, audience=audience, repository_id="999")

    verified = verify_signed_response(response, request_envelope=request, decoder=wrong_decoder)
    assert verified["ok"] is False
    assert verified["terminal"] == "OIDC_REPOSITORY_IDENTITY_REJECTED"


def test_unsigned_or_legacy_target_ack_cannot_satisfy_oidc_reader():
    request = oidc_request()
    legacy = {
        "schema": "janus.demiurge.mailbox_response.v1.0",
        "identity_proof": False,
    }
    reader = JanusOIDCMailboxReader(
        opener=lambda req, timeout=15.0: Response(body=(json.dumps(legacy) + "\n").encode("utf-8")),
        decoder=decoder,
    )
    try:
        reader.read_verified(request)
    except ValueError as exc:
        assert "TARGET_RESPONSE_NOT_VERIFIED" in str(exc)
    else:
        raise AssertionError("legacy ACK unexpectedly satisfied OIDC reader")
