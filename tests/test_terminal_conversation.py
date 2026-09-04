from __future__ import annotations

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.hrain_context_bridge import EMPTY_MEMORY_STATUS, NONEMPTY_MEMORY_STATUS
from janus_spi.terminal_conversation import (
    BOUNDED_INTEGER_CHOICE_KIND,
    DIRECT_ANSWER_SURFACE,
    HRAIN_MEMORY_RESPONSE_MODE,
    SYSTEM_STATUS_SURFACE,
    UNSUPPORTED_FREE_FORM_KIND,
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


def hrain_receipt(*, empty: bool = False, explicit_v15: bool = False):
    paths = [] if empty else ["data/A.json", "data/B.json"]
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
        "selected_memory_count": len(paths),
        "selected_memory_paths": paths,
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
    if empty or explicit_v15:
        value.update({
            "memory_match_status": EMPTY_MEMORY_STATUS if empty else NONEMPTY_MEMORY_STATUS,
            "empty_memory_is_hrain_failure": False,
            "empty_memory_is_negative_evidence": False,
        })
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
    receipt = hrain_receipt(explicit_v15=True)
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
    assert response["memory_match_status"] == NONEMPTY_MEMORY_STATUS
    assert response["memory_path"] == "META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL"
    assert response["meta_registry_access_performed_by_home"] is False
    assert response["memory_content_is_command"] is False
    assert response["memory_context_is_evidence"] is False
    assert response["memory_grants_authority"] is False
    assert response["response_surface"] == SYSTEM_STATUS_SURFACE
    assert response["system_status_requested"] is True


def test_empty_hrain_memory_response_is_valid_and_explicitly_not_negative_evidence():
    request = message()
    model, fabric = locks()
    receipt = hrain_receipt(empty=True)
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-1",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-empty-memory",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=receipt,
        response_text="No strong relevant HRAiN memory selected; this is not negative evidence.",
        now_fn=lambda: 2002.0,
    )
    assert verify_terminal_response(response, request=request)
    assert response["memory_selected_count"] == 0
    assert response["memory_selected_paths"] == []
    assert response["memory_match_status"] == EMPTY_MEMORY_STATUS
    assert response["empty_memory_is_hrain_failure"] is False
    assert response["empty_memory_is_negative_evidence"] is False
    assert "EMPTY RELEVANT MEMORY != HRAiN FAILURE" in response["laws"]
    assert "EMPTY MEMORY != NEGATIVE EVIDENCE" in response["laws"]


def test_legacy_nonempty_hrain_receipt_remains_valid_after_v15():
    request = message()
    model, fabric = locks()
    receipt = hrain_receipt()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-1",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-legacy-memory",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=receipt,
        response_text="Legacy sealed non-empty receipt",
        now_fn=lambda: 2003.0,
    )
    assert verify_terminal_response(response, request=request)
    assert response["memory_match_status"] == NONEMPTY_MEMORY_STATUS
    assert response["memory_selected_count"] == 2


def test_empty_hrain_receipt_without_explicit_empty_semantics_is_rejected():
    request = message()
    model, fabric = locks()
    receipt = hrain_receipt(empty=True)
    receipt.pop("memory_match_status")
    body = dict(receipt)
    body.pop("receipt_hash")
    receipt["receipt_hash"] = canonical_hash(body)
    with pytest.raises(TerminalConversationError, match="HRAIN_CONTEXT_RECEIPT_INVALID"):
        build_terminal_response(
            request,
            resident_uuid="resident-uuid-1",
            model_lock=model,
            file_fabric_lock=fabric,
            turn_id="turn-empty-invalid",
            response_mode=HRAIN_MEMORY_RESPONSE_MODE,
            hrain_context_receipt=receipt,
        )


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


def test_bounded_integer_choice_is_direct_only_and_memory_independent():
    request = build_terminal_message(
        conversation_id="issue-choice",
        human_actor="Hawkar-usls",
        message_text="Выбери номер от 1 до 30.",
        source_ref="Hawkar-usls/-Terminal-for-Janus#choice",
        created_at=5000.0,
    )
    model, fabric = locks()
    receipt_a = hrain_receipt(explicit_v15=True)
    receipt_b = hrain_receipt(explicit_v15=True)
    receipt_b["context_hash"] = "9" * 64
    receipt_b["memory_source_commit"] = "8" * 40
    body = dict(receipt_b)
    body.pop("receipt_hash")
    receipt_b["receipt_hash"] = canonical_hash(body)

    response_a = build_terminal_response(
        request,
        resident_uuid="resident-uuid-choice",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-choice",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=receipt_a,
        response_text="THIS SYSTEM STATUS MUST NOT LEAK TO THE ANSWER",
        now_fn=lambda: 3000.0,
    )
    response_b = build_terminal_response(
        request,
        resident_uuid="resident-uuid-choice",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-choice",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=receipt_b,
        response_text="A DIFFERENT MEMORY PROOF MUST NOT CHANGE THE CHOICE",
        now_fn=lambda: 3001.0,
    )

    assert verify_terminal_response(response_a, request=request)
    assert verify_terminal_response(response_b, request=request)
    assert response_a["response_surface"] == DIRECT_ANSWER_SURFACE
    assert response_a["direct_answer_kind"] == BOUNDED_INTEGER_CHOICE_KIND
    assert response_a["direct_answer_memory_influence"] is False
    assert response_a["system_status_requested"] is False
    assert response_a["direct_answer_range"] == [1, 30]
    assert 1 <= response_a["direct_answer_value"] <= 30
    assert response_a["response_text"] == str(response_a["direct_answer_value"])
    assert response_b["response_text"] == response_a["response_text"]
    assert response_b["direct_answer_derivation_hash"] == response_a["direct_answer_derivation_hash"]
    assert response_b["hrain_context_hash"] != response_a["hrain_context_hash"]


def test_explicit_status_request_keeps_system_status_surface():
    request = build_terminal_message(
        conversation_id="issue-status",
        human_actor="Hawkar-usls",
        message_text="Покажи статус системы и активные органы.",
        source_ref="Hawkar-usls/-Terminal-for-Janus#status",
        created_at=5001.0,
    )
    model, fabric = locks()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-status",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-status",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=hrain_receipt(explicit_v15=True),
        response_text="SYSTEM STATUS PROOF",
        now_fn=lambda: 3002.0,
    )
    assert verify_terminal_response(response, request=request)
    assert response["response_surface"] == SYSTEM_STATUS_SURFACE
    assert response["system_status_requested"] is True
    assert response["response_text"] == "SYSTEM STATUS PROOF"


def test_ordinary_question_is_not_replaced_by_system_status_dump():
    request = build_terminal_message(
        conversation_id="issue-free-form",
        human_actor="Hawkar-usls",
        message_text="Расскажи, что ты думаешь о шахматах.",
        source_ref="Hawkar-usls/-Terminal-for-Janus#free-form",
        created_at=5002.0,
    )
    model, fabric = locks()
    response = build_terminal_response(
        request,
        resident_uuid="resident-uuid-free-form",
        model_lock=model,
        file_fabric_lock=fabric,
        turn_id="turn-free-form",
        response_mode=HRAIN_MEMORY_RESPONSE_MODE,
        hrain_context_receipt=hrain_receipt(explicit_v15=True),
        response_text="JANUS ONLINE. SYSTEM STATUS SHOULD NOT SUBSTITUTE AN ANSWER.",
        now_fn=lambda: 3003.0,
    )
    assert verify_terminal_response(response, request=request)
    assert response["response_surface"] == DIRECT_ANSWER_SURFACE
    assert response["direct_answer_kind"] == UNSUPPORTED_FREE_FORM_KIND
    assert response["direct_answer_memory_influence"] is False
    assert response["system_status_requested"] is False
    assert "JANUS ONLINE" not in response["response_text"]
