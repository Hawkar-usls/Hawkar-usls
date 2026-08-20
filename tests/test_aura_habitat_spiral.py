from __future__ import annotations

from pathlib import Path

from janus_spi.aura_habitat_spiral import AURA_REFLECTION_SCHEMA, SpiralDialogueEngine


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


def test_verified_intent_pass_advances_spiral_without_predictive_training(tmp_path: Path):
    engine = SpiralDialogueEngine(state_dir=tmp_path / "state", aura_peer=FakeAura())
    intent_id = "a" * 64
    receipt = engine.cycle(
        trigger_text="new measured evidence",
        source_ref="TEST_MEASUREMENT",
        intent_id=intent_id,
        intent_authority="DEMIHEAD_GOLDPROMPT_VERIFIED",
        demihead_decision="PASS",
    )
    assert receipt["terminal"] == "VERIFIED_RETURN"
    assert receipt["chain_valid"] is True
    assert receipt["predictive_model_updated"] is False
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
