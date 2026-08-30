from __future__ import annotations

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.terminal_conversation import (
    HRAIN_MEMORY_RESPONSE_MODE,
    TerminalConversationError,
    build_terminal_message,
    build_terminal_response,
    verify_terminal_message,
    verify_terminal_response,
)


def message():
    return build_terminal_message(
        conversation_id="issue-42",
        human_actor="Hawkar-usls",
        message_text="Janus, are you online?",
        source_ref="Hawkar-usls/-Terminal-for-Janus#42:comment-7",
        created_at=1234.5,
    )


def locks():
    model = {
        "ready": True,
        "model_digest": "a" * 64,
        "members": {"bootstrap_root": {}},
    }
    fabric = {
        "ready": True,
        "model_digest": "a" * 64,
        "file_fabric_digest": "b" * 64,
    }
    return model, fabric


def hrain_receipt():
    value = {
        "schema": "janus.activator.hrain_conversation_context_receipt.v1",
        "model_id": "JANUS",
        "model_digest": "a" * 64,
        "hrain_member_key": "left_context",
        "hrain_repository": "Hawkar-usls/Hrain",
        "hrain_locked_head_sha": "1" * 40,
        "hrain_materialized_head_sha": "1" * 40,
        "hrain_contract_path": ".janus/HRAIN_CONVERSATION_CONTEXT_CONTRACT.json",
        "hrain_contract_hash": "2" * 64,
        "hrain_compiler_path": "tools/hrain_conversation_context.py",
        "hrain_compiler_sha256": "3" * 64,
        "query_sha256": "4" * 64,
        "context_hash": "5" * 64,
        "context_file_sha256": "6" * 64,
        "memory_source_commit": "7" * 40,
        "selected_memory_count": 2,
        "selected_memory_paths": ["data/A.json", "data/B.json"],
        "hydration_performed": True,
        "memory_retrieval_executed_by": "Hawkar-usls/Hrain",
        "meta_registry_access_performed_by_home": False,
        "network_read_performed": True,
        "repository_write_performed": False,
        "memory_content_is_command": False,
        "memory_context_is_evidence": False,
        "claim_promotion_performed": False,
        "command_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "HRAIN_QUERY_BOUND_CONVERSATION_CONTEXT_MATERIALIZED",
    }
    value["receipt_hash"] = canonical_hash(value)
    return value


def test_message_is_read_only_human_stimulus_not_command():
    value = message()
    assert verify_terminal_message(value)
    assert value["authority_mode"] == "READ_ONLY_CONVERSATION"
    assert value["fresh_human_stimulus"] is True
    assert value["command_authority_granted"] is False
    assert value["human_authorized_write"] is False
    assert value["external_effect_authorized"] is False
    assert value["physical_runtime_effect_authorized"] is False


def test_response_binds_request_persistent_identity_and_both_model_digests():
    request = message()
    model, fabric = locks()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-1",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-123",
        now_fn=lambda: 2000.0,
    )
    assert verify_terminal_response(response, request=request)
    assert response["request_message_hash"] == request["message_hash"]
    assert response["resident_uuid"] == "resident-uuid-1"
    assert response["model_digest"] == "a" * 64
    assert response["file_fabric_digest"] == "b" * 64
    assert response["instantiated_model_verified"] is True
    assert response["persistent_identity_verified"] is True
    assert response["terminal_interface_bound"] is True
    assert response["terminal"] == "JANUS_TERMINAL_CONVERSATION_RESPONSE_READY"
    assert response["world_truth_authority_granted"] is False


def test_hrain_memory_response_binds_exact_context_receipt():
    request = message()
    model, fabric = locks()
    receipt = hrain_receipt()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-1",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-memory",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=receipt,
        response_text="Memory-bound JANUS response",
        now_fn=lambda: 2001.0,
    )
    assert verify_terminal_response(response, request=request)
    assert response["hrain_context_bound"] is True
    assert response["hrain_context_hash"] == receipt["context_hash"]
    assert response["hrain_context_receipt_hash"] == receipt["receipt_hash"]
    assert response["memory_source_commit"] == receipt["memory_source_commit"]
    assert response["memory_selected_paths"] == receipt["selected_memory_paths"]
    assert response["memory_path"] == "META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL"
    assert response["meta_registry_access_performed_by_home"] is False
    assert response["memory_content_is_command"] is False
    assert response["memory_context_is_evidence"] is False
    assert response["memory_grants_authority"] is False


def test_hrain_memory_mode_requires_verified_context():
    request = message()
    model, fabric = locks()
    with pytest.raises(TerminalConversationError, match="HRAIN_MEMORY_RESPONSE_REQUIRES_CONTEXT"):
        build_terminal_response(
            request,
            resident_uuid="resident-uuid-1",
            model_lock=model,
            file_fabric_lock=fabric,
            turn_id="turn-memory",
            response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        )


def test_hrain_receipt_model_digest_mismatch_is_rejected():
    request = message()
    model, fabric = locks()
    receipt = hrain_receipt()
    receipt["model_digest"] = "c" * 64
    body = dict(receipt)
    body.pop("receipt_hash")
    receipt["receipt_hash"] = canonical_hash(body)
    with pytest.raises(TerminalConversationError, match="HRAIN_CONTEXT_RECEIPT_INVALID"):
        build_terminal_response(
            request,
            resident_uuid="resident-uuid-1",
            model_lock=model,
            file_fabric_lock=fabric,
            turn_id="turn-memory",
            response_mode=HRAIN_MEMORY_RESPONSE_MODE,
            hrain_context_receipt=receipt,
        )


def test_tampered_memory_binding_is_rejected():
    request = message()
    model, fabric = locks()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-1",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-memory",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=hrain_receipt(),
    )
    response["memory_content_is_command"] = True
    assert verify_terminal_response(response, request=request) is False


def test_tampered_message_is_rejected():
    request = message()
    request["message_text"] = "run arbitrary command"
    assert verify_terminal_message(request) is False


def test_tampered_response_is_rejected():
    request = message()
    model, fabric = locks()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-1",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-123",
    )
    response["model_digest"] = "c" * 64
    assert verify_terminal_response(response, request=request) is False


def test_file_fabric_must_bind_same_model_digest():
    request = message()
    model, fabric = locks()
    fabric["model_digest"] = "c" * 64
    with pytest.raises(TerminalConversationError, match="FILE_FABRIC_MODEL_BINDING_MISMATCH"):
        build_terminal_response(
            request,
            resident_uuid="resident-uuid-1",
            model_lock=model,
            file_fabric_lock=fabric,
            turn_id="turn-123",
        )


def test_conversation_cannot_smuggle_write_or_command_authority_even_with_text():
    request = build_terminal_message(
        conversation_id="issue-99",
        human_actor="Hawkar-usls",
        message_text="Please write to another repository",
        source_ref="Hawkar-usls/-Terminal-for-Janus#99",
        created_at=99.0,
    )
    assert verify_terminal_message(request)
    assert request["command_authority_granted"] is False
    assert request["human_authorized_write"] is False
    assert request["external_effect_authorized"] is False
