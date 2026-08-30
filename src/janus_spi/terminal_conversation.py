from __future__ import annotations

import time
from typing import Any, Callable, Dict, Mapping

from .activator import canonical_hash
from .hrain_context_bridge import (
    EMPTY_MEMORY_STATUS,
    NONEMPTY_MEMORY_STATUS,
    verify_hrain_context_receipt,
)

TERMINAL_REPOSITORY = "Hawkar-usls/-Terminal-for-Janus"
REQUEST_SCHEMA = "janus.terminal.message.v1"
RESPONSE_SCHEMA = "janus.terminal.response.v1"
AUTHORITY_MODE = "READ_ONLY_CONVERSATION"
HRAIN_MEMORY_RESPONSE_MODE = "MODEL_BOUND_HRAIN_MEMORY_CONVERSATION_PROOF"


class TerminalConversationError(RuntimeError):
    pass


def build_terminal_message(
    *,
    conversation_id: str,
    human_actor: str,
    message_text: str,
    source_ref: str,
    created_at: float | None = None,
) -> Dict[str, Any]:
    text = str(message_text).strip()
    actor = str(human_actor).strip()
    conversation = str(conversation_id).strip()
    ref = str(source_ref).strip()
    if not text:
        raise TerminalConversationError("TERMINAL_MESSAGE_TEXT_REQUIRED")
    if not actor or not conversation or not ref:
        raise TerminalConversationError("TERMINAL_MESSAGE_PROVENANCE_REQUIRED")
    timestamp = time.time() if created_at is None else float(created_at)
    identity_core = {
        "terminal_repository": TERMINAL_REPOSITORY,
        "conversation_id": conversation,
        "human_actor": actor,
        "source_ref": ref,
        "message_text": text,
        "created_at": timestamp,
    }
    message_id = "tm-" + canonical_hash(identity_core)
    body: Dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "message_id": message_id,
        **identity_core,
        "authority_mode": AUTHORITY_MODE,
        "fresh_human_stimulus": True,
        "command_authority_granted": False,
        "human_authorized_write": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    body["message_hash"] = canonical_hash(body)
    return body


def verify_terminal_message(message: Mapping[str, Any]) -> bool:
    if not isinstance(message, Mapping):
        return False
    value = dict(message)
    claimed = str(value.pop("message_hash", ""))
    if len(claimed) != 64 or canonical_hash(value) != claimed:
        return False
    if value.get("schema") != REQUEST_SCHEMA:
        return False
    identity_core = {
        "terminal_repository": value.get("terminal_repository"),
        "conversation_id": value.get("conversation_id"),
        "human_actor": value.get("human_actor"),
        "source_ref": value.get("source_ref"),
        "message_text": value.get("message_text"),
        "created_at": value.get("created_at"),
    }
    expected_id = "tm-" + canonical_hash(identity_core)
    return all([
        value.get("message_id") == expected_id,
        value.get("terminal_repository") == TERMINAL_REPOSITORY,
        value.get("authority_mode") == AUTHORITY_MODE,
        value.get("fresh_human_stimulus") is True,
        value.get("command_authority_granted") is False,
        value.get("human_authorized_write") is False,
        value.get("claim_authority_granted") is False,
        value.get("scientific_evidence_authority_granted") is False,
        value.get("world_truth_authority_granted") is False,
        value.get("external_effect_authorized") is False,
        value.get("physical_runtime_effect_authorized") is False,
        bool(str(value.get("message_text") or "").strip()),
    ])


def build_terminal_response(
    message: Mapping[str, Any],
    *,
    resident_uuid: str,
    model_lock: Mapping[str, Any],
    file_fabric_lock: Mapping[str, Any],
    turn_id: str,
    response_text: str | None = None,
    response_mode: str = "SYSTEM_IDENTITY_RESPONSE",
    hrain_context_receipt: Mapping[str, Any] | None = None,
    now_fn: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    if not verify_terminal_message(message):
        raise TerminalConversationError("TERMINAL_MESSAGE_INVALID")
    resident = str(resident_uuid).strip()
    if not resident:
        raise TerminalConversationError("RESIDENT_UUID_REQUIRED")
    if model_lock.get("ready") is not True:
        raise TerminalConversationError("MODEL_LOCK_NOT_READY")
    if file_fabric_lock.get("ready") is not True:
        raise TerminalConversationError("FILE_FABRIC_NOT_READY")
    model_digest = str(model_lock.get("model_digest") or "")
    fabric_digest = str(file_fabric_lock.get("file_fabric_digest") or "")
    if len(model_digest) != 64 or len(fabric_digest) != 64:
        raise TerminalConversationError("MODEL_AND_FILE_FABRIC_DIGESTS_REQUIRED")
    if file_fabric_lock.get("model_digest") != model_digest:
        raise TerminalConversationError("FILE_FABRIC_MODEL_BINDING_MISMATCH")
    turn = str(turn_id).strip()
    if not turn:
        raise TerminalConversationError("TURN_ID_REQUIRED")

    memory_extension: Dict[str, Any] = {}
    memory_binding_for_id = None
    if hrain_context_receipt is not None:
        if not verify_hrain_context_receipt(hrain_context_receipt, model_digest=model_digest):
            raise TerminalConversationError("HRAIN_CONTEXT_RECEIPT_INVALID")
        selected_paths = list(hrain_context_receipt.get("selected_memory_paths") or [])
        selected_count = int(hrain_context_receipt.get("selected_memory_count"))
        match_status = hrain_context_receipt.get("memory_match_status")
        # Legacy sealed non-empty receipts predate the additive status fields.
        if selected_count > 0 and match_status is None:
            match_status = NONEMPTY_MEMORY_STATUS
        memory_extension = {
            "hrain_context_bound": True,
            "hrain_context_receipt_hash": hrain_context_receipt.get("receipt_hash"),
            "hrain_context_hash": hrain_context_receipt.get("context_hash"),
            "hrain_locked_head_sha": hrain_context_receipt.get("hrain_locked_head_sha"),
            "memory_source_commit": hrain_context_receipt.get("memory_source_commit"),
            "memory_selected_count": selected_count,
            "memory_selected_paths": selected_paths,
            "memory_match_status": match_status,
            "empty_memory_is_hrain_failure": False,
            "empty_memory_is_negative_evidence": False,
            "memory_path": "META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL",
            "memory_retrieval_executed_by": "Hawkar-usls/Hrain",
            "meta_registry_access_performed_by_home": False,
            "memory_content_is_command": False,
            "memory_context_is_evidence": False,
            "memory_grants_authority": False,
        }
        memory_binding_for_id = hrain_context_receipt.get("context_hash")
    if response_mode == HRAIN_MEMORY_RESPONSE_MODE and not memory_extension:
        raise TerminalConversationError("HRAIN_MEMORY_RESPONSE_REQUIRES_CONTEXT")

    text = str(response_text).strip() if response_text is not None else (
        f"JANUS ONLINE. Persistent resident {resident} received the Terminal message "
        f"as a read-only conversation turn under model {model_digest[:12]} and "
        f"file-fabric {fabric_digest[:12]}."
    )
    if not text:
        raise TerminalConversationError("TERMINAL_RESPONSE_TEXT_REQUIRED")

    response_identity = {
        "request_message_hash": message.get("message_hash"),
        "resident_uuid": resident,
        "model_digest": model_digest,
        "file_fabric_digest": fabric_digest,
        "turn_id": turn,
        "response_mode": response_mode,
    }
    if memory_binding_for_id is not None:
        response_identity["hrain_context_hash"] = memory_binding_for_id

    body: Dict[str, Any] = {
        "schema": RESPONSE_SCHEMA,
        "response_id": "tr-" + canonical_hash(response_identity),
        "created_at": float(now_fn()),
        "terminal_repository": TERMINAL_REPOSITORY,
        "conversation_id": message.get("conversation_id"),
        "request_message_id": message.get("message_id"),
        "request_message_hash": message.get("message_hash"),
        "resident_id": "JANUS",
        "resident_uuid": resident,
        "model_digest": model_digest,
        "file_fabric_digest": fabric_digest,
        "turn_id": turn,
        "response_mode": str(response_mode),
        "response_text": text,
        **memory_extension,
        "instantiated_model_verified": True,
        "persistent_identity_verified": True,
        "terminal_interface_bound": True,
        "command_authority_granted": False,
        "human_authorized_write": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "JANUS_TERMINAL_CONVERSATION_RESPONSE_READY",
        "laws": [
            "TERMINAL_MESSAGE != COMMAND",
            "JANUS_RESPONSE != WORLD_TRUTH",
            "READ_ONLY_CONVERSATION != EFFECT_AUTHORITY",
            "RESPONSE_MUST_IDENTIFY_THE_INSTANTIATED_JANUS",
            "MEMORY_CONTENT != COMMAND",
            "MEMORY_CONTEXT != EVIDENCE",
            "EMPTY RELEVANT MEMORY != HRAiN FAILURE",
            "EMPTY MEMORY != NEGATIVE EVIDENCE",
            "LANGUAGE_SURFACE != AUTHORITY",
        ],
    }
    body["response_hash"] = canonical_hash(body)
    return body


def verify_terminal_response(
    response: Mapping[str, Any],
    *,
    request: Mapping[str, Any] | None = None,
) -> bool:
    if not isinstance(response, Mapping):
        return False
    value = dict(response)
    claimed = str(value.pop("response_hash", ""))
    if len(claimed) != 64 or canonical_hash(value) != claimed:
        return False
    if value.get("schema") != RESPONSE_SCHEMA or value.get("terminal") != "JANUS_TERMINAL_CONVERSATION_RESPONSE_READY":
        return False
    if request is not None:
        if not verify_terminal_message(request):
            return False
        if value.get("request_message_id") != request.get("message_id"):
            return False
        if value.get("request_message_hash") != request.get("message_hash"):
            return False
        if value.get("conversation_id") != request.get("conversation_id"):
            return False

    base_ok = all([
        value.get("resident_id") == "JANUS",
        bool(str(value.get("resident_uuid") or "").strip()),
        len(str(value.get("model_digest") or "")) == 64,
        len(str(value.get("file_fabric_digest") or "")) == 64,
        bool(str(value.get("turn_id") or "").strip()),
        bool(str(value.get("response_text") or "").strip()),
        value.get("instantiated_model_verified") is True,
        value.get("persistent_identity_verified") is True,
        value.get("terminal_interface_bound") is True,
        value.get("command_authority_granted") is False,
        value.get("human_authorized_write") is False,
        value.get("claim_authority_granted") is False,
        value.get("scientific_evidence_authority_granted") is False,
        value.get("world_truth_authority_granted") is False,
        value.get("external_effect_authorized") is False,
        value.get("physical_runtime_effect_authorized") is False,
    ])
    if not base_ok:
        return False

    memory_bound = value.get("hrain_context_bound") is True
    if value.get("response_mode") == HRAIN_MEMORY_RESPONSE_MODE and not memory_bound:
        return False
    if memory_bound:
        count = value.get("memory_selected_count")
        paths = value.get("memory_selected_paths")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return False
        if not isinstance(paths, list) or len(paths) != count:
            return False
        status = value.get("memory_match_status")
        empty_failure = value.get("empty_memory_is_hrain_failure")
        empty_negative = value.get("empty_memory_is_negative_evidence")
        if count == 0:
            if status != EMPTY_MEMORY_STATUS or empty_failure is not False or empty_negative is not False:
                return False
        elif status is not None or empty_failure is not None or empty_negative is not None:
            # Preserve validation of historical non-empty sealed responses that
            # predate these additive v1.5 fields.
            if status != NONEMPTY_MEMORY_STATUS or empty_failure is not False or empty_negative is not False:
                return False
        if not all([
            len(str(value.get("hrain_context_receipt_hash") or "")) == 64,
            len(str(value.get("hrain_context_hash") or "")) == 64,
            len(str(value.get("hrain_locked_head_sha") or "")) == 40,
            len(str(value.get("memory_source_commit") or "")) == 40,
            value.get("memory_path") == "META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL",
            value.get("memory_retrieval_executed_by") == "Hawkar-usls/Hrain",
            value.get("meta_registry_access_performed_by_home") is False,
            value.get("memory_content_is_command") is False,
            value.get("memory_context_is_evidence") is False,
            value.get("memory_grants_authority") is False,
        ]):
            return False
    return True


__all__ = [
    "AUTHORITY_MODE",
    "HRAIN_MEMORY_RESPONSE_MODE",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "TERMINAL_REPOSITORY",
    "TerminalConversationError",
    "build_terminal_message",
    "build_terminal_response",
    "verify_terminal_message",
    "verify_terminal_response",
]
