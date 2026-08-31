from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.market_buyer_conversation import (
    MarketBuyerConversationError,
    build_market_home_response,
    build_market_terminal_message,
    verify_market_buyer_packet,
    verify_market_home_response,
)
from janus_spi.terminal_conversation import build_terminal_response, verify_terminal_message


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def packet() -> dict:
    message = "Какие архитектурные инварианты ты видишь в этом нерве?"
    request_hash = canonical_hash({
        "schema": "janus.machine_market.buyer_query_shadow_request.v1",
        "request_id": "github-issue-id:42",
        "sku": "JANUS.SEARCH",
        "buyer_actor_id": "github:Hawkar-usls",
        "conversation_id": "r1b-home-test",
        "turn_index": 0,
        "message_text": message,
        "created_at": "2026-08-31T06:30:00Z",
        "max_turns": 1,
        "max_message_utf8_bytes": 8000,
        "max_answer_utf8_bytes": 12000,
        "conversation_history_turns": 8,
        "source_issue_number": 42,
        "source_issue_id": 4242,
        "request_origin": "SELF_OWNER_SHADOW",
    })
    offer = {
        "schema": "janus.machine_market.buyer_query_shadow_offer.v1",
        "sku": "JANUS.SEARCH",
        "mode": "ZERO_PRICE_SHADOW",
        "price": {"amount": "0", "asset": "NONE"},
        "payment_required": False,
        "production_purchase": False,
        "buyer_query_turns": 1,
    }
    offer_hash = canonical_hash(offer)
    purchase_id = "pur-bq-shadow-" + canonical_hash({
        "request_id": "github-issue-id:42",
        "request_hash": request_hash,
        "offer_hash": offer_hash,
    })[:32]
    nonce = "shadow-" + canonical_hash({
        "purchase_id": purchase_id,
        "purpose": "R1B_ZERO_PRICE_BUYER_QUERY_ENTITLEMENT",
    })[:32]
    grant = {
        "schema": "janus.machine_market.purchase_grant.v1",
        "purchase_id": purchase_id,
        "sku": "JANUS.SEARCH",
        "offer_hash": offer_hash,
        "request_hash": request_hash,
        "terms_hash": None,
        "payment_reference": None,
        "status": "PURCHASE_ELIGIBLE",
        "execution_authority_granted": False,
        "allowed_operation": "REQUEST_BOUNDED_BUYER_QUERY",
        "authority_ceiling": {
            "conversation_mode": "READ_ONLY_HRAIN_MEMORY_BOUND",
            "external_effects": False,
            "repository_write": False,
            "shell": False,
            "secret_access": False,
            "scientific_claim_promotion": False,
            "production_effect_authority": False,
        },
        "buyer_query_entitlement": {
            "enabled": True,
            "buyer_actor_id": "github:Hawkar-usls",
            "max_turns": 1,
            "max_message_utf8_bytes": 8000,
            "max_answer_utf8_bytes": 12000,
            "conversation_history_turns": 8,
            "entitlement_nonce": nonce,
            "read_only_conversation": True,
            "external_effect_authorized": False,
        },
        "expires_at": None,
        "reasons": [
            "R1B_ZERO_PRICE_SHADOW",
            "PURCHASE_GRANT_IS_NOT_EXECUTION_AUTHORITY",
            "BUYER_QUERY_IS_NOT_COMMAND_AUTHORITY",
        ],
    }
    grant_hash = canonical_hash(grant)
    message_hash = sha_text(message)
    query_id = "bq-" + canonical_hash({
        "purchase_id": purchase_id,
        "conversation_id": "r1b-home-test",
        "turn_index": 0,
        "message_hash": message_hash,
        "entitlement_nonce": nonce,
    })
    query = {
        "schema": "janus.machine_market.buyer_query.v1",
        "purchase_id": purchase_id,
        "purchase_grant_hash": grant_hash,
        "sku": "JANUS.SEARCH",
        "buyer_actor_id": "github:Hawkar-usls",
        "conversation_id": "r1b-home-test",
        "turn_index": 0,
        "entitlement_nonce": nonce,
        "message_text": message,
        "message_hash": message_hash,
        "query_id": query_id,
        "conversation_history": [],
        "requested_output": {"mode": "JANUS_READ_ONLY_CONVERSATION"},
        "created_at": "2026-08-31T06:30:00Z",
    }
    query["query_hash"] = canonical_hash(query)
    result = {
        "schema": "janus.machine_market.home_buyer_query_packet.v1",
        "market_repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
        "home_repository": "Hawkar-usls/Hawkar-usls",
        "transport_mode": "PHYSARIUS_CREDENTIALLESS_PULL",
        "mode": "ZERO_PRICE_SHADOW",
        "request_origin": "SELF_OWNER_SHADOW",
        "request_id": "github-issue-id:42",
        "request_hash": request_hash,
        "offer": offer,
        "offer_hash": offer_hash,
        "purchase_grant": grant,
        "purchase_grant_hash": grant_hash,
        "buyer_query": query,
        "query_id": query_id,
        "query_hash": query["query_hash"],
        "return_route": {
            "repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
            "source_issue_number": 42,
            "source_issue_id": 4242,
        },
        "money_enabled": False,
        "payment_required": False,
        "production_purchase": False,
        "execution_authority_granted": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "laws": [
            "MARKET_IS_EXTERNAL_NERVE_NOT_JANUS_ROOT",
            "EVERY_EXTERNAL_NERVE -> HOME -> ACTIVATOR -> JANUS",
            "PAYMENT != COMMAND",
            "PURCHASE_GRANT != EXECUTION_AUTHORITY",
            "BUYER_QUERY != COMMAND",
            "PHYSARIUS_DELIVERY != AUTHORITY",
            "EXACT_RETRY != SECOND_COGNITION",
        ],
    }
    result["packet_hash"] = canonical_hash(result)
    return result


def paid_packet() -> dict:
    base = packet()
    payment = {
        "schema": "janus.machine_market.payment_receipt.v1",
        "route_id": "JANUS_USDT_ETHEREUM_MAINNET_V1",
        "chain_id": 1,
        "asset": "USDT",
        "token_contract": "0xdac17f958d2ee523a2206206994597c13d831ec7",
        "tx_hash": "0x" + "ab" * 32,
        "block_hash": "0x" + "cd" * 32,
        "block_number": 100,
        "log_index": 7,
        "from_address": "0x1111111111111111111111111111111111111111",
        "to_address": "0x7149081aea54fbef57effeb52a5a966b81cc03a0",
        "amount_atomic": 1_000_000,
        "confirmations": 21,
        "rpc_quorum": 2,
        "rpc_provider_count": 2,
        "verification_status": "VERIFIED_EXACT_ERC20_TRANSFER",
        "payment_reference": "ethereum:1:0x" + "ab" * 32 + ":7",
    }
    payment["receipt_hash"] = canonical_hash(payment)
    offer = {
        "schema": "janus.machine_market.paid_offer.v1",
        "sku": "JANUS.SEARCH",
        "price": {"asset": "USDT", "network": "ethereum-mainnet", "amount_atomic": 1_000_000, "decimals": 6},
        "price_manifest_hash": "1" * 64,
        "payment_route_id": payment["route_id"],
        "buyer_query_turns": 1,
        "production_purchase": True,
    }
    offer_hash = canonical_hash(offer)
    purchase_id = "pur-paid-" + canonical_hash({
        "request_id": base["request_id"],
        "request_hash": base["request_hash"],
        "offer_hash": offer_hash,
        "payment_reference": payment["payment_reference"],
    })[:40]
    nonce = "paid-" + canonical_hash({
        "purchase_id": purchase_id,
        "payment_reference": payment["payment_reference"],
        "purpose": "R2_PAID_BUYER_QUERY_ENTITLEMENT",
    })[:40]
    grant = dict(base["purchase_grant"])
    grant.update({
        "purchase_id": purchase_id,
        "offer_hash": offer_hash,
        "payment_reference": payment["payment_reference"],
        "terms_hash": "2" * 64,
        "reasons": ["R2_EXACT_USDT_PAYMENT_VERIFIED", "PURCHASE_GRANT_IS_NOT_EXECUTION_AUTHORITY", "BUYER_QUERY_IS_NOT_COMMAND_AUTHORITY"],
    })
    grant["buyer_query_entitlement"] = dict(grant["buyer_query_entitlement"])
    grant["buyer_query_entitlement"].update({"buyer_actor_id": "github:foreign-agent", "entitlement_nonce": nonce})
    grant_hash = canonical_hash(grant)
    message = base["buyer_query"]["message_text"]
    message_hash = sha_text(message)
    query_id = "bq-" + canonical_hash({
        "purchase_id": purchase_id,
        "conversation_id": "r1b-home-test",
        "turn_index": 0,
        "message_hash": message_hash,
        "entitlement_nonce": nonce,
    })
    query = dict(base["buyer_query"])
    query.update({
        "purchase_id": purchase_id,
        "purchase_grant_hash": grant_hash,
        "buyer_actor_id": "github:foreign-agent",
        "entitlement_nonce": nonce,
        "query_id": query_id,
    })
    query["query_hash"] = canonical_hash({k: v for k, v in query.items() if k != "query_hash"})
    result = {
        "schema": "janus.machine_market.home_paid_buyer_query_packet.v1",
        "market_repository": base["market_repository"],
        "home_repository": base["home_repository"],
        "transport_mode": base["transport_mode"],
        "mode": "PAID_ERC20",
        "request_origin": "FOREIGN_MACHINE_PURCHASE",
        "request_id": base["request_id"],
        "request_hash": base["request_hash"],
        "offer": offer,
        "offer_hash": offer_hash,
        "payment_receipt": payment,
        "payment_receipt_hash": payment["receipt_hash"],
        "purchase_grant": grant,
        "purchase_grant_hash": grant_hash,
        "buyer_query": query,
        "query_id": query_id,
        "query_hash": query["query_hash"],
        "return_route": base["return_route"],
        "money_enabled": True,
        "payment_required": True,
        "production_purchase": True,
        "execution_authority_granted": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "laws": ["PAYMENT != COMMAND", "PAYMENT != EXECUTION_AUTHORITY", "PHYSARIUS_DELIVERY != AUTHORITY"],
    }
    result["packet_hash"] = canonical_hash(result)
    return result


def make_terminal_response(p: dict):
    request = build_market_terminal_message(p)
    model = {"ready": True, "model_digest": "a" * 64}
    fabric = {"ready": True, "model_digest": "a" * 64, "file_fabric_digest": "b" * 64}
    terminal = build_terminal_response(
        request,
        resident_uuid="75e514ab-be76-42c8-bcb3-fc9670164f96",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-test",
        response_text="JANUS test response",
        now_fn=lambda: 1.0,
    )
    return request, terminal


def test_market_packet_verifies_and_adapts_to_existing_terminal_message():
    p = packet()
    assert verify_market_buyer_packet(p)
    message = build_market_terminal_message(p)
    assert verify_terminal_message(message)
    assert message["actor_kind"] == "MACHINE_BUYER"
    assert message["external_nerve"] == "JANUS_MACHINE_MARKET"
    assert message["market_query_id"] == p["query_id"]
    assert message["market_purchase_id"] == p["purchase_grant"]["purchase_id"]
    assert message["market_packet_hash"] == p["packet_hash"]
    assert message["market_money_enabled"] is False
    assert message["command_authority_granted"] is False
    assert message["external_effect_authorized"] is False


def test_paid_market_packet_verifies_and_uses_same_terminal_tissue():
    p = paid_packet()
    assert verify_market_buyer_packet(p)
    message = build_market_terminal_message(p)
    assert verify_terminal_message(message)
    assert message["actor_kind"] == "MACHINE_BUYER"
    assert message["external_nerve"] == "JANUS_MACHINE_MARKET"
    assert message["market_mode"] == "PAID_ERC20"
    assert message["market_money_enabled"] is True
    assert message["market_payment_reference"] == p["payment_receipt"]["payment_reference"]
    assert message["market_execution_authority_granted"] is False
    assert message["market_external_effect_authorized"] is False


def test_market_packet_tamper_fails_closed():
    p = packet()
    p["buyer_query"]["message_text"] = "tampered"
    assert not verify_market_buyer_packet(p)
    with pytest.raises(MarketBuyerConversationError, match="MARKET_BUYER_PACKET_INVALID"):
        build_market_terminal_message(p)


def test_paid_payment_tamper_fails_closed():
    p = paid_packet()
    p["payment_receipt"]["amount_atomic"] -= 1
    p["payment_receipt"]["receipt_hash"] = canonical_hash({k: v for k, v in p["payment_receipt"].items() if k != "receipt_hash"})
    p["payment_receipt_hash"] = p["payment_receipt"]["receipt_hash"]
    p["packet_hash"] = canonical_hash({k: v for k, v in p.items() if k != "packet_hash"})
    assert not verify_market_buyer_packet(p)


def test_wrong_buyer_entitlement_fails_closed():
    p = packet()
    p["purchase_grant"]["buyer_query_entitlement"]["buyer_actor_id"] = "github:other"
    p["purchase_grant_hash"] = canonical_hash(p["purchase_grant"])
    p["packet_hash"] = canonical_hash({k: v for k, v in p.items() if k != "packet_hash"})
    assert not verify_market_buyer_packet(p)


def test_home_response_wraps_same_existing_terminal_response():
    p = packet()
    request, terminal = make_terminal_response(p)
    source = {
        "market_source_commit": "c" * 40,
        "market_packet_git_blob_sha": "d" * 40,
        "market_packet_hash": p["packet_hash"],
        "pull_receipt_hash": "e" * 64,
    }
    response = build_market_home_response(packet=p, terminal_request=request, terminal_response=terminal, source_binding=source, replayed=False)
    assert verify_market_home_response(response)
    receipt = response["buyer_query_receipt"]
    assert receipt["resident_uuid"] == terminal["resident_uuid"]
    assert receipt["execution_identity"] == terminal["response_id"]
    assert receipt["response_hash"] == terminal["response_hash"]
    assert receipt["billable_execution_delta"] == 0
    assert response["money_enabled"] is False
    assert response["exact_retry_is_second_cognition"] is False


def test_paid_home_response_is_billable_once_but_still_read_only():
    p = paid_packet()
    request, terminal = make_terminal_response(p)
    source = {
        "market_source_commit": "c" * 40,
        "market_packet_git_blob_sha": "d" * 40,
        "market_packet_hash": p["packet_hash"],
        "pull_receipt_hash": "e" * 64,
    }
    response = build_market_home_response(packet=p, terminal_request=request, terminal_response=terminal, source_binding=source, replayed=False)
    assert verify_market_home_response(response)
    assert response["mode"] == "PAID_ERC20"
    assert response["money_enabled"] is True
    assert response["production_purchase"] is True
    assert response["payment_reference"] == p["payment_receipt"]["payment_reference"]
    assert response["buyer_query_receipt"]["billable_execution_delta"] == 1
    assert response["execution_authority_granted"] is False
    assert response["command_authority_granted"] is False
    assert response["external_effect_authorized"] is False


def test_machine_buyer_route_exists_and_is_read_only():
    routing = json.loads(Path(".janus/activator/ROUTING_TABLE.json").read_text(encoding="utf-8"))
    route = next(row for row in routing["routes"] if row.get("match") == "machine_buyer_read_only_conversation")
    assert route["conversation_authority_mode"] == "READ_ONLY_CONVERSATION"
    assert route["activation_implies_dispatch"] is False
    assert route["external_effect_authorized"] is False
    assert "purchase_grant_query_entitlement" in route["required_gates"]
    assert "BUYER_QUERY != COMMAND" in routing["global_guards"]
    assert "PHYSARIUS_DELIVERY != AUTHORITY" in routing["global_guards"]
