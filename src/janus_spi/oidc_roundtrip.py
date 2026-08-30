from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol

from .activator import ActivationEvent, JanusActivator
from .dispatch import JanusDispatchBroker, verify_dispatch_packet
from .oidc_mailbox import JanusOIDCMailboxReader, JanusOIDCMailboxTransport, verify_request_envelope
from .transport import JanusTransportBroker

TARGET_REPOSITORY = "Hawkar-usls/Janus-Demiurge"
SUCCESS_TERMINAL = "OIDC_BIDIRECTIONAL_PACKET_ROUNDTRIP_VERIFIED_NO_EXECUTION"


class SecretPacketLane(Protocol):
    def send(self, packet: Dict[str, Any], *, token: str) -> Dict[str, Any]: ...


class OIDCPublisher(Protocol):
    def publish(self, packet: Dict[str, Any], *, local_github_token: str) -> Dict[str, Any]: ...


class OIDCReader(Protocol):
    def read_verified(self, request_envelope: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]] | None: ...


def _secret_emitted(receipt: Dict[str, Any]) -> bool:
    return receipt.get("terminal") in {"TRANSPORT_SENT_AWAITING_ACK", "TRANSPORT_OUTCOME_UNDETERMINED"}


class JanusOIDCPacketRoundtrip:
    """Prove both-lane attempt and bidirectional OIDC packet/ACK identity.

    This witness intentionally ends before P12. It proves transport identity,
    not execution authority, launch, consciousness, AGI, or scientific truth.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path,
        routing_path: str | Path = ".janus/activator/ROUTING_TABLE.json",
        policy_path: str | Path = "config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json",
        secret_lane: SecretPacketLane | None = None,
        oidc_publisher: OIDCPublisher | None = None,
        oidc_reader: OIDCReader | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        poll_interval_seconds: float = 10.0,
        max_wait_seconds: float = 660.0,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.routing_path = Path(routing_path)
        self.policy_path = Path(policy_path)
        self.secret_lane = secret_lane or JanusTransportBroker(self.state_dir)
        self.oidc_publisher = oidc_publisher or JanusOIDCMailboxTransport(self.state_dir)
        self.oidc_reader = oidc_reader or JanusOIDCMailboxReader()
        self.sleep_fn = sleep_fn
        self.poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self.max_wait_seconds = max(5.0, float(max_wait_seconds))

    @staticmethod
    def _base(source_ref: str, event_id: str) -> Dict[str, Any]:
        return {
            "schema": "janus.activator.oidc_packet_roundtrip.v1.1",
            "created_at": time.time(),
            "source_ref": source_ref,
            "event_id": event_id,
            "activation_receipt_hash": None,
            "packet_id": None,
            "packet_hash": None,
            "lanes_attempted": ["SECRET_PUSH", "OIDC_CREDENTIALLESS_PULL"],
            "secret_lane_attempted": True,
            "secret_lane_emitted": False,
            "secret_lane_terminal": None,
            "oidc_lane_attempted": True,
            "oidc_lane_emitted": False,
            "oidc_lane_terminal": None,
            "oidc_request_message_hash": None,
            "oidc_source_identity_verified": False,
            "oidc_response_hash": None,
            "oidc_response_core_hash": None,
            "oidc_target_identity_verified": False,
            "bidirectional_identity_proof": False,
            "target_execution_observed": False,
            "p12_execution_authority_granted": False,
            "is_launch_witness": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "OIDC_ROUNDTRIP_INITIALIZING",
            "reasons": [],
        }

    def run(
        self,
        *,
        source_ref: str,
        payload: Any,
        secret_dispatch_token: str,
        local_github_token: str,
    ) -> Dict[str, Any]:
        event = ActivationEvent.build(
            source_kind="EXPLICIT_EXTERNAL_WORKFLOW_TRIGGER",
            source_ref=source_ref,
            payload=payload,
            classifications=["research_or_anomaly_investigation"],
            fresh=True,
            self_generated=False,
            command_authority=False,
            effect_authorized=False,
        )
        result = self._base(source_ref, event.event_id)

        activation = JanusActivator(
            state_dir=self.state_dir,
            routing_path=self.routing_path,
            policy_path=self.policy_path,
        ).activate(event)
        result["activation_receipt_hash"] = activation.get("receipt_hash")
        if activation.get("terminal") != "ROUTE_PROPOSED":
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_ACTIVATION"
            result["reasons"] = ["Fresh stimulus did not produce a declared HOME route proposal."]
            return result

        dispatch = JanusDispatchBroker(self.state_dir).dispatch(activation, target_organ=TARGET_REPOSITORY)
        if dispatch.get("terminal") not in {"AUTHORIZED_INTERNAL_HANDOFF", "ALREADY_EMITTED"}:
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_DISPATCH"
            result["reasons"] = [f"Dispatch broker terminal: {dispatch.get('terminal')}."]
            return result
        packet_path = Path(str(dispatch.get("packet_path") or ""))
        if not packet_path.is_file():
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_PACKET_MISSING"
            return result
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        if not verify_dispatch_packet(packet):
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_PACKET_INTEGRITY"
            return result
        result["packet_id"] = packet["packet_id"]
        result["packet_hash"] = packet["packet_hash"]

        # JANUS does not select a lane. Both are attempted for the same sealed packet.
        secret = self.secret_lane.send(packet, token=secret_dispatch_token)
        result["secret_lane_terminal"] = secret.get("terminal")
        result["secret_lane_emitted"] = _secret_emitted(secret)

        oidc = self.oidc_publisher.publish(packet, local_github_token=local_github_token)
        result["oidc_lane_terminal"] = oidc.get("terminal")
        result["oidc_lane_emitted"] = oidc.get("published") is True
        result["oidc_request_message_hash"] = oidc.get("message_hash")
        if result["oidc_lane_emitted"] is not True or oidc.get("identity_proof") is not True:
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_REQUEST_NOT_PUBLISHED_WITH_IDENTITY"
            result["reasons"] = ["Both lanes were attempted, but OIDC mailbox request did not publish with verified HOME identity."]
            return result

        message_path = Path(str(oidc.get("message_path") or ""))
        if not message_path.is_file():
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_LOCAL_REQUEST_MISSING"
            return result
        request = json.loads(message_path.read_text(encoding="utf-8"))
        request_verification = verify_request_envelope(request)
        if request_verification.get("ok") is not True:
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_LOCAL_SOURCE_IDENTITY"
            result["reasons"] = [f"Local exact request verification terminal: {request_verification.get('terminal')}"]
            return result
        result["oidc_source_identity_verified"] = True

        deadline = time.monotonic() + self.max_wait_seconds
        observed: Optional[tuple[Dict[str, Any], Dict[str, Any]]] = None
        while time.monotonic() < deadline:
            observed = self.oidc_reader.read_verified(request)
            if observed is not None:
                break
            self.sleep_fn(self.poll_interval_seconds)
        if observed is None:
            result["terminal"] = "OIDC_ROUNDTRIP_ACK_WAIT_UNRESOLVED"
            result["reasons"] = ["No matching target-signed OIDC ACK observed before bounded deadline; silence is not negative evidence and request is not republished."]
            return result

        response, verification = observed
        result["oidc_response_hash"] = response.get("response_hash")
        result["oidc_response_core_hash"] = response.get("response_core_hash")
        result["oidc_target_identity_verified"] = verification.get("identity_proof") is True
        result["bidirectional_identity_proof"] = result["oidc_source_identity_verified"] and result["oidc_target_identity_verified"]
        if result["bidirectional_identity_proof"] is not True:
            result["terminal"] = "OIDC_ROUNDTRIP_BLOCKED_BIDIRECTIONAL_IDENTITY"
            return result

        result["terminal"] = SUCCESS_TERMINAL
        result["reasons"] = [
            "HOME produced a genuine Activator route and deterministic read-only dispatch packet.",
            "The same packet attempted both secret push and OIDC credentialless pull lanes.",
            "HOME GitHub Actions identity was cryptographically verified and object-bound to the exact packet audience.",
            "Janus-Demiurge independently verified HOME identity, emitted a no-execution ACK, and bound its own GitHub Actions identity to the exact response core.",
            "HOME independently verified the target signature, immutable repository identity, workflow/ref claims, exact request/response hashes and no-execution authority ceiling.",
            "This is a transport identity witness only: P12, launch, command, scientific, world-truth, external-effect and physical-runtime authority remain false.",
        ]
        return result


__all__ = ["JanusOIDCPacketRoundtrip", "SUCCESS_TERMINAL"]
