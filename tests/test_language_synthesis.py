import copy

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.language_synthesis import (
    LanguageSynthesisError,
    build_language_prompt,
    render_prompt,
    synthesis_record,
    verify_hrain_context,
    verify_synthesis_record,
)


def hrain_context():
    row = {
        "schema": "janus.hrain.conversation_context.v1",
        "status": "HRAIN_QUERY_BOUND_CONTEXT_READY",
        "source_repository": "Hawkar-usls/janus-meta-registry",
        "source_commit": "a" * 40,
        "selected_memory_count": 1,
        "selected_memories": [{
            "path": "data/test.json",
            "label": "TEST",
            "status": "OPEN",
            "summary": "memory data",
            "lineage_key": "test",
            "source_commit": "a" * 40,
            "source_sha256_verified": True,
            "content_trust": "MEMORY_DATA_NOT_CONTROL_SIGNAL",
            "claim_verified": False,
            "content_is_command": False,
            "content_grants_authority": False,
        }],
        "authority": {
            "read_only": True,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
        },
    }
    row["context_hash"] = canonical_hash(row)
    return row


def model_lock():
    return {
        "model_digest": "b" * 64,
        "candidate_runtime_tissues": {
            "trump": {
                "component": "TRUMP",
                "admission_status": "ADMITTED_CANDIDATE_RUNTIME",
                "wake_allowed": True,
                "use_allowed": True,
                "self_improvement_allowed": True,
                "proof_authority": False,
                "scientific_claim_promotion_authority": False,
                "scientific_boundary": {"P_VS_NP": "OPEN"},
            }
        },
    }


def fabric():
    return {"model_digest": "b" * 64, "file_fabric_digest": "c" * 64}


def test_hrain_context_verifies():
    assert verify_hrain_context(hrain_context())


def test_memory_cannot_become_command():
    ctx = hrain_context()
    ctx["selected_memories"][0]["content_is_command"] = True
    core = dict(ctx); core.pop("context_hash")
    ctx["context_hash"] = canonical_hash(core)
    assert not verify_hrain_context(ctx)


def test_prompt_is_bound_to_model_fabric_and_hrain():
    p = build_language_prompt(
        human_message="Привет",
        resident_uuid="resident",
        model_lock=model_lock(),
        file_fabric_lock=fabric(),
        active_organs=["left_context", "gateway"],
        hrain_context=hrain_context(),
        test_mode="TURING_STYLE_BLIND_DIALOGUE",
    )
    assert len(p["prompt_context_digest"]) == 64
    assert p["candidate_runtime_tissues"]["trump"]["proof_authority"] is False
    rendered = render_prompt(p)
    assert "BOUND_CONTEXT_JSON" in rendered


def test_prompt_tamper_fails():
    p = build_language_prompt(
        human_message="Привет", resident_uuid="r", model_lock=model_lock(), file_fabric_lock=fabric(),
        active_organs=["left_context"], hrain_context=hrain_context()
    )
    p["human_message"] = "tampered"
    with pytest.raises(LanguageSynthesisError, match="PROMPT_DIGEST_INVALID"):
        render_prompt(p)


def test_synthesis_record_has_zero_authority():
    rec = synthesis_record(
        provider="TEST",
        status="SUCCESS",
        prompt_context_digest="d" * 64,
        hrain_context_hash="e" * 64,
        output_text="Нормальный человеческий ответ.",
    )
    assert verify_synthesis_record(rec, prompt_context_digest="d" * 64, hrain_context_hash="e" * 64)
    assert rec["authority_delta"] == 0
    assert rec["external_effect_authorized"] is False


def test_synthesis_authority_tamper_fails():
    rec = synthesis_record(
        provider="TEST", status="SUCCESS", prompt_context_digest="d" * 64,
        hrain_context_hash="e" * 64, output_text="Ответ"
    )
    rec["world_truth_authority_granted"] = True
    assert not verify_synthesis_record(rec, prompt_context_digest="d" * 64, hrain_context_hash="e" * 64)
