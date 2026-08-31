import argparse
import json
from pathlib import Path

import run_janus_turing_gate_v2 as gate_v2


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_fixture(tmp_path, *, provider_ok=False, error_class="COPILOT_MONTHLY_QUOTA_EXHAUSTED"):
    config = {
        "schema": "janus.activator.turing_style_gate.v1",
        "gate_id": "R2",
        "machine_gate": {
            "max_answer_utf8_bytes": 4000,
            "forbidden_internal_leaks": [],
            "minimum_distinct_answers": 1,
            "provider_failure_verdict": "PROVIDER_UNAVAILABLE__NO_CONTEXTUAL_MIND_PROBE_WITNESS",
        },
    }
    prepared = tmp_path / "prepared"
    responses = tmp_path / "responses"
    prepared.mkdir(); responses.mkdir()
    write(tmp_path / "config.json", config)
    write(prepared / "session.json", {
        "schema": "janus.activator.turing_style_prepared_session.v1",
        "gate_id": "R2",
        "claim_boundary": "CONTEXTUAL_INTEGRATION_NOT_CONSCIOUSNESS_PROOF",
        "resident_uuid": "75e514ab-be76-42c8-bcb3-fc9670164f96",
        "model_digest": "a" * 64,
        "file_fabric_digest": "b" * 64,
        "question_count": 1,
        "questions": [{
            "id": "mind01",
            "text": "Да, вчера",
            "conversation_history": [{"role":"assistant","content":"Может ли кремниевый процессор обрести чувства?"}],
            "probe": {
                "probe_id": "DA-VCHERA",
                "kind": "CONTEXTUAL_ELLIPSIS_TEMPORAL_GROUNDING",
                "consciousness_claim_forbidden": True,
            },
            "prompt_context_digest": "c" * 64,
            "hrain_context_hash": "d" * 64,
        }],
        "session_hash": "e" * 64,
    })
    write(prepared / "mind01.prompt.json", {
        "prompt_context_digest": "c" * 64,
        "resident_uuid": "75e514ab-be76-42c8-bcb3-fc9670164f96",
        "model_digest": "a" * 64,
    })
    if provider_ok:
        (responses / "mind01.txt").write_text("Если это не шутка, расскажи, что именно произошло вчера?", encoding="utf-8")
    else:
        (responses / "mind01.txt").write_text("", encoding="utf-8")
    write(tmp_path / "provider.json", {
        "provider": "GITHUB_COPILOT_CLI",
        "model": "claude-haiku-4.5",
        "all_provider_calls_succeeded": provider_ok,
        "error_class": None if provider_ok else error_class,
    })
    return argparse.Namespace(
        config=str(tmp_path / "config.json"),
        prepared_dir=str(prepared),
        responses_dir=str(responses),
        provider_status=str(tmp_path / "provider.json"),
        transcript_out=str(tmp_path / "transcript.json"),
        result_out=str(tmp_path / "result.json"),
    )


def test_provider_quota_failure_does_not_erase_frozen_probe(tmp_path):
    args = make_fixture(tmp_path)
    assert gate_v2.adjudicate(args) == 0
    result = json.loads(Path(args.result_out).read_text())
    probe = result["contextual_mind_probe"]
    assert result["machine_gate_ready"] is False
    assert result["terminal"] == "PROVIDER_UNAVAILABLE__NO_CONTEXTUAL_MIND_PROBE_WITNESS"
    assert result["provider_model"] == "claude-haiku-4.5"
    assert result["provider_error_class"] == "COPILOT_MONTHLY_QUOTA_EXHAUSTED"
    assert result["provider_quota_exhausted"] is True
    assert probe["present"] is True
    assert probe["probe_count"] == 1
    assert probe["semantic_verdict"] == "NOT_ADJUDICATED"
    assert probe["consciousness_verdict"] == "NOT_ESTABLISHED_BY_DIALOGUE_PROBE"
    assert probe["human_adjudication_required"] is True
    assert probe["probes"][0]["probe_id"] == "DA-VCHERA"


def test_success_keeps_probe_boundary_and_records_projection_model(tmp_path):
    args = make_fixture(tmp_path, provider_ok=True)
    assert gate_v2.adjudicate(args) == 0
    result = json.loads(Path(args.result_out).read_text())
    probe = result["contextual_mind_probe"]
    assert result["provider_success"] is True
    assert result["machine_gate_ready"] is True
    assert result["provider_model"] == "claude-haiku-4.5"
    assert result["provider_quota_exhausted"] is False
    assert result["classical_turing_verdict"] == "NOT_ADJUDICATED"
    assert probe["semantic_verdict"] == "NOT_ADJUDICATED"
    assert probe["consciousness_verdict"] == "NOT_ESTABLISHED_BY_DIALOGUE_PROBE"


def test_no_probe_session_remains_not_applicable(tmp_path):
    args = make_fixture(tmp_path, provider_ok=True)
    session_path = Path(args.prepared_dir) / "session.json"
    session = json.loads(session_path.read_text())
    session["questions"][0]["probe"] = None
    write(session_path, session)
    gate_v2.adjudicate(args)
    result = json.loads(Path(args.result_out).read_text())
    assert result["contextual_mind_probe"]["present"] is False
    assert result["contextual_mind_probe"]["semantic_verdict"] == "NOT_APPLICABLE"
