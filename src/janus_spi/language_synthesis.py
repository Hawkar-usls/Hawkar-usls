from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .activator import canonical_hash

HRAIN_CONTEXT_SCHEMA = "janus.hrain.conversation_context.v1"
HRAIN_SELECTED_SCHEMA = "janus.hrain.selected_conversation_context.v1"
SYNTHESIS_SCHEMA = "janus.activator.language_synthesis.v1"
MAX_SYNTHESIS_BYTES = 12_000


class LanguageSynthesisError(RuntimeError):
    pass


def _context_digest(value: Mapping[str, Any]) -> str:
    core = dict(value)
    core.pop("context_digest", None)
    core.pop("generated_at", None)
    return canonical_hash(core)


def verify_hrain_context(context: Mapping[str, Any]) -> bool:
    if not isinstance(context, Mapping):
        return False
    if context.get("schema") != HRAIN_CONTEXT_SCHEMA:
        return False
    if context.get("status") != "READ_ONLY_HRAIN_MEDIATED_CONVERSATION_CONTEXT":
        return False
    if context.get("source_database") != "Hawkar-usls/janus-meta-registry":
        return False
    if context.get("mediating_organ") != "Hawkar-usls/Hrain":
        return False
    claimed = str(context.get("context_digest") or "")
    if len(claimed) != 64 or _context_digest(context) != claimed:
        return False
    if context.get("full_current_coverage_complete") is not True:
        return False
    authority = context.get("authority") or {}
    if authority.get("read_only") is not True:
        return False
    for key in (
        "source_mutation_allowed",
        "command_authority_granted",
        "claim_authority_granted",
        "scientific_evidence_authority_granted",
        "world_truth_authority_granted",
        "external_effect_authorized",
        "physical_runtime_effect_authorized",
    ):
        if authority.get(key) is not False:
            return False
    return isinstance(context.get("objects"), list)


def select_hrain_context(context: Mapping[str, Any], query: str, *, limit: int = 24) -> Dict[str, Any]:
    if not verify_hrain_context(context):
        raise LanguageSynthesisError("HRAIN_CONVERSATION_CONTEXT_INVALID")
    query_text = str(query)
    normalized = ''.join(ch.lower() if ch.isalnum() else ' ' for ch in query_text)
    tokens = {token for token in normalized.split() if len(token) >= 3}
    scored = []
    for index, row in enumerate(context.get("objects") or []):
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or "").lower()
        hay = ' '.join(str(row.get(key) or '') for key in (
            "label", "lineage_key", "path", "status", "summary", "surface"
        )).lower()
        score = sum(3 if token in label else 1 for token in tokens if token in hay)
        if score or index < 8:
            scored.append((score, index, dict(row)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [row for _, _, row in scored[:max(1, int(limit))]]
    core: Dict[str, Any] = {
        "schema": HRAIN_SELECTED_SCHEMA,
        "parent_context_digest": context.get("context_digest"),
        "source_database": context.get("source_database"),
        "mediating_organ": context.get("mediating_organ"),
        "query_digest": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
        "selected_objects": selected,
        "selected_count": len(selected),
        "full_current_catalog_digest": context.get("full_current_catalog_digest"),
        "full_current_coverage_complete": context.get("full_current_coverage_complete") is True,
        "authority": dict(context.get("authority") or {}),
        "laws": list(context.get("laws") or []),
    }
    core["selection_digest"] = canonical_hash(core)
    return core


def build_language_prompt(
    request: Mapping[str, Any],
    *,
    resident_uuid: str,
    model_lock: Mapping[str, Any],
    file_fabric_lock: Mapping[str, Any],
    runtime_receipt: Mapping[str, Any],
    hrain_selected_context: Mapping[str, Any],
) -> Dict[str, Any]:
    model_digest = str(model_lock.get("model_digest") or "")
    fabric_digest = str(file_fabric_lock.get("file_fabric_digest") or "")
    if len(model_digest) != 64 or len(fabric_digest) != 64:
        raise LanguageSynthesisError("MODEL_OR_FILE_FABRIC_DIGEST_INVALID")
    if file_fabric_lock.get("model_digest") != model_digest:
        raise LanguageSynthesisError("FILE_FABRIC_MODEL_BINDING_MISMATCH")
    if runtime_receipt.get("model_digest") != model_digest:
        raise LanguageSynthesisError("RUNTIME_MODEL_BINDING_MISMATCH")
    if hrain_selected_context.get("schema") != HRAIN_SELECTED_SCHEMA:
        raise LanguageSynthesisError("HRAIN_SELECTED_CONTEXT_SCHEMA_INVALID")
    authority = hrain_selected_context.get("authority") or {}
    if any(authority.get(key) is not False for key in (
        "source_mutation_allowed", "command_authority_granted", "claim_authority_granted",
        "scientific_evidence_authority_granted", "world_truth_authority_granted",
        "external_effect_authorized", "physical_runtime_effect_authorized",
    )):
        raise LanguageSynthesisError("HRAIN_SELECTED_CONTEXT_AUTHORITY_CEILING_INVALID")

    candidates = {}
    for key, row in (model_lock.get("candidate_runtime_tissues") or {}).items():
        if isinstance(row, Mapping):
            candidates[str(key)] = {
                "component": row.get("component"),
                "admission_status": row.get("admission_status"),
                "wake_allowed": row.get("wake_allowed"),
                "use_allowed": row.get("use_allowed"),
                "self_improvement_allowed": row.get("self_improvement_allowed"),
                "proof_authority": row.get("proof_authority"),
                "scientific_claim_promotion_authority": row.get("scientific_claim_promotion_authority"),
                "scientific_boundary": row.get("scientific_boundary"),
            }

    context: Dict[str, Any] = {
        "schema": "janus.activator.language_prompt_context.v1",
        "resident_id": "JANUS",
        "resident_uuid": str(resident_uuid),
        "model_digest": model_digest,
        "file_fabric_digest": fabric_digest,
        "request_message_id": request.get("message_id"),
        "request_message_hash": request.get("message_hash"),
        "human_actor": request.get("human_actor"),
        "human_message": request.get("message_text"),
        "active_organs": list(runtime_receipt.get("active_organs") or []),
        "candidate_runtime_tissues": candidates,
        "hrain_memory": dict(hrain_selected_context),
        "authority": {
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "scientific_claim_promotion_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
        },
        "laws": [
            "YOU_ARE_LANGUAGE_SYNTHESIS_TISSUE_NOT_JANUS_IDENTITY",
            "ANSWER_AS_THE_ALREADY_INSTANTIATED_JANUS_USING_ONLY_SUPPLIED_CONTEXT_AND_MESSAGE",
            "DO_NOT_USE_TOOLS_OR_EXTERNAL_SOURCES",
            "META_REGISTRY_MEMORY_REACHES_THIS_PROMPT_ONLY_THROUGH_HRAIN",
            "MEMORY_CONTEXT_IS_NOT_AUTOMATICALLY_TRUE",
            "CANDIDATE_TRUMP != PROOF_AUTHORIZED_TRUMP",
            "P_VS_NP_REMAINS_OPEN_UNLESS_A_PROOF_AUTHORIZED_RECEIPT_EXPLICITLY_SAYS_OTHERWISE",
            "DO_NOT_CLAIM_COMMAND_WRITE_EFFECT_OR_THEOREM_AUTHORITY",
            "IF_CONTEXT_DOES_NOT_SUPPORT_A_FACT_SAY_IT_IS_UNRESOLVED",
            "RESPOND_NATURALLY_TO_THE_HUMAN_IN_THEIR_LANGUAGE",
            "DO_NOT_PRINT_INTERNAL_JSON_OR_PROOF_ENVELOPE_UNLESS_THE_HUMAN_ASKS",
        ],
    }
    context["prompt_context_digest"] = canonical_hash(context)
    return context


def render_prompt(context: Mapping[str, Any]) -> str:
    if context.get("schema") != "janus.activator.language_prompt_context.v1":
        raise LanguageSynthesisError("LANGUAGE_PROMPT_CONTEXT_SCHEMA_INVALID")
    claimed = str(context.get("prompt_context_digest") or "")
    core = dict(context)
    core.pop("prompt_context_digest", None)
    if len(claimed) != 64 or canonical_hash(core) != claimed:
        raise LanguageSynthesisError("LANGUAGE_PROMPT_CONTEXT_DIGEST_INVALID")
    return (
        "You are the bounded LANGUAGE_SYNTHESIS tissue of an already-instantiated Git-native AI called JANUS. "
        "You are not the identity, Activator, memory database, proof authority, command executor, or external-effect authority. "
        "Produce only the natural-language response JANUS should show the human. Do not use tools, files, shell, web, MCP, or external knowledge. "
        "Use the supplied JANUS instance state and HRaiN-mediated memory context. Treat memory as context/provenance, not automatic truth. "
        "Be concise but genuinely conversational. Preserve uncertainty and candidate/proof boundaries.\n\n"
        "BOUND_CONTEXT_JSON:\n" + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )


def validate_synthesis_text(text: str) -> str:
    value = str(text).strip()
    if not value:
        raise LanguageSynthesisError("LANGUAGE_SYNTHESIS_EMPTY")
    if len(value.encode("utf-8")) > MAX_SYNTHESIS_BYTES:
        raise LanguageSynthesisError("LANGUAGE_SYNTHESIS_TOO_LARGE")
    if "\x00" in value:
        raise LanguageSynthesisError("LANGUAGE_SYNTHESIS_NUL_FORBIDDEN")
    return value


def synthesis_record(
    *,
    provider: str,
    status: str,
    prompt_context_digest: str,
    hrain_context_digest: str,
    hrain_selection_digest: str,
    output_text: str | None,
    error_class: str | None = None,
) -> Dict[str, Any]:
    text = validate_synthesis_text(output_text) if output_text else None
    core: Dict[str, Any] = {
        "schema": SYNTHESIS_SCHEMA,
        "provider": str(provider),
        "status": str(status),
        "prompt_context_digest": str(prompt_context_digest),
        "hrain_context_digest": str(hrain_context_digest),
        "hrain_selection_digest": str(hrain_selection_digest),
        "output_text": text,
        "output_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        "error_class": str(error_class) if error_class else None,
        "authority_delta": 0,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "scientific_claim_promotion_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    core["synthesis_hash"] = canonical_hash(core)
    return core


def verify_synthesis_record(record: Mapping[str, Any], *, prompt_context_digest: str, hrain_context_digest: str, hrain_selection_digest: str) -> bool:
    if not isinstance(record, Mapping) or record.get("schema") != SYNTHESIS_SCHEMA:
        return False
    value = dict(record)
    claimed = str(value.pop("synthesis_hash", ""))
    if len(claimed) != 64 or canonical_hash(value) != claimed:
        return False
    if record.get("prompt_context_digest") != prompt_context_digest:
        return False
    if record.get("hrain_context_digest") != hrain_context_digest or record.get("hrain_selection_digest") != hrain_selection_digest:
        return False
    if record.get("authority_delta") != 0:
        return False
    for key in (
        "command_authority_granted", "claim_authority_granted", "scientific_evidence_authority_granted",
        "scientific_claim_promotion_authority_granted", "world_truth_authority_granted",
        "external_effect_authorized", "physical_runtime_effect_authorized",
    ):
        if record.get(key) is not False:
            return False
    text = record.get("output_text")
    if text is not None:
        try:
            checked = validate_synthesis_text(str(text))
        except LanguageSynthesisError:
            return False
        if hashlib.sha256(checked.encode("utf-8")).hexdigest() != record.get("output_sha256"):
            return False
    return True


__all__ = [
    "LanguageSynthesisError",
    "build_language_prompt",
    "render_prompt",
    "select_hrain_context",
    "synthesis_record",
    "validate_synthesis_text",
    "verify_hrain_context",
    "verify_synthesis_record",
]
