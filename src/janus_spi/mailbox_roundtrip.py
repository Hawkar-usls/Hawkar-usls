from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .activator import ActivationEvent, JanusActivator, canonical_hash
from .dispatch import JanusDispatchBroker, verify_dispatch_packet
from .dual_transport import JanusDualTransportBroker
from .mailbox_transport import JanusCredentiallessMailboxReader, verify_message, verify_response

TARGET_REPOSITORY = "Hawkar-usls/Janus-Demiurge"
SUCCESS_TERMINAL = "CREDENTIALLESS_PACKET_ROUNDTRIP_OBSERVED_NON_IDENTITY_PROVENANCE"


def verify_delivery_ack(ack: Dict[str, Any], packet: Dict[str, Any]) -> bool:
    if not isinstance(ack, dict) or not verify_dispatch_packet(packet):
        return False
    claimed = str(ack.get("ack_hash") or "")
    if len(claimed) != 64:
        return False
    body = dict(ack)
    body.pop("ack_hash", None)
    return all([
        canonical_hash(body) == claimed,
        ack.get("packet_id") == packet.get("packet_id"),
        ack.get("packet_hash") == packet.get("packet_hash"),
        ack.get("accepted") is True,
        ack.get("execution_authorized") is False,
        ack.get("execution_performed") is False,
        ack.get("claim_authority_granted") is False,
        ack.get("external_effect_authorized") is False,
        ack.get("terminal") == "ACK_ACCEPTED_NO_EXECUTION",
    ])


class JanusCredentiallessPacketRoundtrip:
    """One bounded HOME -> dual lanes -> public mailbox ACK -> HOME witness.

    This is intentionally *not* a launch witness. Credentialless v1.0 proves a
    hash-bound response at the expected public repository origin, but its
    identity_proof remains false until the OIDC/attestation gate is implemented.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path,
        routing_path: str | Path = ".janus/activator/ROUTING_TABLE.json",
        policy_path: str | Path = "config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json",
        reader: JanusCredentiallessMailboxReader | None = None,
        dual_broker: JanusDualTransportBroker | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        poll_interval_seconds: float = 10.0,
        max_wait_seconds: float = 420.0,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.routing_path = Path(routing_path)
        self.policy_path = Path(policy_path)
        self.reader = reader or JanusCredentiallessMailboxReader()
        self.dual = dual_broker or JanusDualTransportBroker(self.state_dir)
        self.sleep_fn = sleep_fn
        self.poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self.max_wait_seconds = max(5.0, float(max_wait_seconds))

    def _result_base(self, *, source_ref: str, event_id: str) -> Dict[str, Any]:
        return {
            "schema": "janus.activator.credentialless_packet_roundtrip.v1.0",
            "created_at": time.time(),
            "source_ref": source_ref,
            "event_id": event_id,
            "activation_receipt_hash": None,
            "packet_id": None,
            "packet_hash": None,
            "dual_transport_receipt_hash": None,
            "secret_lane_terminal": None,
            "secret_lane_emitted": False,
            "credentialless_lane_terminal": None,
            "credentialless_lane_emitted": False,
            "mailbox_message_hash": None,
            "mailbox_response_hash": None,
            "credentialless_ack_observed": False,
            "credentialless_provenance_class": None,
            "credentialless_identity_proof": False,
            "target_execution_observed": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "ROUNDTRIP_INITIALIZING",
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
        result = self._result_base(source_ref=source_ref, event_id=event.event_id)

        activation = JanusActivator(
            state_dir=self.state_dir,
            routing_path=self.routing_path,
            policy_path=self.policy_path,
        ).activate(event)
        result["activation_receipt_hash"] = activation.get("receipt_hash")
        if activation.get("terminal") != "ROUTE_PROPOSED":
            result["terminal"] = "ROUNDTRIP_BLOCKED_ACTIVATION"
            result["reasons"] = ["Fresh stimulus did not produce a declared HOME route proposal."]
            return result

        dispatch = JanusDispatchBroker(self.state_dir).dispatch(
            activation,
            target_organ=TARGET_REPOSITORY,
        )
        if dispatch.get("terminal") not in {"AUTHORIZED_INTERNAL_HANDOFF", "ALREADY_EMITTED"}:
            result["terminal"] = "ROUNDTRIP_BLOCKED_DISPATCH"
            result["reasons"] = [f"Dispatch broker terminal: {dispatch.get('terminal')}."]
            return result

        packet_path = Path(str(dispatch.get("packet_path") or ""))
        if not packet_path.is_file():
            result["terminal"] = "ROUNDTRIP_BLOCKED_PACKET_MISSING"
            result["reasons"] = ["Dispatch broker did not leave a readable deterministic packet."]
            return result
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        if not verify_dispatch_packet(packet):
            result["terminal"] = "ROUNDTRIP_BLOCKED_PACKET_INTEGRITY"
            result["reasons"] = ["Deterministic dispatch packet failed integrity verification."]
            return result
        result["packet_id"] = packet["packet_id"]
        result["packet_hash"] = packet["packet_hash"]

        dual = self.dual.dispatch(
            packet,
            secret_token=secret_dispatch_token,
            local_github_token=local_github_token,
        )
        result["dual_transport_receipt_hash"] = dual.get("receipt_hash")
        result["secret_lane_terminal"] = dual.get("secret_push", {}).get("terminal")
        result["secret_lane_emitted"] = dual.get("secret_push", {}).get("emitted") is True
        result["credentialless_lane_terminal"] = dual.get("credentialless_pull", {}).get("terminal")
        result["credentialless_lane_emitted"] = dual.get("credentialless_pull", {}).get("emitted") is True
        result["mailbox_message_hash"] = dual.get("credentialless_pull", {}).get("message_hash")

        if result["credentialless_lane_emitted"] is not True:
            result["terminal"] = "ROUNDTRIP_BLOCKED_MAILBOX_NOT_EMITTED"
            result["reasons"] = [
                "Both transport lanes were attempted, but the credentialless mailbox lane did not emit a request."
            ]
            return result

        message_path = Path(str(dual.get("credentialless_pull", {}).get("message_path") or ""))
        if not message_path.is_file():
            result["terminal"] = "ROUNDTRIP_BLOCKED_LOCAL_REQUEST_MISSING"
            result["reasons"] = ["Exact mailbox request was not preserved locally for response binding."]
            return result
        request = json.loads(message_path.read_text(encoding="utf-8"))
        if not verify_message(request) or request.get("message_hash") != result["mailbox_message_hash"]:
            result["terminal"] = "ROUNDTRIP_BLOCKED_LOCAL_REQUEST_INTEGRITY"
            result["reasons"] = ["Locally preserved mailbox request failed deterministic integrity binding."]
            return result

        deadline = time.monotonic() + self.max_wait_seconds
        response: Optional[Dict[str, Any]] = None
        while time.monotonic() < deadline:
            response = self.reader.read(request)
            if response is not None:
                break
            self.sleep_fn(self.poll_interval_seconds)

        if response is None:
            result["terminal"] = "ROUNDTRIP_ACK_WAIT_UNRESOLVED"
            result["reasons"] = [
                "No matching credentialless mailbox ACK was observed before the bounded deadline; silence is not negative evidence and the packet is not republished."
            ]
            return result
        if not verify_response(response, request):
            result["terminal"] = "ROUNDTRIP_BLOCKED_RESPONSE_INTEGRITY"
            result["reasons"] = ["Mailbox response failed request/authority/provenance binding."]
            return result

        ack = response.get("payload", {}).get("ack") if isinstance(response.get("payload"), dict) else None
        if not isinstance(ack, dict) or not verify_delivery_ack(ack, packet):
            result["terminal"] = "ROUNDTRIP_BLOCKED_ACK_INTEGRITY"
            result["reasons"] = ["Target delivery ACK failed packet binding or no-execution authority ceiling."]
            return result

        result["mailbox_response_hash"] = response.get("response_hash")
        result["credentialless_ack_observed"] = True
        result["credentialless_provenance_class"] = response.get("provenance_class")
        result["credentialless_identity_proof"] = response.get("identity_proof") is True
        result["target_execution_observed"] = False

        # v1.0 success explicitly requires identity_proof to remain false. A
        # future OIDC/attestation version will have a different success terminal.
        if response.get("identity_proof") is not False:
            result["terminal"] = "ROUNDTRIP_BLOCKED_UNDECLARED_IDENTITY_ELEVATION"
            result["reasons"] = ["Credentialless v1.0 response attempted to exceed its frozen provenance ceiling."]
            return result

        result["terminal"] = SUCCESS_TERMINAL
        result["reasons"] = [
            "HOME generated a genuine sealed activation route and deterministic dispatch packet.",
            "The dual broker attempted both secret push and credentialless pull lanes for the same packet.",
            "Janus-Demiurge observed the public HOME mailbox request and returned a hash-bound no-execution ACK through its own mailbox branch.",
            "HOME bound the response to the exact locally preserved request and packet.",
            "Credentialless provenance remains non-identity v1.0 evidence and grants no P12, claim, scientific, world-truth, external-effect or physical-runtime authority.",
        ]
        return result


__all__ = ["JanusCredentiallessPacketRoundtrip", "SUCCESS_TERMINAL", "verify_delivery_ack"]
