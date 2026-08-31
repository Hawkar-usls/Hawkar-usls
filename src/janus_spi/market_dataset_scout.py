from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .dataset_scout_service import verify_request, verify_result

PACKET_SCHEMA = "janus.machine_market.home_dataset_scout_packet.v1"
HOME_RESPONSE_SCHEMA = "janus.machine_market.home_dataset_scout_response.v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    text = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_packet(packet: Mapping[str, Any]) -> bool:
    try:
        value = dict(packet); claimed = str(value.pop("packet_hash", ""))
        if len(claimed) != 64 or digest(value) != claimed:
            return False
        if value.get("schema") != PACKET_SCHEMA or value.get("sku") != "JANUS.DATASET_SCOUT":
            return False
        if value.get("market_repository") != "Hawkar-usls/JANUS-MACHINE-MARKET" or value.get("home_repository") != "Hawkar-usls/Hawkar-usls":
            return False
        if value.get("commerce_mode") != "ZERO_PRICE_SHADOW" or value.get("money_enabled") is not False or value.get("payment_reference") is not None:
            return False
        request = value.get("service_request")
        if not isinstance(request, Mapping) or not verify_request(request):
            return False
        grant = value.get("purchase_grant") or {}; entitlement = grant.get("service_entitlement") or {}
        if grant.get("sku") != "JANUS.DATASET_SCOUT" or grant.get("status") != "PURCHASE_ELIGIBLE" or grant.get("execution_authority_granted") is not False:
            return False
        if entitlement.get("service") != "JANUS.DATASET_SCOUT" or entitlement.get("request_id") != request.get("request_id"):
            return False
        if entitlement.get("bounds") != request.get("bounds") or entitlement.get("read_only") is not True:
            return False
        if entitlement.get("dataset_payload_download_authorized") is not False or entitlement.get("redistribution_authority_granted") is not False:
            return False
        for key in ("command_authority_granted", "external_effect_authorized", "dataset_payload_download_authorized", "redistribution_authority_granted"):
            if value.get(key) is not False:
                return False
        return value.get("purchase_grant_hash") == digest(grant) and value.get("service_request_hash") == request.get("request_hash")
    except Exception:
        return False


def build_home_response(*, packet: Mapping[str, Any], home_receipt: Mapping[str, Any], source_binding: Mapping[str, Any], replayed: bool) -> dict[str, Any]:
    if not verify_packet(packet):
        raise ValueError("MARKET_DATASET_SCOUT_PACKET_INVALID")
    if home_receipt.get("schema") != "janus.market_service.dataset_scout_home_receipt.v1":
        raise ValueError("MARKET_DATASET_SCOUT_HOME_RECEIPT_INVALID")
    if home_receipt.get("request_id") != packet["service_request"]["request_id"]:
        raise ValueError("MARKET_DATASET_SCOUT_HOME_REQUEST_MISMATCH")
    result = home_receipt.get("dataset_scout_result")
    if not isinstance(result, Mapping) or not verify_result(result, request=packet["service_request"]):
        raise ValueError("MARKET_DATASET_SCOUT_RESULT_INVALID")
    body: dict[str, Any] = {
        "schema": HOME_RESPONSE_SCHEMA,
        "sku": "JANUS.DATASET_SCOUT",
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
        "dataset_scout_result_hash": home_receipt.get("dataset_scout_result_hash"),
        "dataset_scout_result": result,
        "same_resident_uuid": home_receipt.get("same_resident_uuid"),
        "return_home_verified": home_receipt.get("return_home_verified"),
        "replayed": bool(replayed),
        "source_binding": dict(source_binding),
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "dataset_payload_downloaded": False,
        "redistribution_authority_granted": False,
        "license_authority_granted": False,
        "laws": [
            "MARKET IS EXTERNAL NERVE NOT JANUS ROOT",
            "DATASET METADATA != DATASET PAYLOAD",
            "DATASET DISCOVERY != REDISTRIBUTION AUTHORITY",
            "LICENSE OBSERVATION != LICENSE AUTHORITY",
            "DELIVERY != AUTHORITY",
            "EXACT RETRY != SECOND COGNITION",
        ],
    }
    body["home_response_hash"] = digest(body)
    return body


def verify_home_response(response: Mapping[str, Any]) -> bool:
    try:
        value = dict(response); claimed = str(value.pop("home_response_hash", ""))
        if len(claimed) != 64 or digest(value) != claimed:
            return False
        result = value.get("dataset_scout_result") or {}
        authority = result.get("authority") or {}
        return all([
            value.get("schema") == HOME_RESPONSE_SCHEMA,
            value.get("sku") == "JANUS.DATASET_SCOUT",
            bool(str(value.get("resident_uuid") or "").strip()),
            len(str(value.get("model_digest") or "")) == 64,
            len(str(value.get("file_fabric_digest") or "")) == 64,
            len(str(value.get("home_service_receipt_hash") or "")) == 64,
            len(str(value.get("dataset_scout_result_hash") or "")) == 64,
            result.get("result_hash") == value.get("dataset_scout_result_hash"),
            value.get("same_resident_uuid") is True,
            value.get("return_home_verified") is True,
            value.get("command_authority_granted") is False,
            value.get("external_effect_authorized") is False,
            value.get("dataset_payload_downloaded") is False,
            value.get("redistribution_authority_granted") is False,
            value.get("license_authority_granted") is False,
            authority.get("dataset_payload_downloaded") is False,
            authority.get("redistribution_authority_granted") is False,
        ])
    except Exception:
        return False


__all__ = ["HOME_RESPONSE_SCHEMA", "PACKET_SCHEMA", "build_home_response", "digest", "verify_home_response", "verify_packet"]
