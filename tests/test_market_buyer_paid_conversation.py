from __future__ import annotations

from janus_spi.activator import canonical_hash
from janus_spi.market_buyer_conversation import (
    PAID_MODE,
    build_market_home_response,
    build_market_terminal_message,
    verify_market_buyer_packet,
    verify_market_home_response,
)
from janus_spi.terminal_conversation import build_terminal_response

RECEIVER = "0x7149081aea54fbef57effeb52a5a966b81cc03a0"
TOKEN = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
TX = "0x" + "ab" * 32


def paid_packet() -> dict:
    message = "Проверь архитектурный инвариант платного JANUS.SEARCH."
    request = {
        "schema": "janus.machine_market.buyer_query_shadow_request.v1",
        "request_id": "github-issue-id:9001",
        "sku": "JANUS.SEARCH",
        "buyer_actor_id": "github:external-buyer",
        "conversation_id": "paid-search-9001",
        "turn_index": 0,
        "message_text": message,
        "created_at": "2026-09-04T12:00:00Z",
        "max_turns": 1,
        "max_message_utf8_bytes": 4000,
        "max_answer_utf8_bytes": 6000,
        "conversation_history_turns": 0,
        "source_issue_number": 9001,
        "source_issue_id": 9001001,
        "request_origin": "FOREIGN_PAID_SEARCH",
    }
    request_hash = canonical_hash(request)
    quote = {
        "schema": "janus.machine_market.quote.v1",
        "sku": "JANUS.SEARCH",
        "request_hash": request_hash,
        "amount_usdt_micros": 50_000,
        "asset": "USDT",
        "chain_id": 1,
        "token_contract": TOKEN,
        "receiving_address": RECEIVER,
        "expires_at": "2026-09-04T13:00:00+00:00",
        "nonce": "paid-test-9001",
        "policy_version": "commerce-paid-search-v1",
    }
    quote["quote_hash"] = canonical_hash(quote)
    payment_ref = f"{TX}:7"
    payment = {
        "schema": "janus.machine_market.payment_receipt.v1",
        "status": "CONFIRMED",
        "quote_hash": quote["quote_hash"],
        "tx_hash": TX,
        "log_index": 7,
        "payment_reference": payment_ref,
        "chain_id": 1,
        "token_contract": TOKEN,
        "to": RECEIVER,
        "amount_usdt_micros": 50_000,
        "confirmations": 12,
        "required_confirmations": 12,
    }
    purchase_id = "jp-" + canonical_hash({"quote_hash": quote["quote_hash"], "payment_reference": payment_ref})[:40]
    entitlement_nonce = "paid-" + canonical_hash({"purchase_id": purchase_id, "buyer": request["buyer_actor_id"]})[:32]
    grant = {
        "schema": "janus.machine_market.purchase_grant.v1",
        "purchase_id": purchase_id,
        "sku": "JANUS.SEARCH",
        "offer_hash": None,
        "quote_hash": quote["quote_hash"],
        "request_hash": request_hash,
        "terms_hash": None,
        "payment_reference": payment_ref,
        "amount_usdt_micros": 50_000,
        "policy_version": "commerce-paid-search-v1",
        "status": "PURCHASE_SETTLED",
        "execution_authority_granted": False,
        "allowed_operation": "REQUEST_BOUNDED_BUYER_QUERY",
        "next_gate": "JANUS_HOME_READ_ONLY_BUYER_QUERY",
        "authority_ceiling": {
            "sku": "JANUS.SEARCH",
            "production_activator_authority": False,
            "external_effect_authority": False,
        },
        "buyer_query_entitlement": {
            "enabled": True,
            "buyer_actor_id": request["buyer_actor_id"],
            "max_turns": 1,
            "max_message_utf8_bytes": 4000,
            "max_answer_utf8_bytes": 6000,
            "conversation_history_turns": 0,
            "entitlement_nonce": entitlement_nonce,
            "read_only_conversation": True,
            "external_effect_authorized": False,
        },
        "expires_at": None,
        "reasons": ["PAYMENT_CONFIRMED_PURCHASE_GRANT_IS_NOT_EXECUTION_AUTHORITY"],
    }
    grant["grant_hash"] = canonical_hash(grant)
    message_hash = __import__("hashlib").sha256(message.encode()).hexdigest()
    query_id = "bq-" + canonical_hash({
        "purchase_id": purchase_id,
        "conversation_id": request["conversation_id"],
        "turn_index": 0,
        "message_hash": message_hash,
        "entitlement_nonce": entitlement_nonce,
    })
    query = {
        "schema": "janus.machine_market.buyer_query.v1",
        "purchase_id": purchase_id,
        "purchase_grant_hash": grant["grant_hash"],
        "sku": "JANUS.SEARCH",
        "buyer_actor_id": request["buyer_actor_id"],
        "conversation_id": request["conversation_id"],
        "turn_index": 0,
        "entitlement_nonce": entitlement_nonce,
        "message_text": message,
        "message_hash": message_hash,
        "query_id": query_id,
        "conversation_history": [],
        "requested_output": {"mode": "JANUS_READ_ONLY_CONVERSATION"},
        "created_at": request["created_at"],
    }
    query["query_hash"] = canonical_hash(query)
    packet = {
        "schema": "janus.machine_market.home_buyer_query_packet.v1",
        "market_repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
        "home_repository": "Hawkar-usls/Hawkar-usls",
        "transport_mode": "PHYSARIUS_CREDENTIALLESS_PULL",
        "mode": PAID_MODE,
        "request_origin": request["request_origin"],
        "request_id": request["request_id"],
        "request_hash": request_hash,
        "offer": {"schema": "janus.machine_market.paid_search_offer.v1", "sku": "JANUS.SEARCH", "quote_required": True},
        "offer_hash": canonical_hash({"schema": "janus.machine_market.paid_search_offer.v1", "sku": "JANUS.SEARCH", "quote_required": True}),
        "purchase_grant": grant,
        "purchase_grant_hash": grant["grant_hash"],
        "buyer_query": query,
        "query_id": query_id,
        "query_hash": query["query_hash"],
        "return_route": {"repository": "Hawkar-usls/JANUS-MACHINE-MARKET", "source_issue_number": 9001, "source_issue_id": 9001001},
        "commerce": {
            "quote": quote,
            "quote_hash": quote["quote_hash"],
            "payment_receipt": payment,
            "payment_reference": payment_ref,
            "settlement_verified": True,
        },
        "money_enabled": True,
        "payment_required": True,
        "production_purchase": True,
        "execution_authority_granted": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "laws": ["PAYMENT != COMMAND", "PURCHASE_GRANT != EXECUTION_AUTHORITY", "BUYER_QUERY != COMMAND", "EXACT_RETRY != SECOND_COGNITION"],
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def test_paid_packet_is_accepted_only_as_read_only_home_query():
    p = paid_packet()
    assert verify_market_buyer_packet(p)
    terminal = build_market_terminal_message(p)
    assert terminal["market_mode"] == PAID_MODE
    assert terminal["market_money_enabled"] is True
    assert terminal["market_payment_reference"] == p["commerce"]["payment_reference"]
    assert terminal["command_authority_granted"] is False
    assert terminal["external_effect_authorized"] is False


def test_paid_packet_wrong_recipient_fails_closed():
    p = paid_packet()
    p["commerce"]["payment_receipt"]["to"] = "0x" + "11" * 20
    p["packet_hash"] = canonical_hash({k: v for k, v in p.items() if k != "packet_hash"})
    assert not verify_market_buyer_packet(p)


def test_paid_packet_underconfirmed_fails_closed():
    p = paid_packet()
    p["commerce"]["payment_receipt"]["confirmations"] = 11
    p["packet_hash"] = canonical_hash({k: v for k, v in p.items() if k != "packet_hash"})
    assert not verify_market_buyer_packet(p)


def test_paid_home_response_marks_one_billable_execution_but_no_command_authority():
    p = paid_packet()
    request = build_market_terminal_message(p)
    terminal = build_terminal_response(
        request,
        resident_uuid="75e514ab-be76-42c8-bcb3-fc9670164f96",
        model_lock={"ready": True, "model_digest": "a" * 64},
        file_fabric_lock={"ready": True, "model_digest": "a" * 64, "file_fabric_digest": "b" * 64},
        turn_id="paid-turn-test",
        response_text="JANUS paid test response",
        now_fn=lambda: 1.0,
    )
    response = build_market_home_response(
        packet=p,
        terminal_request=request,
        terminal_response=terminal,
        source_binding={"market_packet_hash": p["packet_hash"], "pull_receipt_hash": "e" * 64, "transport": "PHYSARIUS_CREDENTIALLESS_PULL"},
        replayed=False,
    )
    assert verify_market_home_response(response)
    assert response["money_enabled"] is True
    assert response["payment_reference"] == p["commerce"]["payment_reference"]
    assert response["buyer_query_receipt"]["billable_execution_delta"] == 1
    assert response["execution_authority_granted"] is False
    assert response["external_effect_authorized"] is False


def test_paid_replay_is_not_second_billable_execution():
    p = paid_packet()
    request = build_market_terminal_message(p)
    terminal = build_terminal_response(
        request,
        resident_uuid="75e514ab-be76-42c8-bcb3-fc9670164f96",
        model_lock={"ready": True, "model_digest": "a" * 64},
        file_fabric_lock={"ready": True, "model_digest": "a" * 64, "file_fabric_digest": "b" * 64},
        turn_id="paid-turn-replay",
        response_text="JANUS paid replay",
        now_fn=lambda: 1.0,
    )
    response = build_market_home_response(packet=p, terminal_request=request, terminal_response=terminal, source_binding={}, replayed=True)
    assert response["buyer_query_receipt"]["billable_execution_delta"] == 0
    assert response["exact_retry_is_second_cognition"] is False
