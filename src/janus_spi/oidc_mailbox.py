from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .activator import canonical_hash
from .dispatch import (
    READ_ONLY_EFFECT_SCOPE,
    READ_ONLY_OPERATION,
    READ_ONLY_RISK_CLASS,
    verify_dispatch_packet,
)

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = "https://token.actions.githubusercontent.com/.well-known/jwks"
IDENTITY_SCHEMA = "janus.activator.github_actions_oidc_identity.v1.1"
REQUEST_SCHEMA = "janus.activator.mailbox_message.v1.1"
RESPONSE_SCHEMA = "janus.demiurge.mailbox_response.v1.1"
PROVENANCE_CLASS = "GITHUB_ACTIONS_OIDC_BIDIRECTIONAL_OBJECT_BOUND_IDENTITY"

HOME_REPOSITORY = "Hawkar-usls/Hawkar-usls"
HOME_REPOSITORY_ID = "1328314567"
TARGET_REPOSITORY = "Hawkar-usls/Janus-Demiurge"
TARGET_REPOSITORY_ID = "1188744620"
OWNER = "Hawkar-usls"
OWNER_ID = "242020399"
MAIN_REF = "refs/heads/main"
HOME_BRANCH = "janus/transport-mailbox"
TARGET_BRANCH = "janus/activator-mailbox"
HOME_OUTBOX = ".janus/mailbox/outbox"
TARGET_INBOX = ".janus/mailbox/inbox"
HOME_WORKFLOW_REFS = {
    "Hawkar-usls/Hawkar-usls/.github/workflows/janus-oidc-mailbox-roundtrip.yml@refs/heads/main",
}
TARGET_WORKFLOW_REFS = {
    "Hawkar-usls/Janus-Demiurge/.github/workflows/janus-activator-credentialless-mailbox.yml@refs/heads/main",
}
HOME_EVENTS = {"push", "workflow_dispatch"}
TARGET_EVENTS = {"push", "schedule", "workflow_dispatch"}
PACKET_ID_RE = re.compile(r"^dsp-[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

DISPATCH_PACKET_SCHEMA = "janus.activator.dispatch_packet.v0.3"
DISPATCH_DELIVERY_TERMINALS = {"AUTHORIZED_INTERNAL_HANDOFF", "ALREADY_EMITTED"}
DISPATCH_PACKET_KEYS = {
    "schema", "packet_id", "created_at", "activation_id", "activation_receipt_hash",
    "route_match", "target_organ", "operation", "risk_class", "required_gates",
    "dispatch_authorized", "external_effect_authorized", "claim_authority_granted",
    "command_authority_granted", "effect_scope", "delivery_terminal", "packet_hash",
}

Decoder = Callable[[str, str], Dict[str, Any]]
IdentityIssuer = Callable[[str], Dict[str, Any]]


def request_audience(object_kind: str, object_id: str, object_hash: str) -> str:
    if object_kind != "DISPATCH_PACKET":
        raise ValueError("OIDC_V11_PACKET_ACK_STAGE_ONLY")
    if PACKET_ID_RE.fullmatch(str(object_id)) is None or HASH_RE.fullmatch(str(object_hash)) is None:
        raise ValueError("OIDC_REQUEST_OBJECT_ID_OR_HASH_INVALID")
    return f"urn:janus:mailbox-request:v1.1:{object_kind}:{object_id}:{object_hash}"


def response_audience(request_message_hash: str, response_core_hash: str) -> str:
    if HASH_RE.fullmatch(str(request_message_hash)) is None or HASH_RE.fullmatch(str(response_core_hash)) is None:
        raise ValueError("OIDC_RESPONSE_HASH_BINDING_INVALID")
    return f"urn:janus:mailbox-response:v1.1:{request_message_hash}:{response_core_hash}"


def _oidc_request(url: str, request_token: str, audience: str) -> urllib.request.Request:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or not parts.hostname.endswith(".actions.githubusercontent.com"):
        raise ValueError("GITHUB_ACTIONS_OIDC_REQUEST_URL_HOST_REJECTED")
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("audience", audience))
    bound_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))
    return urllib.request.Request(
        bound_url,
        headers={
            "Authorization": f"Bearer {request_token}",
            "Accept": "application/json",
            "User-Agent": "JANUS-HOME-OIDC-Mailbox/1.1",
        },
    )


def request_github_oidc_token(
    audience: str,
    *,
    request_url: str | None = None,
    request_token: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    url = str(request_url if request_url is not None else os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")).strip()
    token = str(request_token if request_token is not None else os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")).strip()
    if not url or not token:
        raise RuntimeError("GITHUB_ACTIONS_OIDC_REQUEST_ENV_MISSING")
    response = opener(_oidc_request(url, token, audience), timeout=20.0)
    value = json.loads(response.read().decode("utf-8"))
    jwt_value = value.get("value") if isinstance(value, dict) else None
    if not isinstance(jwt_value, str) or jwt_value.count(".") != 2:
        raise RuntimeError("GITHUB_ACTIONS_OIDC_RESPONSE_INVALID")
    return jwt_value


def issue_identity_assertion(
    audience: str,
    *,
    role: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
    now_fn: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    jwt_value = request_github_oidc_token(audience, opener=opener)
    return {
        "schema": IDENTITY_SCHEMA,
        "provider": "GITHUB_ACTIONS_OIDC",
        "role": role,
        "audience": audience,
        "bound_at": float(now_fn()),
        "jwt": jwt_value,
    }


_jwk_client = None


def _decode_signed_github_jwt(token: str, audience: str) -> Dict[str, Any]:
    import jwt  # type: ignore

    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(JWKS_URL)
    key = _jwk_client.get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=audience,
        issuer=ISSUER,
        options={"verify_exp": False, "verify_nbf": False, "verify_iat": False},
    )
    if not isinstance(claims, dict):
        raise ValueError("OIDC_CLAIMS_NOT_OBJECT")
    return claims


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _audience_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    return isinstance(value, list) and expected in value


def _failure(terminal: str, reason: str) -> Dict[str, Any]:
    return {"ok": False, "identity_proof": False, "terminal": terminal, "reason": reason}


def _strict_authority_false(row: Mapping[str, Any]) -> bool:
    return all(
        row.get(field) is False
        for field in (
            "command_authority_granted",
            "claim_authority_granted",
            "scientific_evidence_authority_granted",
            "world_truth_authority_granted",
            "external_effect_authorized",
            "physical_runtime_effect_authorized",
        )
    )


def _admitted_dispatch_packet(packet: Mapping[str, Any]) -> bool:
    """Freeze the full v0.3 contract at the OIDC authority boundary.

    ``verify_dispatch_packet`` establishes deterministic integrity, not whether
    the hash-bound object requests an admitted operation or authority. Identity
    must never promote a well-hashed, authority-bearing packet.
    """

    if set(packet) != DISPATCH_PACKET_KEYS:
        return False
    created_at = packet.get("created_at")
    required_gates = packet.get("required_gates")
    if (
        packet.get("schema") != DISPATCH_PACKET_SCHEMA
        or PACKET_ID_RE.fullmatch(str(packet.get("packet_id") or "")) is None
        or HASH_RE.fullmatch(str(packet.get("packet_hash") or "")) is None
        or HASH_RE.fullmatch(str(packet.get("activation_receipt_hash") or "")) is None
        or not isinstance(created_at, (int, float))
        or isinstance(created_at, bool)
        or created_at < 0
        or not isinstance(packet.get("activation_id"), str)
        or not str(packet.get("activation_id"))
        or not isinstance(packet.get("route_match"), str)
        or not str(packet.get("route_match"))
        or packet.get("target_organ") != TARGET_REPOSITORY
        or packet.get("operation") != READ_ONLY_OPERATION
        or packet.get("risk_class") != READ_ONLY_RISK_CLASS
        or packet.get("effect_scope") != READ_ONLY_EFFECT_SCOPE
        or packet.get("delivery_terminal") not in DISPATCH_DELIVERY_TERMINALS
        or packet.get("dispatch_authorized") is not True
        or packet.get("external_effect_authorized") is not False
        or packet.get("claim_authority_granted") is not False
        or packet.get("command_authority_granted") is not False
        or not isinstance(required_gates, list)
        or any(not isinstance(gate, str) or not gate for gate in required_gates)
        or len(set(required_gates)) != len(required_gates)
    ):
        return False
    return verify_dispatch_packet(dict(packet))


def _verification_hash_matches(row: Mapping[str, Any]) -> bool:
    claimed = str(row.get("verification_hash") or "")
    body = dict(row)
    body.pop("verification_hash", None)
    return HASH_RE.fullmatch(claimed) is not None and canonical_hash(body) == claimed


def _source_identity_attestation_matches(core: Mapping[str, Any], request: Mapping[str, Any]) -> bool:
    verification = core.get("source_identity_verification")
    if not isinstance(verification, dict):
        return False
    identity = verification.get("identity_verification")
    return all((
        core.get("source_identity_verified") is True,
        core.get("source_identity_verification_hash") == verification.get("verification_hash"),
        _verification_hash_matches(verification),
        verification.get("ok") is True,
        verification.get("identity_proof") is True,
        verification.get("terminal") == "OIDC_REQUEST_VERIFIED_HOME_OBJECT_BOUND_IDENTITY",
        verification.get("message_hash") == request.get("message_hash"),
        verification.get("object_id") == request.get("object_id"),
        verification.get("object_hash") == request.get("object_hash"),
        isinstance(identity, dict),
        isinstance(identity, dict) and identity.get("ok") is True,
        isinstance(identity, dict) and identity.get("identity_proof") is True,
        isinstance(identity, dict) and _verification_hash_matches(identity),
    ))


def verify_identity_assertion(
    assertion: Dict[str, Any],
    *,
    expected_audience: str,
    expected_role: str,
    expected_repository: str,
    expected_repository_id: str,
    allowed_workflow_refs: Iterable[str],
    allowed_events: Iterable[str],
    decoder: Decoder | None = None,
) -> Dict[str, Any]:
    if not isinstance(assertion, dict):
        return _failure("OIDC_ASSERTION_MISSING", "Identity assertion is not an object.")
    if assertion.get("schema") != IDENTITY_SCHEMA or assertion.get("provider") != "GITHUB_ACTIONS_OIDC":
        return _failure("OIDC_ASSERTION_SCHEMA_REJECTED", "Identity assertion schema/provider mismatch.")
    if assertion.get("role") != expected_role:
        return _failure("OIDC_ROLE_REJECTED", "Identity role mismatch.")
    if assertion.get("audience") != expected_audience:
        return _failure("OIDC_AUDIENCE_REJECTED", "Assertion audience does not bind the exact object.")
    bound_at = _as_float(assertion.get("bound_at"))
    token = assertion.get("jwt")
    if bound_at is None or not isinstance(token, str) or token.count(".") != 2:
        return _failure("OIDC_ASSERTION_MALFORMED", "bound_at or JWT is malformed.")
    try:
        claims = (decoder or _decode_signed_github_jwt)(token, expected_audience)
    except Exception as exc:
        return _failure("OIDC_SIGNATURE_ISSUER_AUDIENCE_REJECTED", f"JWT verification failed with {type(exc).__name__}.")
    required = (
        "iss", "aud", "iat", "nbf", "exp", "repository", "repository_id",
        "repository_owner", "repository_owner_id", "ref", "event_name",
        "workflow_ref", "workflow_sha", "run_id", "run_attempt",
    )
    missing = [key for key in required if key not in claims]
    if missing:
        return _failure("OIDC_REQUIRED_CLAIMS_MISSING", "Missing required claims: " + ",".join(missing))
    if claims.get("iss") != ISSUER or not _audience_contains(claims.get("aud"), expected_audience):
        return _failure("OIDC_ISSUER_OR_AUDIENCE_REJECTED", "Issuer or audience mismatch.")
    if str(claims.get("repository")) != expected_repository or str(claims.get("repository_id")) != expected_repository_id:
        return _failure("OIDC_REPOSITORY_IDENTITY_REJECTED", "Repository name or immutable repository ID mismatch.")
    if str(claims.get("repository_owner")) != OWNER or str(claims.get("repository_owner_id")) != OWNER_ID:
        return _failure("OIDC_OWNER_IDENTITY_REJECTED", "Repository owner name or immutable owner ID mismatch.")
    if str(claims.get("ref")) != MAIN_REF:
        return _failure("OIDC_REF_REJECTED", "OIDC identity did not originate from refs/heads/main.")
    if str(claims.get("workflow_ref")) not in set(allowed_workflow_refs):
        return _failure("OIDC_WORKFLOW_REF_REJECTED", "Workflow reference is not admitted.")
    if str(claims.get("event_name")) not in set(allowed_events):
        return _failure("OIDC_EVENT_REJECTED", "Workflow event is not admitted.")
    if SHA_RE.fullmatch(str(claims.get("workflow_sha"))) is None:
        return _failure("OIDC_WORKFLOW_SHA_REJECTED", "workflow_sha is not 40-hex.")
    iat, nbf, exp = (_as_float(claims.get(key)) for key in ("iat", "nbf", "exp"))
    if iat is None or nbf is None or exp is None or not (iat <= exp and nbf <= exp):
        return _failure("OIDC_TIME_CLAIMS_REJECTED", "Token time claims are malformed.")
    if exp - iat <= 0 or exp - iat > 900:
        return _failure("OIDC_TOKEN_LIFETIME_REJECTED", "Token lifetime exceeds frozen attestation bound.")
    if not (max(iat, nbf) <= bound_at <= exp):
        return _failure("OIDC_BOUND_AT_REJECTED", "bound_at is outside signed token window.")
    public_claims = {
        key: claims.get(key)
        for key in (
            "repository", "repository_id", "repository_owner", "repository_owner_id",
            "ref", "event_name", "workflow_ref", "workflow_sha", "run_id", "run_attempt",
            "iat", "nbf", "exp",
        )
    }
    result = {
        "ok": True,
        "identity_proof": True,
        "terminal": "OIDC_IDENTITY_VERIFIED_OBJECT_BOUND_HISTORICAL_ATTESTATION",
        "provider": "GITHUB_ACTIONS_OIDC",
        "role": expected_role,
        "audience": expected_audience,
        "bound_at": bound_at,
        "claims": public_claims,
        "subject_exact_match_required": False,
        "jwt_is_bearer_authorization": False,
    }
    result["verification_hash"] = canonical_hash(result)
    return result


def verify_home_identity(assertion: Dict[str, Any], audience: str, *, decoder: Decoder | None = None) -> Dict[str, Any]:
    return verify_identity_assertion(
        assertion,
        expected_audience=audience,
        expected_role="HOME_REQUEST_SOURCE",
        expected_repository=HOME_REPOSITORY,
        expected_repository_id=HOME_REPOSITORY_ID,
        allowed_workflow_refs=HOME_WORKFLOW_REFS,
        allowed_events=HOME_EVENTS,
        decoder=decoder,
    )


def verify_target_identity(assertion: Dict[str, Any], audience: str, *, decoder: Decoder | None = None) -> Dict[str, Any]:
    return verify_identity_assertion(
        assertion,
        expected_audience=audience,
        expected_role="DEMIURGE_RESPONSE_SOURCE",
        expected_repository=TARGET_REPOSITORY,
        expected_repository_id=TARGET_REPOSITORY_ID,
        allowed_workflow_refs=TARGET_WORKFLOW_REFS,
        allowed_events=TARGET_EVENTS,
        decoder=decoder,
    )


def build_request_envelope(packet: Dict[str, Any], source_identity: Dict[str, Any]) -> Dict[str, Any]:
    if not _admitted_dispatch_packet(packet):
        raise ValueError("OIDC_MAILBOX_INVALID_DISPATCH_PACKET")
    audience = request_audience("DISPATCH_PACKET", str(packet["packet_id"]), str(packet["packet_hash"]))
    if source_identity.get("audience") != audience or source_identity.get("role") != "HOME_REQUEST_SOURCE":
        raise ValueError("OIDC_SOURCE_IDENTITY_NOT_BOUND_TO_PACKET")
    row = {
        "schema": REQUEST_SCHEMA,
        "created_at": packet.get("created_at"),
        "source_repository": HOME_REPOSITORY,
        "target_repository": TARGET_REPOSITORY,
        "object_kind": "DISPATCH_PACKET",
        "object_id": packet["packet_id"],
        "object_hash": packet["packet_hash"],
        "object": packet,
        "source_identity": source_identity,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    row["message_hash"] = canonical_hash(row)
    return row


def verify_request_envelope(envelope: Dict[str, Any], *, decoder: Decoder | None = None) -> Dict[str, Any]:
    if not isinstance(envelope, dict) or envelope.get("schema") != REQUEST_SCHEMA:
        return _failure("OIDC_REQUEST_SCHEMA_REJECTED", "Request schema mismatch.")
    claimed = str(envelope.get("message_hash") or "")
    body = dict(envelope)
    body.pop("message_hash", None)
    if HASH_RE.fullmatch(claimed) is None or canonical_hash(body) != claimed:
        return _failure("OIDC_REQUEST_HASH_REJECTED", "Request hash mismatch.")
    if envelope.get("source_repository") != HOME_REPOSITORY or envelope.get("target_repository") != TARGET_REPOSITORY:
        return _failure("OIDC_REQUEST_REPOSITORY_REJECTED", "Request repository binding mismatch.")
    if envelope.get("object_kind") != "DISPATCH_PACKET" or not _strict_authority_false(envelope):
        return _failure("OIDC_REQUEST_AUTHORITY_OR_KIND_REJECTED", "Only authority-bounded packets are admitted.")
    packet = envelope.get("object")
    if not isinstance(packet, dict) or not _admitted_dispatch_packet(packet):
        return _failure(
            "OIDC_REQUEST_PACKET_SCOPE_REJECTED",
            "Packet integrity, schema, target, operation, scope, or embedded authority ceiling failed.",
        )
    if envelope.get("object_id") != packet.get("packet_id") or envelope.get("object_hash") != packet.get("packet_hash"):
        return _failure("OIDC_REQUEST_OBJECT_BINDING_REJECTED", "Envelope object binding mismatch.")
    audience = request_audience("DISPATCH_PACKET", str(packet["packet_id"]), str(packet["packet_hash"]))
    identity = verify_home_identity(envelope.get("source_identity"), audience, decoder=decoder)
    if identity.get("ok") is not True:
        return identity
    result = {
        "ok": True,
        "identity_proof": True,
        "terminal": "OIDC_REQUEST_VERIFIED_HOME_OBJECT_BOUND_IDENTITY",
        "message_hash": claimed,
        "object_id": packet["packet_id"],
        "object_hash": packet["packet_hash"],
        "identity_verification": identity,
    }
    result["verification_hash"] = canonical_hash(result)
    return result


def verify_signed_response(
    response: Dict[str, Any],
    *,
    request_envelope: Dict[str, Any],
    decoder: Decoder | None = None,
) -> Dict[str, Any]:
    req = verify_request_envelope(request_envelope, decoder=decoder)
    if req.get("ok") is not True:
        return _failure("OIDC_RESPONSE_REQUEST_NOT_VERIFIED", "Exact source request did not verify.")
    if not isinstance(response, dict) or response.get("schema") != RESPONSE_SCHEMA:
        return _failure("OIDC_RESPONSE_SCHEMA_REJECTED", "Response schema mismatch.")
    claimed = str(response.get("response_hash") or "")
    body = dict(response)
    body.pop("response_hash", None)
    if HASH_RE.fullmatch(claimed) is None or canonical_hash(body) != claimed:
        return _failure("OIDC_RESPONSE_HASH_REJECTED", "Response outer hash mismatch.")
    core = response.get("response_core")
    core_hash = str(response.get("response_core_hash") or "")
    if not isinstance(core, dict) or HASH_RE.fullmatch(core_hash) is None or canonical_hash(core) != core_hash:
        return _failure("OIDC_RESPONSE_CORE_HASH_REJECTED", "Response core hash mismatch.")
    if response.get("provenance_class") != PROVENANCE_CLASS or response.get("identity_proof") is not True:
        return _failure("OIDC_RESPONSE_PROVENANCE_REJECTED", "Response did not declare bidirectional OIDC provenance.")
    if core.get("request_message_hash") != request_envelope.get("message_hash"):
        return _failure("OIDC_RESPONSE_REQUEST_BINDING_REJECTED", "Response does not bind exact request hash.")
    if core.get("request_object_kind") != "DISPATCH_PACKET" or core.get("request_object_id") != request_envelope.get("object_id") or core.get("request_object_hash") != request_envelope.get("object_hash"):
        return _failure("OIDC_RESPONSE_OBJECT_BINDING_REJECTED", "Response object binding mismatch.")
    if not _source_identity_attestation_matches(core, request_envelope):
        return _failure(
            "OIDC_RESPONSE_SOURCE_IDENTITY_ATTESTATION_REJECTED",
            "Target did not attest a hash-valid source verification bound to the exact request and object.",
        )
    if not _strict_authority_false(core) or core.get("target_execution_authorized") is not False or core.get("target_execution_performed") is not False:
        return _failure("OIDC_RESPONSE_AUTHORITY_REJECTED", "Response exceeds packet/ACK authority ceiling.")
    audience = response_audience(str(request_envelope["message_hash"]), core_hash)
    identity = verify_target_identity(response.get("target_identity"), audience, decoder=decoder)
    if identity.get("ok") is not True:
        return identity
    result = {
        "ok": True,
        "identity_proof": True,
        "terminal": "OIDC_RESPONSE_VERIFIED_BIDIRECTIONAL_OBJECT_BOUND_IDENTITY",
        "response_hash": claimed,
        "response_core_hash": core_hash,
        "target_identity_verification": identity,
    }
    result["verification_hash"] = canonical_hash(result)
    return result


def verify_no_execution_ack(response: Dict[str, Any], request: Dict[str, Any]) -> bool:
    core = response.get("response_core") if isinstance(response, dict) else None
    if not isinstance(core, dict) or not _source_identity_attestation_matches(core, request):
        return False
    payload = core.get("payload")
    ack = payload.get("ack") if isinstance(payload, dict) else None
    if not isinstance(ack, dict):
        return False
    claimed = str(ack.get("ack_hash") or "")
    body = dict(ack)
    body.pop("ack_hash", None)
    return all([
        HASH_RE.fullmatch(claimed) is not None,
        canonical_hash(body) == claimed,
        ack.get("packet_id") == request.get("object_id"),
        ack.get("packet_hash") == request.get("object_hash"),
        ack.get("accepted") is True,
        ack.get("terminal") == "ACK_ACCEPTED_NO_EXECUTION",
        ack.get("execution_authorized") is False,
        ack.get("execution_performed") is False,
        ack.get("claim_authority_granted") is False,
        ack.get("external_effect_authorized") is False,
    ])


class JanusOIDCMailboxTransport:
    def __init__(
        self,
        state_dir: str | Path,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        decoder: Decoder | None = None,
        identity_issuer: IdentityIssuer | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.local_outbox = self.state_dir / "oidc_mailbox_outbox"
        self.local_outbox.mkdir(parents=True, exist_ok=True)
        self.opener = opener
        self.decoder = decoder
        self.identity_issuer = identity_issuer

    @staticmethod
    def filename(packet: Dict[str, Any]) -> str:
        return f"{packet['packet_id']}.oidc-packet.json"

    @staticmethod
    def _raw_url(filename: str) -> str:
        return f"https://raw.githubusercontent.com/{HOME_REPOSITORY}/{HOME_BRANCH}/{HOME_OUTBOX}/{filename}"

    @staticmethod
    def _api_url(filename: str) -> str:
        path = urllib.parse.quote(f"{HOME_OUTBOX}/{filename}", safe="/")
        return f"https://api.github.com/repos/{HOME_REPOSITORY}/contents/{path}"

    def _read_existing(self, filename: str) -> Dict[str, Any] | None:
        try:
            response = self.opener(urllib.request.Request(self._raw_url(filename), headers={"User-Agent": "JANUS-HOME-OIDC-Mailbox/1.1"}), timeout=15.0)
            return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _preserve(self, filename: str, envelope: Dict[str, Any]) -> Path:
        path = self.local_outbox / filename
        text = json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != envelope:
                raise RuntimeError("OIDC_LOCAL_REQUEST_CONFLICT")
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def publish(self, packet: Dict[str, Any], *, local_github_token: str) -> Dict[str, Any]:
        if not _admitted_dispatch_packet(packet):
            raise ValueError("OIDC_MAILBOX_INVALID_DISPATCH_PACKET")
        filename = self.filename(packet)
        existing = self._read_existing(filename)
        if existing is not None:
            verified = verify_request_envelope(existing, decoder=self.decoder)
            if verified.get("ok") is not True or existing.get("object_hash") != packet.get("packet_hash"):
                return {
                    "terminal": "OIDC_MAILBOX_EXISTING_CONFLICT",
                    "published": False,
                    "identity_proof": False,
                }
            path = self._preserve(filename, existing)
            return {
                "terminal": "OIDC_MAILBOX_ALREADY_PUBLISHED_VERIFIED",
                "published": True,
                "identity_proof": True,
                "message_hash": existing["message_hash"],
                "message_path": str(path),
                "object_id": packet["packet_id"],
                "object_hash": packet["packet_hash"],
                "cross_repository_credential_used": False,
            }
        if not str(local_github_token).strip():
            return {
                "terminal": "OIDC_MAILBOX_BLOCKED_NO_LOCAL_GITHUB_TOKEN",
                "published": False,
                "identity_proof": False,
            }

        audience = request_audience("DISPATCH_PACKET", str(packet["packet_id"]), str(packet["packet_hash"]))
        issuer = self.identity_issuer or (
            lambda aud: issue_identity_assertion(aud, role="HOME_REQUEST_SOURCE", opener=self.opener)
        )
        source_identity = issuer(audience)
        envelope = build_request_envelope(packet, source_identity)
        verified = verify_request_envelope(envelope, decoder=self.decoder)
        if verified.get("ok") is not True:
            return {
                "terminal": "OIDC_MAILBOX_SELF_IDENTITY_VERIFICATION_FAILED",
                "published": False,
                "identity_proof": False,
                "verification_terminal": verified.get("terminal"),
            }
        path = self._preserve(filename, envelope)
        encoded = base64.b64encode((json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")).decode("ascii")
        payload = json.dumps({
            "message": f"Activator OIDC mailbox publish {packet['packet_id']}",
            "content": encoded,
            "branch": HOME_BRANCH,
        }, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self._api_url(filename),
            data=payload,
            method="PUT",
            headers={
                "Authorization": f"Bearer {local_github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "JANUS-HOME-OIDC-Mailbox/1.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            response = self.opener(request, timeout=20.0)
            status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
        except urllib.error.HTTPError as exc:
            if exc.code in {409, 422}:
                reread = self._read_existing(filename)
                if reread == envelope and verify_request_envelope(reread, decoder=self.decoder).get("ok") is True:
                    status = 200
                else:
                    return {
                        "terminal": "OIDC_MAILBOX_PUBLISH_CONFLICT",
                        "published": False,
                        "identity_proof": False,
                        "http_status": exc.code,
                    }
            else:
                return {
                    "terminal": "OIDC_MAILBOX_PUBLISH_OUTCOME_UNDETERMINED",
                    "published": False,
                    "identity_proof": True,
                    "message_hash": envelope["message_hash"],
                    "message_path": str(path),
                    "http_status": exc.code,
                }
        return {
            "terminal": "OIDC_MAILBOX_PUBLISHED_AWAITING_SIGNED_ACK" if status in {200, 201} else "OIDC_MAILBOX_PUBLISH_OUTCOME_UNDETERMINED",
            "published": status in {200, 201},
            "identity_proof": True,
            "message_hash": envelope["message_hash"],
            "message_path": str(path),
            "object_id": packet["packet_id"],
            "object_hash": packet["packet_hash"],
            "cross_repository_credential_used": False,
            "http_status": status,
        }


class JanusOIDCMailboxReader:
    def __init__(self, *, opener: Callable[..., Any] = urllib.request.urlopen, decoder: Decoder | None = None) -> None:
        self.opener = opener
        self.decoder = decoder

    @staticmethod
    def response_url(request_envelope: Dict[str, Any]) -> str:
        object_id = str(request_envelope.get("object_id") or "")
        if PACKET_ID_RE.fullmatch(object_id) is None:
            raise ValueError("OIDC_RESPONSE_OBJECT_ID_INVALID")
        return f"https://raw.githubusercontent.com/{TARGET_REPOSITORY}/{TARGET_BRANCH}/{TARGET_INBOX}/{object_id}.oidc-ack.json"

    def read_verified(self, request_envelope: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]] | None:
        source = verify_request_envelope(request_envelope, decoder=self.decoder)
        if source.get("ok") is not True:
            raise ValueError("OIDC_LOCAL_REQUEST_NOT_VERIFIED")
        try:
            response = self.opener(urllib.request.Request(self.response_url(request_envelope), headers={"User-Agent": "JANUS-HOME-OIDC-Mailbox/1.1"}), timeout=15.0)
            row = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        verification = verify_signed_response(row, request_envelope=request_envelope, decoder=self.decoder)
        if verification.get("ok") is not True or not verify_no_execution_ack(row, request_envelope):
            raise ValueError("OIDC_TARGET_RESPONSE_NOT_VERIFIED")
        return row, verification


__all__ = [
    "IDENTITY_SCHEMA", "REQUEST_SCHEMA", "RESPONSE_SCHEMA", "PROVENANCE_CLASS",
    "request_audience", "response_audience", "request_github_oidc_token",
    "issue_identity_assertion", "verify_identity_assertion", "verify_home_identity",
    "verify_target_identity", "build_request_envelope", "verify_request_envelope",
    "verify_signed_response", "verify_no_execution_ack", "JanusOIDCMailboxTransport",
    "JanusOIDCMailboxReader",
]
