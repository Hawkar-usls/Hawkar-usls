import json
from pathlib import Path

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.turing_gate_arm import TuringGateArmError, arm_status, consume_arm, verify_arm


def arm():
    return {
        "schema": "janus.activator.turing_style_gate_arm.v1",
        "arm_id": "T-ARM-1",
        "gate_id": "G",
        "armed": True,
        "one_shot": True,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }


def witness(*, suffix="1"):
    session = {"gate_id":"G","session_hash":("a" if suffix == "1" else "b") * 64}
    transcript = {"transcript_hash":("c" if suffix == "1" else "d") * 64}
    result = {
        "gate_id":"G",
        "session_hash":session["session_hash"],
        "result_hash":("e" if suffix == "1" else "f") * 64,
        "transcript_hash":transcript["transcript_hash"],
        "terminal":"JANUS_TURING_STYLE_MACHINE_GATE_READY_FOR_HUMAN_BLIND_JUDGMENT",
        "machine_gate_ready":True,
        "human_blind_adjudication_required":True,
        "classical_turing_verdict":"NOT_ADJUDICATED",
        "resident_uuid":"75e514ab-be76-42c8-bcb3-fc9670164f96",
        "model_digest":"1" * 64,
        "command_authority_granted":False,
        "external_effect_authorized":False,
    }
    return session, result, transcript


def test_unconsumed_arm_is_runnable(tmp_path):
    assert verify_arm(arm())
    status = arm_status(arm(), state_dir=tmp_path)
    assert status["should_run"] is True and status["consumed"] is False


def test_successful_machine_ready_witness_consumes_once(tmp_path):
    session, result, transcript = witness()
    status = consume_arm(arm(), state_dir=tmp_path, session=session, result=result, transcript=transcript)
    assert status["consumed"] is True and status["should_run"] is False
    assert status["session_hash"] == session["session_hash"]
    again = consume_arm(arm(), state_dir=tmp_path, session=session, result=result, transcript=transcript)
    assert again["consumed"] is True
    assert len((tmp_path / "turing_style_gate_arm_ledger.jsonl").read_text().splitlines()) == 1


def test_different_second_witness_is_blocked(tmp_path):
    s1, r1, t1 = witness()
    consume_arm(arm(), state_dir=tmp_path, session=s1, result=r1, transcript=t1)
    s2, r2, t2 = witness(suffix="2")
    with pytest.raises(TuringGateArmError, match="DIFFERENT_WITNESS"):
        consume_arm(arm(), state_dir=tmp_path, session=s2, result=r2, transcript=t2)


def test_failed_machine_gate_does_not_consume(tmp_path):
    session, result, transcript = witness()
    result["machine_gate_ready"] = False
    result["terminal"] = "JANUS_TURING_STYLE_MACHINE_GATE_FAILED"
    with pytest.raises(TuringGateArmError, match="MACHINE_READY"):
        consume_arm(arm(), state_dir=tmp_path, session=session, result=result, transcript=transcript)
    assert arm_status(arm(), state_dir=tmp_path)["should_run"] is True


def test_self_awarded_classical_verdict_cannot_consume(tmp_path):
    session, result, transcript = witness()
    result["classical_turing_verdict"] = "PASS"
    with pytest.raises(TuringGateArmError, match="HUMAN_GATE_INVALID"):
        consume_arm(arm(), state_dir=tmp_path, session=session, result=result, transcript=transcript)


def test_transcript_mismatch_blocks_consumption(tmp_path):
    session, result, transcript = witness()
    transcript["transcript_hash"] = "9" * 64
    with pytest.raises(TuringGateArmError, match="TRANSCRIPT_BINDING"):
        consume_arm(arm(), state_dir=tmp_path, session=session, result=result, transcript=transcript)


def test_tampered_ledger_fails_closed(tmp_path):
    path = tmp_path / "turing_style_gate_arm_ledger.jsonl"
    path.write_text(json.dumps({"schema":"janus.activator.turing_style_gate_arm_ledger_entry.v1","entry_hash":"0"*64})+"\n")
    with pytest.raises(TuringGateArmError, match="ENTRY_HASH_INVALID"):
        arm_status(arm(), state_dir=tmp_path)
