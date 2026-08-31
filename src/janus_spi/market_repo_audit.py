from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .repo_audit_service import verify_request

PACKET_SCHEMA = "janus.machine_market.home_repo_audit_packet.v1"
HOME_RESPONSE_SCHEMA = "janus.machine_market.home_repo_audit_response.v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    text = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_packet(packet: Mapping[str, Any]) -> bool:
    if not isinstance(packet, Mapping):
        return False
    value = dict(packet)
    claimed = str(value.pop("packet_hash", ""))
    if len(claimed) != 64 or digest(value) != claimed:
        return False
    if value.get("schema") != PACKET_SCHEMA or value.get("sku") != "JANUS.REPO_AUDIT":
        return False
    if value.get("market_repository") != "Hawkar-usls/JANUS-MACHINE-MARKET":
        return False
    if value.get("home_repository") != "Hawkar-usls/Hawkar-usls":
        return False
    if value.get("commerce_mode") not in {"ZERO_PRICE_SHADOW", "PAID_ERC20"}:
        return False
    request = value.get("service_request")
    if not isinstance(request, Mapping) or not verify_request(request):
        return False
    grant = value.get("purchase_grant") or {}
    if grant.get("sku") != "JANUS.REPO_AUDIT" or grant.get("status") != "PURCHASE_ELIGIBLE":
        return False
    if grant.get("execution_authority_granted") is not False:
        return False
    entitlement = grant.get("service_entitlement") or {}
    if entitlement.get("service") != "JANUS.REPO_AUDIT" or entitlement.get("read_only") is not True:
        return False
    if entitlement.get("repository") != request.get("repository") or entitlement.get("ref") != request.get("ref"):
        return False
    if entitlement.get("execute_repository_code") is not False:
        return False
    if value.get("command_authority_granted") is not False or value.get("external_effect_authorized") is not False:
        return False
    if value.get("repository_write_authorized") is not False or value.get("execute_repository_code") is not False:
        return False
    if value.get("purchase_grant_hash") != digest(grant):
        return False
    if value.get("service_request_hash") != request.get("request_hash"):
        return False
    if value.get("commerce_mode") == "ZERO_PRICE_SHADOW":
        if value.get("money_enabled") is not False or value.get("payment_reference") is not None:
            return False
    else:
        if value.get("money_enabled") is not True or not str(value.get("payment_reference") or "").strip():
            return False
    return True


def build_home_response(
    *,
    packet: Mapping[str, Any],
    home_receipt: Mapping[str, Any],
    source_binding: Mapping[str, Any],
    replayed: bool,
) -> dict[str, Any]:
    if not verify_packet(packet):
        raise ValueError("MARKET_REPO_AUDIT_PACKET_INVALID")
    if home_receipt.get("schema") != "janus.market_service.repo_audit_home_receipt.v1":
        raise ValueError("MARKET_REPO_AUDIT_HOME_RECEIPT_INVALID")
    if home_receipt.get("request_id") != packet["service_request"]["request_id"]:
        raise ValueError("MARKET_REPO_AUDIT_HOME_REQUEST_MISMATCH")
    body: dict[str, Any] = {
        "schema": HOME_RESPONSE_SCHEMA,
        "sku": "JANUS.REPO_AUDIT",
        "packet_id": packet.get("packet_id"),
        "packet_hash": packet.get("packet_hash"),
        "purchase_id": packet["purchase_grant"]["purchase_id"],
        "purchase_grant_hash": packet["purchase_grant_hash"],
        "service_request_id": packet["service_request"]["request_id"],
        "service_request_hash": packet["service_request_hash"],
        "commerce_mode": packet["commerce_mode"],
        "money_enabled": packet["money_enabled"],
        "payment_reference": packet.get("payment_reference"),
        "resident_uuid": home_receipt.get("resident_uuid"),
        "model_digest": home_receipt.get("model_digest"),
        "file_fabric_digest": home_receipt.get("file_fabric_digest"),
        "runtime_receipt_hash": home_receipt.get("runtime_receipt_hash"),
        "home_service_receipt_hash": home_receipt.get("home_receipt_hash"),
        "audit_result_hash": home_receipt.get("audit_result_hash"),
        "audit_result": home_receipt.get("audit_result"),
        "same_resident_uuid": home_receipt.get("same_resident_uuid"),
        "return_home_verified": home_receipt.get("return_home_verified"),
        "replayed": bool(replayed),
        "source_binding": dict(source_binding),
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "repository_write_authorized": False,
        "repository_code_executed": False,
        "security_certification_granted": False,
        "legal_opinion_granted": False,
        "laws": [
            "MARKET IS EXTERNAL NERVE NOT JANUS ROOT",
            "REPOSITORY CONTENT != COMMAND",
            "AUDIT != SECURITY CERTIFICATION",
            "AUDIT != LEGAL OPINION",
            "DELIVERY != AUTHORITY",
            "EXACT RETRY != SECOND COGNITION"
        ],
    }
    body["home_response_hash"] = digest(body)
    return body


def verify_home_response(response: Mapping[str, Any]) -> bool:
    if not isinstance(response, Mapping):
        return False
    value = dict(response)
    claimed = str(value.pop("home_response_hash", ""))
    if len(claimed) != 64 or digest(value) != claimed:
        return False
    return all([
        value.get("schema") == HOME_RESPONSE_SCHEMA,
        value.get("sku") == "JANUS.REPO_AUDIT",
        bool(str(value.get("resident_uuid") or "").strip()),
        len(str(value.get("model_digest") or "")) == 64,
        len(str(value.get("file_fabric_digest") or "")) == 64,
        len(str(value.get("home_service_receipt_hash") or "")) == 64,
        len(str(value.get("audit_result_hash") or "")) == 64,
        value.get("same_resident_uuid") is True,
        value.get("return_home_verified") is True,
        value.get("command_authority_granted") is False,
        value.get("external_effect_authorized") is False,
        value.get("repository_write_authorized") is False,
        value.get("repository_code_executed") is False,
        value.get("security_certification_granted") is False,
        value.get("legal_opinion_granted") is False,
    ])


__all__ = [
    "HOME_RESPONSE_SCHEMA",
    "PACKET_SCHEMA",
    "build_home_response",
    "digest",
    "verify_home_response",
    "verify_packet",
]
