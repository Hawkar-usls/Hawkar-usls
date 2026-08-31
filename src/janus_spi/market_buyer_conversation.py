from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Mapping

from .activator import canonical_hash
from .terminal_conversation import build_terminal_message, verify_terminal_message, verify_terminal_response

PACKET_SCHEMA = "janus.machine_market.home_buyer_query_packet.v1"
PAID_PACKET_SCHEMA = "janus.machine_market.home_paid_buyer_query_packet.v1"
QUERY_SCHEMA = "janus.machine_market.buyer_query.v1"
GRANT_SCHEMA = "janus.machine_market.purchase_grant.v1"
PAYMENT_RECEIPT_SCHEMA = "janus.machine_market.payment_receipt.v1"
HOME_RESPONSE_SCHEMA = "janus.home.market_buyer_query_response.v1"
BUYER_RECEIPT_SCHEMA = "janus.machine_market.buyer_query_receipt.v1"
MARKET_REPOSITORY = "Hawkar-usls/JANUS-MACHINE-MARKET"
HOME_REPOSITORY = "Hawkar-usls/Hawkar-usls"
MACHINE_BUYER_CLASSIFICATION = "machine_buyer_read_only_conversation"
MACHINE_BUYER_SOURCE_KIND = "MARKET_BUYER_CONVERSATION"
USDT_ETHEREUM_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
MARKET_MERCHANT_ADDRESS = "0x7149081aea54fbef57effeb52a5a966b81cc03a0"


class MarketBuyerConversationError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MarketBuyerConversationError(code)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso_to_timestamp(value: str) -> float:
    text = str(value or "").strip()
    _require(bool(text), "MARKET_BUYER_CREATED_AT_REQUIRED")
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception as exc:  # noqa: BLE001
        raise MarketBuyerConversationError("MARKET_BUYER_CREATED_AT_INVALID") from exc


def _verify_paid_payment(value: Mapping[str, Any], grant: Mapping[str, Any]) -> bool:
    payment = value.get("payment_receipt")
    if not isinstance(payment, Mapping):
        return False
    payment = dict(payment)
    if payment.get("schema") != PAYMENT_RECEIPT_SCHEMA:
        return False
    pbody = dict(payment)
    claimed = str(pbody.pop("receipt_hash", ""))
    if len(claimed) != 64 or canonical_hash(pbody) != claimed:
        return False
    if claimed != value.get("payment_receipt_hash"):
        return False
    if payment.get("chain_id") != 1 or payment.get("asset") != "USDT":
        return False
    if str(payment.get("token_contract") or "").lower() != USDT_ETHEREUM_CONTRACT:
        return False
    if str(payment.get("to_address") or "").lower() != MARKET_MERCHANT_ADDRESS:
        return False
    if payment.get("verification_status") != "VERIFIED_EXACT_ERC20_TRANSFER":
        return False
    if not isinstance(payment.get("amount_atomic"), int) or isinstance(payment.get("amount_atomic"), bool) or payment["amount_atomic"] <= 0:
        return False
    if not isinstance(payment.get("confirmations"), int) or payment["confirmations"] < 12:
        return False
    if not isinstance(payment.get("rpc_quorum"), int) or payment["rpc_quorum"] < 2:
        return False
    if not isinstance(payment.get("rpc_provider_count"), int) or payment["rpc_provider_count"] < payment["rpc_quorum"]:
        return False
    payment_reference = str(payment.get("payment_reference") or "")
    if not payment_reference or grant.get("payment_reference") != payment_reference:
        return False
    offer = value.get("offer")
    if not isinstance(offer, Mapping):
        return False
    price = offer.get("price")
    if not isinstance(price, Mapping):
        return False
    if price.get("asset") != "USDT" or price.get("network") != "ethereum-mainnet":
        return False
    if price.get("amount_atomic") != payment.get("amount_atomic") or price.get("decimals") != 6:
        return False
    if offer.get("payment_route_id") != payment.get("route_id"):
        return False
    expected_purchase_id = "pur-paid-" + canonical_hash({
        "request_id": value.get("request_id"),
        "request_hash": value.get("request_hash"),
        "offer_hash": value.get("offer_hash"),
        "payment_reference": payment_reference,
    })[:40]
    return grant.get("purchase_id") == expected_purchase_id


def verify_market_buyer_packet(packet: Mapping[str, Any]) -> bool:
    if not isinstance(packet, Mapping):
        return False
    value = dict(packet)
    claimed_packet_hash = str(value.pop("packet_hash", ""))
    if len(claimed_packet_hash) != 64 or canonical_hash(value) != claimed_packet_hash:
        return False
    schema = value.get("schema")
    if schema not in {PACKET_SCHEMA, PAID_PACKET_SCHEMA}:
        return False
    if value.get("market_repository") != MARKET_REPOSITORY or value.get("home_repository") != HOME_REPOSITORY:
        return False
    if value.get("transport_mode") != "PHYSARIUS_CREDENTIALLESS_PULL":
        return False
    for field in (
        "execution_authority_granted",
        "command_authority_granted",
        "external_effect_authorized",
        "physical_runtime_effect_authorized",
        "scientific_evidence_authority_granted",
        "world_truth_authority_granted",
    ):
        if value.get(field) is not False:
            return False

    grant = value.get("purchase_grant")
    query = value.get("buyer_query")
    if not isinstance(grant, Mapping) or not isinstance(query, Mapping):
        return False
    grant = dict(grant)
    query = dict(query)
    if grant.get("schema") != GRANT_SCHEMA or query.get("schema") != QUERY_SCHEMA:
        return False
    if canonical_hash(grant) != value.get("purchase_grant_hash"):
        return False
    if grant.get("status") != "PURCHASE_ELIGIBLE" or grant.get("execution_authority_granted") is not False:
        return False

    if schema == PACKET_SCHEMA:
        if value.get("mode") != "ZERO_PRICE_SHADOW" or value.get("money_enabled") is not False:
            return False
        if any(value.get(k) is not False for k in ("payment_required", "production_purchase")):
            return False
        if grant.get("payment_reference") is not None:
            return False
    else:
        if value.get("mode") != "PAID_ERC20" or value.get("money_enabled") is not True:
            return False
        if value.get("payment_required") is not True or value.get("production_purchase") is not True:
            return False
        if not _verify_paid_payment(value, grant):
            return False

    entitlement = grant.get("buyer_query_entitlement")
    if not isinstance(entitlement, Mapping):
        return False
    entitlement = dict(entitlement)
    if entitlement.get("enabled") is not True:
        return False
    if entitlement.get("read_only_conversation") is not True or entitlement.get("external_effect_authorized") is not False:
        return False
    if query.get("purchase_id") != grant.get("purchase_id"):
        return False
    if query.get("purchase_grant_hash") != value.get("purchase_grant_hash"):
        return False
    if query.get("buyer_actor_id") != entitlement.get("buyer_actor_id"):
        return False
    if query.get("entitlement_nonce") != entitlement.get("entitlement_nonce"):
        return False
    if query.get("query_id") != value.get("query_id") or query.get("query_hash") != value.get("query_hash"):
        return False

    qbody = dict(query)
    claimed_query_hash = str(qbody.pop("query_hash", ""))
    if len(claimed_query_hash) != 64 or canonical_hash(qbody) != claimed_query_hash:
        return False
    message_text = str(query.get("message_text") or "")
    message_hash = _sha256_bytes(message_text.encode("utf-8"))
    if message_hash != query.get("message_hash"):
        return False
    expected_query_id = "bq-" + canonical_hash({
        "purchase_id": query.get("purchase_id"),
        "conversation_id": query.get("conversation_id"),
        "turn_index": query.get("turn_index"),
        "message_hash": query.get("message_hash"),
        "entitlement_nonce": query.get("entitlement_nonce"),
    })
    if expected_query_id != query.get("query_id"):
        return False
    max_turns = entitlement.get("max_turns")
    turn_index = query.get("turn_index")
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        return False
    if not isinstance(turn_index, int) or isinstance(turn_index, bool) or not (0 <= turn_index < max_turns):
        return False
    max_message = entitlement.get("max_message_utf8_bytes")
    if not isinstance(max_message, int) or len(message_text.encode("utf-8")) > max_message:
        return False
    return True


def build_market_terminal_message(packet: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_market_buyer_packet(packet):
        raise MarketBuyerConversationError("MARKET_BUYER_PACKET_INVALID")
    packet = dict(packet)
    query = dict(packet["buyer_query"])
    buyer_actor = str(query["buyer_actor_id"])
    created_at = _iso_to_timestamp(str(query["created_at"]))
    terminal = build_terminal_message(
        conversation_id="market::" + str(query["conversation_id"]),
        human_actor=buyer_actor,
        message_text=str(query["message_text"]),
        source_ref=f"MARKET_BUYER_QUERY/{query['purchase_id']}/{query['query_id']}",
        created_at=created_at,
    )
    terminal.update({
        "actor_kind": "MACHINE_BUYER",
        "external_nerve": "JANUS_MACHINE_MARKET",
        "market_repository": MARKET_REPOSITORY,
        "market_purchase_id": query["purchase_id"],
        "market_purchase_grant_hash": packet["purchase_grant_hash"],
        "market_query_id": query["query_id"],
        "market_query_hash": query["query_hash"],
        "market_packet_hash": packet["packet_hash"],
        "market_mode": packet["mode"],
        "market_money_enabled": packet["money_enabled"],
        "market_execution_authority_granted": False,
        "market_external_effect_authorized": False,
    })
    if packet["mode"] == "PAID_ERC20":
        terminal["market_payment_reference"] = packet["payment_receipt"]["payment_reference"]
        terminal["market_payment_receipt_hash"] = packet["payment_receipt_hash"]
    terminal.pop("message_hash", None)
    terminal["message_hash"] = canonical_hash(terminal)
    if not verify_terminal_message(terminal):
        raise MarketBuyerConversationError("MARKET_BUYER_TERMINAL_ADAPTER_INVALID")
    return terminal


def build_market_home_response(
    *,
    packet: Mapping[str, Any],
    terminal_request: Mapping[str, Any],
    terminal_response: Mapping[str, Any],
    source_binding: Mapping[str, Any],
    replayed: bool,
) -> dict[str, Any]:
    if not verify_market_buyer_packet(packet):
        raise MarketBuyerConversationError("MARKET_BUYER_PACKET_INVALID_FOR_RESPONSE")
    if not verify_terminal_message(terminal_request):
        raise MarketBuyerConversationError("MARKET_TERMINAL_REQUEST_INVALID_FOR_RESPONSE")
    if not verify_terminal_response(terminal_response, request=terminal_request):
        raise MarketBuyerConversationError("MARKET_TERMINAL_RESPONSE_INVALID")
    packet = dict(packet)
    query = dict(packet["buyer_query"])
    terminal_response = dict(terminal_response)
    paid = packet["mode"] == "PAID_ERC20"
    _require(terminal_request.get("actor_kind") == "MACHINE_BUYER", "MARKET_RESPONSE_ACTOR_KIND_MISMATCH")
    _require(terminal_request.get("market_query_id") == query["query_id"], "MARKET_RESPONSE_QUERY_BINDING_MISMATCH")
    _require(terminal_response.get("command_authority_granted") is False, "MARKET_RESPONSE_COMMAND_AUTHORITY_FORBIDDEN")
    _require(terminal_response.get("external_effect_authorized") is False, "MARKET_RESPONSE_EFFECT_AUTHORITY_FORBIDDEN")

    receipt = {
        "schema": BUYER_RECEIPT_SCHEMA,
        "purchase_id": query["purchase_id"],
        "purchase_grant_hash": packet["purchase_grant_hash"],
        "query_id": query["query_id"],
        "query_hash": query["query_hash"],
        "status": "REPLAYED" if replayed else "DELIVERED",
        "resident_uuid": terminal_response.get("resident_uuid"),
        "model_digest": terminal_response.get("model_digest"),
        "file_fabric_digest": terminal_response.get("file_fabric_digest"),
        "turn_id": terminal_response.get("turn_id"),
        "hrain_context_receipt_hash": terminal_response.get("hrain_context_receipt_hash"),
        "hrain_context_hash": terminal_response.get("hrain_context_hash"),
        "memory_source_commit": terminal_response.get("memory_source_commit"),
        "response_text": terminal_response.get("response_text"),
        "response_hash": terminal_response.get("response_hash"),
        "execution_identity": terminal_response.get("response_id"),
        "execution_authority_granted": False,
        "external_effect_authorized": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "replayed": bool(replayed),
        "billable_execution_delta": 0 if replayed or not paid else 1,
    }
    response = {
        "schema": HOME_RESPONSE_SCHEMA,
        "market_repository": MARKET_REPOSITORY,
        "home_repository": HOME_REPOSITORY,
        "mode": packet["mode"],
        "query_id": query["query_id"],
        "query_hash": query["query_hash"],
        "purchase_id": query["purchase_id"],
        "purchase_grant_hash": packet["purchase_grant_hash"],
        "source_packet_binding": dict(source_binding),
        "terminal_message_id": terminal_request.get("message_id"),
        "terminal_message_hash": terminal_request.get("message_hash"),
        "terminal_response_id": terminal_response.get("response_id"),
        "terminal_response_hash": terminal_response.get("response_hash"),
        "buyer_query_receipt": receipt,
        "terminal_response": terminal_response,
        "return_route": dict(packet.get("return_route") or {}),
        "money_enabled": bool(packet["money_enabled"]),
        "execution_authority_granted": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "same_resident_required": True,
        "exact_retry_is_second_cognition": False,
    }
    if paid:
        response.update({
            "production_purchase": True,
            "payment_reference": packet["payment_receipt"]["payment_reference"],
            "payment_receipt_hash": packet["payment_receipt_hash"],
        })
    response["home_response_hash"] = canonical_hash(response)
    return response


def verify_market_home_response(response: Mapping[str, Any]) -> bool:
    if not isinstance(response, Mapping):
        return False
    value = dict(response)
    claimed = str(value.pop("home_response_hash", ""))
    if len(claimed) != 64 or canonical_hash(value) != claimed:
        return False
    if value.get("schema") != HOME_RESPONSE_SCHEMA:
        return False
    if value.get("market_repository") != MARKET_REPOSITORY or value.get("home_repository") != HOME_REPOSITORY:
        return False
    mode = value.get("mode")
    if mode == "ZERO_PRICE_SHADOW":
        if value.get("money_enabled") is not False:
            return False
    elif mode == "PAID_ERC20":
        if value.get("money_enabled") is not True or value.get("production_purchase") is not True:
            return False
        if not str(value.get("payment_reference") or "") or len(str(value.get("payment_receipt_hash") or "")) != 64:
            return False
    else:
        return False
    for field in ("execution_authority_granted", "command_authority_granted", "external_effect_authorized"):
        if value.get(field) is not False:
            return False
    receipt = value.get("buyer_query_receipt")
    terminal = value.get("terminal_response")
    if not isinstance(receipt, Mapping) or not isinstance(terminal, Mapping):
        return False
    if receipt.get("schema") != BUYER_RECEIPT_SCHEMA:
        return False
    if receipt.get("query_id") != value.get("query_id") or receipt.get("purchase_id") != value.get("purchase_id"):
        return False
    if receipt.get("execution_authority_granted") is not False or receipt.get("external_effect_authorized") is not False:
        return False
    delta = receipt.get("billable_execution_delta")
    if mode == "ZERO_PRICE_SHADOW" and delta != 0:
        return False
    if mode == "PAID_ERC20" and delta not in {0, 1}:
        return False
    if terminal.get("resident_uuid") != receipt.get("resident_uuid"):
        return False
    if terminal.get("response_hash") != receipt.get("response_hash"):
        return False
    return True


__all__ = [
    "MACHINE_BUYER_CLASSIFICATION",
    "MACHINE_BUYER_SOURCE_KIND",
    "MarketBuyerConversationError",
    "build_market_home_response",
    "build_market_terminal_message",
    "verify_market_buyer_packet",
    "verify_market_home_response",
]
