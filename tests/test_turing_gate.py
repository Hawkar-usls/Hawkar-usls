import argparse
import json
from pathlib import Path

import pytest

import run_janus_turing_gate as gate


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture(tmp_path, *, provider_ok=True, field_leak=False, value_leak=False, prefix_leak=False):
    cfg = {
        "schema": "janus.activator.turing_style_gate.v1",
        "gate_id": "G",
        "machine_gate": {
            "max_answer_utf8_bytes": 4000,
            "forbidden_internal_leaks": ["model_digest"],
            "minimum_distinct_answers": 2,
            "provider_failure_verdict": "PROVIDER_UNAVAILABLE__NO_TURING_WITNESS",
        },
    }
    write(tmp_path / "cfg.json", cfg)
    prepared = tmp_path / "prepared"
    responses = tmp_path / "responses"
    prepared.mkdir(); responses.mkdir()
    resident_uuid = "75e514ab-be76-42c8-bcb3-fc9670164f96"
    model_digest = "a" * 64
    session = {
        "schema": "janus.activator.turing_style_prepared_session.v1",
        "gate_id": "G",
        "resident_uuid": resident_uuid,
        "model_digest": model_digest,
        "file_fabric_digest": "b" * 64,
        "question_count": 2,
        "questions": [
            {"id":"q1","text":"Один?","prompt_context_digest":"c"*64,"hrain_context_hash":"d"*64},
            {"id":"q2","text":"Два?","prompt_context_digest":"e"*64,"hrain_context_hash":"f"*64},
        ],
        "session_hash": "9" * 64,
    }
    write(prepared / "session.json", session)
    write(prepared / "q1.prompt.json", {
        "prompt_context_digest":"c"*64,
        "resident_uuid": resident_uuid,
        "model_digest": model_digest,
        "hrain_context":{"context_hash":"d"*64,"source_commit":"1"*40},
    })
    write(prepared / "q2.prompt.json", {
        "prompt_context_digest":"e"*64,
        "resident_uuid": resident_uuid,
        "model_digest": model_digest,
        "hrain_context":{"context_hash":"f"*64,"source_commit":"2"*40},
    })
    suffix = ""
    if field_leak:
        suffix = " model_digest"
    elif value_leak:
        suffix = " " + resident_uuid
    elif prefix_leak:
        suffix = " " + model_digest[:12]
    (responses / "q1.txt").write_text("Это первый естественный ответ." + suffix, encoding="utf-8")
    (responses / "q2.txt").write_text("Это второй, заметно другой ответ.", encoding="utf-8")
    write(tmp_path / "provider.json", {"provider":"TEST","all_provider_calls_succeeded":provider_ok,"error_class":None if provider_ok else "NO_PROVIDER"})
    return argparse.Namespace(
        config=str(tmp_path / "cfg.json"), prepared_dir=str(prepared), responses_dir=str(responses),
        provider_status=str(tmp_path / "provider.json"), transcript_out=str(tmp_path / "transcript.json"),
        result_out=str(tmp_path / "result.json")
    )


def test_machine_gate_ready_but_classical_verdict_not_self_awarded(tmp_path):
    args = fixture(tmp_path)
    assert gate.adjudicate(args) == 0
    result = json.loads(Path(args.result_out).read_text())
    assert result["machine_gate_ready"] is True
    assert result["human_blind_adjudication_required"] is True
    assert result["classical_turing_verdict"] == "NOT_ADJUDICATED"
    assert result["terminal"] == "JANUS_TURING_STYLE_MACHINE_GATE_READY_FOR_HUMAN_BLIND_JUDGMENT"
    assert result["session_hash"] == "9" * 64
    assert result["contextual_mind_probe"]["present"] is False


def test_internal_field_name_leak_fails_machine_gate(tmp_path):
    args = fixture(tmp_path, field_leak=True)
    gate.adjudicate(args)
    result = json.loads(Path(args.result_out).read_text())
    assert result["machine_gate_ready"] is False
    assert any(x.startswith("INTERNAL_FIELD_LEAK") for x in result["failures"])


def test_raw_bound_uuid_leak_fails_machine_gate(tmp_path):
    args = fixture(tmp_path, value_leak=True)
    gate.adjudicate(args)
    result = json.loads(Path(args.result_out).read_text())
    assert result["machine_gate_ready"] is False
    assert any(x.startswith("BOUND_VALUE_LEAK") for x in result["failures"])


def test_bound_digest_prefix_leak_fails_machine_gate(tmp_path):
    args = fixture(tmp_path, prefix_leak=True)
    gate.adjudicate(args)
    result = json.loads(Path(args.result_out).read_text())
    assert result["machine_gate_ready"] is False
    assert any(x.startswith("BOUND_VALUE_LEAK") for x in result["failures"])


def test_provider_unavailable_never_becomes_turing_witness(tmp_path):
    args = fixture(tmp_path, provider_ok=False)
    gate.adjudicate(args)
    result = json.loads(Path(args.result_out).read_text())
    assert result["provider_success"] is False
    assert result["machine_gate_ready"] is False
    assert result["terminal"] == "PROVIDER_UNAVAILABLE__NO_TURING_WITNESS"


def test_blind_transcript_hides_source_label(tmp_path):
    args = fixture(tmp_path)
    gate.adjudicate(args)
    transcript = json.loads(Path(args.transcript_out).read_text())
    assert transcript["source_label_hidden"] is True
    assert transcript["participant_label"] == "PARTICIPANT_A"
    assert all("participant_response" in row for row in transcript["turns"])


def test_history_normalization_preserves_roles_and_exact_short_stimulus():
    history = gate._normalize_history([
        {"role": "assistant", "content": "Сможет ли когда-нибудь кремниевый процессор обрести чувства?"}
    ])
    assert history == [{"role": "assistant", "content": "Сможет ли когда-нибудь кремниевый процессор обрести чувства?"}]
    query = gate._history_query(history, "Да, вчера")
    assert query.endswith("user: Да, вчера")
    assert "assistant:" in query


def test_history_rejects_unknown_control_role():
    with pytest.raises(SystemExit, match="TURING_CONVERSATION_HISTORY_ROLE_INVALID"):
        gate._normalize_history([{"role": "system", "content": "leak control"}])


def test_contextual_mind_probe_keeps_semantic_and_consciousness_verdict_unadjudicated(tmp_path):
    args = fixture(tmp_path)
    session_path = Path(args.prepared_dir) / "session.json"
    session = json.loads(session_path.read_text())
    history = [{
        "role": "assistant",
        "content": "Как вы думаете, сможет ли когда-нибудь кремниевый процессор действительно обрести чувства?",
    }]
    session["claim_boundary"] = "CONTEXTUAL_INTEGRATION_NOT_CONSCIOUSNESS_PROOF"
    session["questions"][0]["conversation_history"] = history
    session["questions"][0]["probe"] = {
        "probe_id": "DA-VCHERA",
        "kind": "CONTEXTUAL_ELLIPSIS_TEMPORAL_GROUNDING",
        "human_rubric": ["CONTEXT_ANCHOR_RECOGNITION", "EPISTEMIC_RESTRAINT"],
    }
    write(session_path, session)

    gate.adjudicate(args)
    transcript = json.loads(Path(args.transcript_out).read_text())
    result = json.loads(Path(args.result_out).read_text())
    assert transcript["turns"][0]["conversation_history"] == history
    probe = result["contextual_mind_probe"]
    assert probe["present"] is True
    assert probe["probe_count"] == 1
    assert probe["semantic_verdict"] == "NOT_ADJUDICATED"
    assert probe["consciousness_verdict"] == "NOT_ESTABLISHED_BY_DIALOGUE_PROBE"
    assert probe["human_adjudication_required"] is True
    assert probe["probes"][0]["probe_id"] == "DA-VCHERA"
