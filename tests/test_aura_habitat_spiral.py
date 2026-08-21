from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from janus_spi.advancing_spiral import AdvancingSpiralDialogueEngine
from janus_spi.aura_habitat_spiral import AURA_REFLECTION_SCHEMA, SpiralDialogueEngine, sha256


class FakeAura:
    def reflect(self, packet):
        return {
            "schema": AURA_REFLECTION_SCHEMA,
            "status": "REFLECTION_READY",
            "session_id": packet["session_id"],
            "generation": packet["generation"],
            "intent_id": packet["intent_id"],
            "reflection_text": "Mirror the structure, attack the attractive interpretation, choose a discriminating next gate.",
            "cards": [],
            "predictive_label_authority": False,
            "scientific_evidence_authority": False,
            "may_train_semantic_memory": True,
            "may_train_predictive_head": False,
            "may_resolve_forecast": False,
            "may_replace_primary_intent": False,
            "claim_ceiling": "SYMBOLIC_REFLECTION_ONLY",
        }


def _valid_arbitration_receipt(*, session_id: str, generation: int, intent_id: str):
    origin_hash = "1" * 64
    candidate_hash = "2" * 64
    delta_hash = "3" * 64
    unsigned = {
        "schema": "janus.aura_spi.demihead_arbitration.v1",
        "session_id": session_id,
        "generation": generation,
        "intent_id": intent_id,
        "decision": "PASS",
        "intent_authority": "DEMIHEAD_GOLDPROMPT_VERIFIED",
        "verified_return_eligible": True,
        "external_effect_authorized": False,
        "authority_delta": 0,
        "state_advance_gate": {"candidate_valid": True},
    }
    return {
        **unsigned,
        "arbitration_sha256": sha256(unsigned),
        "verified_return": {
            "schema": "janus.aura_spi.verified_return.v1",
            "session_id": session_id,
            "generation": generation,
            "intent_id": intent_id,
            "origin_state_hash": origin_hash,
            "candidate_state_hash": candidate_hash,
            "state_delta_sha256": delta_hash,
            "parent_origin_state_hash": origin_hash,
        },
    }


def test_preview_pass_cannot_promote_origin_prime(tmp_path: Path):
    engine = SpiralDialogueEngine(state_dir=tmp_path / "state", aura_peer=FakeAura())
    receipt = engine.cycle(
        trigger_text="fresh external event",
        source_ref="TEST",
        demihead_decision="PASS",
        intent_authority="LOCAL_PREVIEW",
    )
    assert receipt["terminal"] == "HOLD"
    assert receipt["chain_valid"] is True
    assert receipt["predictive_model_updated"] is False
    stages = [turn.stage for turn in engine.dialogue.iter_turns(receipt["session_id"])]
    assert "ORIGIN_PRIME" not in stages


def test_verified_intent_bare_pass_still_holds_without_arbitration_receipt(tmp_path: Path):
    engine = SpiralDialogueEngine(state_dir=tmp_path / "state", aura_peer=FakeAura())
    intent_id = "a" * 64
    receipt = engine.cycle(
        trigger_text="new measured evidence",
        source_ref="TEST_MEASUREMENT",
        intent_id=intent_id,
        intent_authority="DEMIHEAD_GOLDPROMPT_VERIFIED",
        demihead_decision="PASS",
    )
    assert receipt["terminal"] == "HOLD"
    assert receipt["chain_valid"] is True
    assert receipt["predictive_model_updated"] is False
    stages = [turn.stage for turn in engine.dialogue.iter_turns(receipt["session_id"])]
    assert "ORIGIN_PRIME" not in stages


def test_hash_valid_arbitration_advances_through_preferred_spiral_api(tmp_path: Path):
    engine = AdvancingSpiralDialogueEngine(state_dir=tmp_path / "state", aura_peer=FakeAura())
    intent_id = "b" * 64
    session_id = "verified-session"
    arbitration = _valid_arbitration_receipt(session_id=session_id, generation=1, intent_id=intent_id)

    receipt = engine.spiral_step(
        trigger_text="new measured evidence with bound DemiHead receipt",
        source_ref="TEST_MEASUREMENT",
        intent_id=intent_id,
        session_id=session_id,
        intent_authority="DEMIHEAD_GOLDPROMPT_VERIFIED",
        demihead_decision="PASS",
        demihead_arbitration_receipt=arbitration,
    )
    assert receipt["terminal"] == "VERIFIED_RETURN"
    assert receipt["chain_valid"] is True
    assert receipt["predictive_model_updated"] is False
    assert receipt["demihead_arbitration_receipt_forwarded"] is True
    stages = [turn.stage for turn in engine.dialogue.iter_turns(receipt["session_id"])]
    assert stages[-1] == "ORIGIN_PRIME"


def test_empty_trigger_rejected(tmp_path: Path):
    engine = SpiralDialogueEngine(state_dir=tmp_path / "state", aura_peer=FakeAura())
    try:
        engine.cycle(trigger_text="   ", source_ref="TEST")
    except ValueError as exc:
        assert "FRESH_EXTERNAL_TRIGGER_REQUIRED" in str(exc)
    else:
        raise AssertionError("empty trigger must fail closed")
