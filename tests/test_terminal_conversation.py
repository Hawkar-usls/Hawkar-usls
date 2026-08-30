from __future__ import annotations

import pytest

from janus_spi.terminal_conversation import (
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
