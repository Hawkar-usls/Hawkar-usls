from __future__ import annotations

import re
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
DIRECT_ANSWER_SURFACE = "DIRECT_ANSWER"
SYSTEM_STATUS_SURFACE = "SYSTEM_STATUS"
BOUNDED_INTEGER_CHOICE_KIND = "BOUNDED_INTEGER_CHOICE"
UNSUPPORTED_FREE_FORM_KIND = "UNSUPPORTED_FREE_FORM"


class TerminalConversationError(RuntimeError):
    pass


def _bounded_integer_range(message_text: str) -> tuple[int, int] | None:
    text = str(message_text).strip().lower().replace("–", "-").replace("—", "-")
    if not re.search(r"\b(?:выбери(?:те)?|выбрать|назови(?:те)?|обери|вибери|назви|pick|choose|select)\b", text):
        return None
    patterns = (
        r"(?:\bот\b|\bfrom\b)\s*(-?\d+)\s*(?:\bдо\b|\bto\b)\s*(-?\d+)",
        r"(?:\bмежду\b|\bbetween\b)\s*(-?\d+)\s*(?:\bи\b|\band\b)\s*(-?\d+)",
        r"(-?\d+)\s*-\s*(-?\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        low, high = sorted((first, second))
        if high - low > 1_000_000:
            raise TerminalConversationError("DIRECT_CHOICE_RANGE_TOO_LARGE")
        return low, high
    return None


def _system_status_requested(message_text: str) -> bool:
    text = str(message_text).strip().lower()
    markers = (
        "status",
        "system state",
        "system status",
        "are you online",
        "health",
        "diagnostic",
        "статус",
        "состояни",
        "онлайн",
        "диагност",
        "какие органы",
        "что запущено",
        "что активно",
        "покажи систему",
        "покажи состояние",
        "чекни",
        "чек ",
        "проверь систему",
        "стан системи",
        "статус системи",
    )
    return any(marker in text for marker in markers)


def _derive_bounded_integer_choice(
    *,
    request_message_hash: str,
    resident_uuid: str,
    turn_id: str,
    low: int,
    high: int,
) -> tuple[int, str]:
    if low > high:
        raise TerminalConversationError("DIRECT_CHOICE_RANGE_INVALID")
    seed = {
        "schema": "janus.terminal.direct_choice_seed.v1",
        "purpose": "SEALED_MEMORY_INDEPENDENT_BOUNDED_INTEGER_CHOICE",
        "request_message_hash": str(request_message_hash),
        "resident_uuid": str(resident_uuid),
        "turn_id": str(turn_id),
        "low": int(low),
        "high": int(high),
        "hrain_memory_influence": False,
    }
    derivation_hash = canonical_hash(seed)
    width = high - low + 1
    return low + (int(derivation_hash, 16) % width), derivation_hash


def _direct_unresolved_text(message_text: str) -> str:
    if re.search(r"[А-Яа-яЁёІіЇїЄє]", str(message_text)):
        return (
            "JANUS не подменяет обычный вопрос системным статусом. "
            "Для этого типа вопроса доверенный свободный языковой синтезатор пока не подключён."
        )
    return (
        "JANUS will not substitute system status for an ordinary question. "
        "A trusted free-form language synthesizer is not yet connected for this request."
    )


def _project_human_surface(
    message: Mapping[str, Any],
    *,
    resident_uuid: str,
    turn_id: str,
) -> tuple[str | None, Dict[str, Any]]:
    if message.get("actor_kind") == "MACHINE_BUYER":
        return None, {}
    message_text = str(message.get("message_text") or "")
    bounded = _bounded_integer_range(message_text)
    if bounded is not None:
        low, high = bounded
        value, derivation_hash = _derive_bounded_integer_choice(
            request_message_hash=str(message.get("message_hash") or ""),
            resident_uuid=resident_uuid,
            turn_id=turn_id,
            low=low,
            high=high,
        )
        return str(value), {
            "response_surface": DIRECT_ANSWER_SURFACE,
            "direct_answer_kind": BOUNDED_INTEGER_CHOICE_KIND,
            "direct_answer_range": [low, high],
            "direct_answer_value": value,
            "direct_answer_derivation_hash": derivation_hash,
            "direct_answer_memory_influence": False,
            "system_status_requested": False,
        }
    if _system_status_requested(message_text):
        return None, {
            "response_surface": SYSTEM_STATUS_SURFACE,
            "system_status_requested": True,
        }
    return _direct_unresolved_text(message_text), {
        "response_surface": DIRECT_ANSWER_SURFACE,
        "direct_answer_kind": UNSUPPORTED_FREE_FORM_KIND,
        "direct_answer_memory_influence": False,
        "system_status_requested": False,
    }


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

    surface_extension: Dict[str, Any] = {}
    projected_text: str | None = None
    if response_mode == HRAIN_MEMORY_RESPONSE_MODE and memory_extension:
        projected_text, surface_extension = _project_human_surface(
            message,
            resident_uuid=resident,
            turn_id=turn,
        )

    text = projected_text if projected_text is not None else (
        str(response_text).strip() if response_text is not None else (
            f"JANUS ONLINE. Persistent resident {resident} received the Terminal message "
            f"as a read-only conversation turn under model {model_digest[:12]} and "
            f"file-fabric {fabric_digest[:12]}."
        )
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
    if surface_extension:
        response_identity["response_surface"] = surface_extension.get("response_surface")

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
        **surface_extension,
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
            "DIRECT_ANSWER != SYSTEM_STATUS",
            "SYSTEM_STATUS_ONLY_WHEN_REQUESTED",
            "DIRECT_BOUNDED_CHOICE_MEMORY_INFLUENCE = FALSE",
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

    surface = value.get("response_surface")
    if surface is not None:
        if surface not in {DIRECT_ANSWER_SURFACE, SYSTEM_STATUS_SURFACE}:
            return False
        if surface == SYSTEM_STATUS_SURFACE:
            if value.get("system_status_requested") is not True:
                return False
            if request is not None and not _system_status_requested(str(request.get("message_text") or "")):
                return False
        else:
            if value.get("system_status_requested") is not False:
                return False
            if value.get("direct_answer_memory_influence") is not False:
                return False
            kind = value.get("direct_answer_kind")
            if kind == BOUNDED_INTEGER_CHOICE_KIND:
                bounds = value.get("direct_answer_range")
                choice = value.get("direct_answer_value")
                derivation_hash = str(value.get("direct_answer_derivation_hash") or "")
                if not isinstance(bounds, list) or len(bounds) != 2:
                    return False
                low, high = bounds
                if any(isinstance(x, bool) or not isinstance(x, int) for x in (low, high, choice)):
                    return False
                if low > high or not low <= choice <= high or str(choice) != value.get("response_text"):
                    return False
                if len(derivation_hash) != 64:
                    return False
                if request is not None:
                    parsed = _bounded_integer_range(str(request.get("message_text") or ""))
                    if parsed != (low, high):
                        return False
                    expected, expected_hash = _derive_bounded_integer_choice(
                        request_message_hash=str(request.get("message_hash") or ""),
                        resident_uuid=str(value.get("resident_uuid") or ""),
                        turn_id=str(value.get("turn_id") or ""),
                        low=low,
                        high=high,
                    )
                    if choice != expected or derivation_hash != expected_hash:
                        return False
            elif kind == UNSUPPORTED_FREE_FORM_KIND:
                if request is not None:
                    if _bounded_integer_range(str(request.get("message_text") or "")) is not None:
                        return False
                    if _system_status_requested(str(request.get("message_text") or "")):
                        return False
            else:
                return False
    return True


__all__ = [
    "AUTHORITY_MODE",
    "BOUNDED_INTEGER_CHOICE_KIND",
    "DIRECT_ANSWER_SURFACE",
    "HRAIN_MEMORY_RESPONSE_MODE",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "SYSTEM_STATUS_SURFACE",
    "TERMINAL_REPOSITORY",
    "TerminalConversationError",
    "UNSUPPORTED_FREE_FORM_KIND",
    "build_terminal_message",
    "build_terminal_response",
    "verify_terminal_message",
    "verify_terminal_response",
]
