from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Protocol

from .oidc_mailbox import JanusOIDCMailboxReader, verify_request_envelope

PENDING_TERMINAL = "OIDC_ASYNC_RECONCILIATION_PENDING_TARGET_POLL"
SUCCESS_TERMINAL = "OIDC_ASYNC_RECONCILIATION_VERIFIED_NO_EXECUTION"
EMPTY_TERMINAL = "OIDC_ASYNC_RECONCILIATION_NO_REQUESTS"
BLOCKED_TERMINAL = "OIDC_ASYNC_RECONCILIATION_BLOCKED_INVALID_EVIDENCE"


class Reader(Protocol):
    def read_verified(self, request_envelope: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]] | None: ...


RequestVerifier = Callable[[Dict[str, Any]], Dict[str, Any]]


def _base() -> Dict[str, Any]:
    return {
        "schema": "janus.activator.oidc_async_reconciliation.v1",
        "request_count": 0,
        "verified_source_request_count": 0,
        "verified_ack_count": 0,
        "pending_count": 0,
        "invalid_count": 0,
        "rejected_response_count": 0,
        "verified": [],
        "pending": [],
        "invalid": [],
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "target_execution_observed": False,
        "p12_execution_authority_granted": False,
        "is_launch_witness": False,
        "terminal": EMPTY_TERMINAL,
        "reasons": [],
    }


def reconcile_requests(
    requests: Iterable[Dict[str, Any]],
    *,
    reader: Reader | None = None,
    request_verifier: RequestVerifier = verify_request_envelope,
) -> Dict[str, Any]:
    """Reconcile already-published HOME OIDC requests without creating new authority.

    A missing target ACK is a pending transport observation, never negative
    cryptographic evidence.  An existing but unverifiable response is different:
    the production reader raises and this function fails closed.
    """
    result = _base()
    mailbox_reader = reader or JanusOIDCMailboxReader()
    seen_object_ids: set[str] = set()

    for request in requests:
        result["request_count"] += 1
        object_id = str(request.get("object_id") or "")
        message_hash = str(request.get("message_hash") or "")

        if object_id in seen_object_ids:
            result["invalid_count"] += 1
            result["invalid"].append(
                {"object_id": object_id, "message_hash": message_hash, "reason": "DUPLICATE_OBJECT_ID"}
            )
            continue
        seen_object_ids.add(object_id)

        verification = request_verifier(request)
        if verification.get("ok") is not True or verification.get("identity_proof") is not True:
            result["invalid_count"] += 1
            result["invalid"].append(
                {
                    "object_id": object_id,
                    "message_hash": message_hash,
                    "reason": str(verification.get("terminal") or "REQUEST_NOT_VERIFIED"),
                }
            )
            continue

        result["verified_source_request_count"] += 1
        try:
            observed = mailbox_reader.read_verified(request)
        except (ValueError, RuntimeError) as exc:
            result["rejected_response_count"] += 1
            result["invalid"].append(
                {
                    "object_id": object_id,
                    "message_hash": message_hash,
                    "reason": f"TARGET_RESPONSE_REJECTED:{type(exc).__name__}:{exc}",
                }
            )
            continue

        if observed is None:
            result["pending_count"] += 1
            result["pending"].append({"object_id": object_id, "message_hash": message_hash})
            continue

        response, response_verification = observed
        if response_verification.get("ok") is not True or response_verification.get("identity_proof") is not True:
            # Defensive fail-closed check even though JanusOIDCMailboxReader already enforces it.
            result["rejected_response_count"] += 1
            result["invalid"].append(
                {
                    "object_id": object_id,
                    "message_hash": message_hash,
                    "reason": "TARGET_RESPONSE_READER_CONTRACT_VIOLATION",
                }
            )
            continue

        result["verified_ack_count"] += 1
        result["verified"].append(
            {
                "object_id": object_id,
                "message_hash": message_hash,
                "response_hash": response.get("response_hash"),
                "response_core_hash": response.get("response_core_hash"),
                "verification_hash": response_verification.get("verification_hash"),
            }
        )

    if result["invalid_count"] or result["rejected_response_count"]:
        result["terminal"] = BLOCKED_TERMINAL
        result["reasons"] = [
            "At least one published request or observed target response failed verification; reconciliation fails closed."
        ]
    elif result["request_count"] == 0:
        result["terminal"] = EMPTY_TERMINAL
        result["reasons"] = ["No HOME OIDC mailbox requests were present in the inspected snapshot."]
    elif result["verified_ack_count"] > 0:
        result["terminal"] = SUCCESS_TERMINAL
        result["reasons"] = [
            "One or more previously published HOME requests now have exact target-signed no-execution ACKs.",
            "Requests without an ACK remain pending and do not count as negative evidence.",
            "P12, execution, launch and every higher authority remain false.",
        ]
    else:
        result["terminal"] = PENDING_TERMINAL
        result["reasons"] = [
            "Verified HOME requests exist, but no matching target-signed ACK is visible yet; silence is not negative evidence."
        ]
    return result


__all__ = [
    "BLOCKED_TERMINAL",
    "EMPTY_TERMINAL",
    "PENDING_TERMINAL",
    "SUCCESS_TERMINAL",
    "reconcile_requests",
]
