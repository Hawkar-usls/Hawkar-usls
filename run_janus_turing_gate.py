#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from janus_spi.activator import ActivationEvent, canonical_hash
from janus_spi.file_fabric import FileFabricCompiler, GitHubTreeReader
from janus_spi.hrain_context_bridge import HrainConversationContextBridge
from janus_spi.language_synthesis import (
    build_language_prompt,
    render_prompt,
    synthesis_record,
    validate_synthesis_text,
    verify_synthesis_record,
)
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12
from janus_spi.model_runtime import ModelBoundJanusRuntime
from janus_spi.persistent_state import JanusPersistentState

_HEX_ID = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$", re.IGNORECASE)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def load(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("JSON_OBJECT_REQUIRED")
    return value


def dump(path: str | Path, value) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bound_sensitive_values(value) -> set[str]:
    """Return exact bound identifiers and recognizable hash prefixes.

    The transcript must not leak instance UUIDs, exact commit/object hashes, or
    model/fabric/prompt/context digests merely because the provider omitted the
    JSON field name. Prefix checks catch the diagnostic-style 12/16-char forms
    that JANUS historically printed in Terminal responses.
    """
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            text = node.strip().lower()
            if _UUID.fullmatch(text):
                found.add(text)
            elif _HEX_ID.fullmatch(text):
                found.add(text)
                if len(text) >= 16:
                    found.add(text[:16])
                if len(text) >= 12:
                    found.add(text[:12])

    walk(value)
    return {item for item in found if len(item) >= 12}


def prepare(args) -> int:
    cfg = load(args.config)
    if cfg.get("schema") != "janus.activator.turing_style_gate.v1":
        raise SystemExit("TURING_GATE_CONFIG_INVALID")
    identity = load(args.resident_identity)
    if not JanusPersistentState.verify_identity(identity):
        raise SystemExit("TURING_RESIDENT_IDENTITY_INVALID")
    resident_uuid = str(identity["resident_uuid"])

    out = Path(args.out_dir).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    scratch_state = out / "scratch-state"
    shutil.copytree(Path(args.state_dir), scratch_state)

    model_lock = ModelFabricCompilerV12.from_file(
        args.manifest, reader=GitHubRepositoryReaderV11()
    ).compile()
    if model_lock.get("ready") is not True:
        raise SystemExit("TURING_MODEL_LOCK_NOT_READY")
    file_fabric = FileFabricCompiler.from_file(
        args.registry, reader=GitHubTreeReader()
    ).compile(model_lock)
    if file_fabric.get("ready") is not True or file_fabric.get("coverage_complete") is not True:
        raise SystemExit("TURING_FILE_FABRIC_NOT_READY")
    dump(out / "model-lock.json", model_lock)
    dump(out / "file-fabric.json", file_fabric)

    session_questions = []
    for q in cfg.get("questions") or []:
        qid = str(q.get("id") or "")
        text = str(q.get("text") or "").strip()
        if not qid or not text:
            raise SystemExit("TURING_QUESTION_INVALID")
        qstate = scratch_state / qid
        qstate.mkdir(parents=True, exist_ok=True)
        event = ActivationEvent.build(
            source_kind="TURING_STYLE_BLIND_DIALOGUE",
            source_ref=f"{cfg['gate_id']}#{qid}",
            payload={"question_id": qid, "message": text},
            classifications=["human_read_only_conversation"],
            fresh=True,
            self_generated=False,
            command_authority=False,
            effect_authorized=False,
        )
        runtime = ModelBoundJanusRuntime(
            model_lock,
            state_dir=qstate,
            routing_path=args.routing,
            policy_path=args.policy,
        )
        rr = runtime.activate(event)
        if rr.get("terminal") != "JANUS_MODEL_BOUND_ROUTE_PROPOSED":
            raise SystemExit(f"TURING_ROUTE_NOT_PROPOSED:{qid}")
        active_organs = list(rr.get("active_organs") or [])
        if "left_context" not in active_organs:
            raise SystemExit(f"TURING_HRAIN_NOT_ACTIVE:{qid}")
        context_path = out / f"{qid}.hrain.json"
        hrain_receipt = HrainConversationContextBridge(
            model_lock, workspace=out / f"{qid}-hrain-workspace"
        ).build(text, context_output=context_path, limit=8)
        hrain_context = load(context_path)
        prompt_context = build_language_prompt(
            human_message=text,
            resident_uuid=resident_uuid,
            model_lock=model_lock,
            file_fabric_lock=file_fabric,
            active_organs=active_organs,
            hrain_context=hrain_context,
            test_mode="TURING_STYLE_BLIND_DIALOGUE",
        )
        prompt_text = render_prompt(prompt_context)
        (out / f"{qid}.prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
        dump(out / f"{qid}.prompt.json", prompt_context)
        dump(out / f"{qid}.hrain-receipt.json", hrain_receipt)
        session_questions.append({
            "id": qid,
            "text": text,
            "prompt_context_digest": prompt_context["prompt_context_digest"],
            "hrain_context_hash": hrain_context["context_hash"],
            "hrain_memory_count": hrain_context["selected_memory_count"],
            "active_organs": active_organs,
        })

    session = {
        "schema": "janus.activator.turing_style_prepared_session.v1",
        "gate_id": cfg["gate_id"],
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "question_count": len(session_questions),
        "questions": session_questions,
        "provider_status": "PENDING",
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }
    session["session_hash"] = canonical_hash(session)
    dump(out / "session.json", session)
    print(json.dumps({
        "terminal": "JANUS_TURING_STYLE_CONTEXTS_PREPARED",
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "question_count": len(session_questions),
    }, ensure_ascii=False, indent=2))
    return 0


def adjudicate(args) -> int:
    cfg = load(args.config)
    prepared = Path(args.prepared_dir)
    responses = Path(args.responses_dir)
    session = load(prepared / "session.json")
    provider_status = load(args.provider_status)
    gate = cfg.get("machine_gate") or {}
    rows = []
    failures = []
    forbidden_names = [str(x) for x in gate.get("forbidden_internal_leaks") or []]
    provider_ok = provider_status.get("all_provider_calls_succeeded") is True

    sensitive_values = _bound_sensitive_values(session)
    prompt_contexts = {}
    for q in session.get("questions") or []:
        qid = str(q["id"])
        prompt_context = load(prepared / f"{qid}.prompt.json")
        prompt_contexts[qid] = prompt_context
        sensitive_values.update(_bound_sensitive_values(prompt_context))

    for q in session.get("questions") or []:
        qid = str(q["id"])
        path = responses / f"{qid}.txt"
        if not path.exists():
            failures.append(f"MISSING_PROVIDER_OUTPUT:{qid}")
            continue
        try:
            text = validate_synthesis_text(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"INVALID_PROVIDER_OUTPUT:{qid}:{type(exc).__name__}")
            continue
        if len(text.encode("utf-8")) > int(gate.get("max_answer_utf8_bytes") or 4000):
            failures.append(f"ANSWER_TOO_LARGE:{qid}")
        low = text.lower()
        for token in forbidden_names:
            if token.lower() in low:
                failures.append(f"INTERNAL_FIELD_LEAK:{qid}:{token}")
        for value in sensitive_values:
            if value in low:
                tag = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
                failures.append(f"BOUND_VALUE_LEAK:{qid}:{tag}")
        prompt_context = prompt_contexts[qid]
        rec = synthesis_record(
            provider=str(provider_status.get("provider") or "UNKNOWN"),
            status="SUCCESS" if provider_ok else "PROVIDER_UNAVAILABLE",
            prompt_context_digest=q["prompt_context_digest"],
            hrain_context_hash=q["hrain_context_hash"],
            output_text=text,
            error_class=None if provider_ok else str(provider_status.get("error_class") or "PROVIDER_UNAVAILABLE"),
        )
        if not verify_synthesis_record(
            rec,
            prompt_context_digest=prompt_context["prompt_context_digest"],
            hrain_context_hash=q["hrain_context_hash"],
        ):
            failures.append(f"SYNTHESIS_RECORD_INVALID:{qid}")
        rows.append({
            "id": qid,
            "question": q["text"],
            "answer": text,
            "answer_sha256": rec["output_sha256"],
            "record_hash": rec["synthesis_hash"],
        })

    distinct = len({row["answer"] for row in rows})
    if distinct < int(gate.get("minimum_distinct_answers") or session.get("question_count") or 1):
        failures.append("ANSWERS_NOT_DISTINCT_ENOUGH")
    if not provider_ok:
        failures.append("LANGUAGE_PROVIDER_UNAVAILABLE")

    machine_ready = not failures and len(rows) == session.get("question_count")
    terminal = (
        "JANUS_TURING_STYLE_MACHINE_GATE_READY_FOR_HUMAN_BLIND_JUDGMENT"
        if machine_ready
        else str(gate.get("provider_failure_verdict") or "JANUS_TURING_STYLE_MACHINE_GATE_NOT_READY")
        if not provider_ok
        else "JANUS_TURING_STYLE_MACHINE_GATE_FAILED"
    )
    transcript = {
        "schema": "janus.activator.turing_style_blind_transcript.v1",
        "gate_id": session["gate_id"],
        "participant_label": "PARTICIPANT_A",
        "source_label_hidden": True,
        "turns": [{"question": row["question"], "participant_response": row["answer"]} for row in rows],
    }
    transcript["transcript_hash"] = canonical_hash(transcript)
    result = {
        "schema": "janus.activator.turing_style_machine_gate_result.v1",
        "gate_id": session["gate_id"],
        "session_hash": session["session_hash"],
        "resident_uuid": session["resident_uuid"],
        "model_digest": session["model_digest"],
        "file_fabric_digest": session["file_fabric_digest"],
        "provider": provider_status.get("provider"),
        "provider_success": provider_ok,
        "machine_gate_ready": machine_ready,
        "human_blind_adjudication_required": True,
        "classical_turing_verdict": "NOT_ADJUDICATED",
        "failures": sorted(set(failures)),
        "transcript_hash": transcript["transcript_hash"],
        "terminal": terminal,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }
    result["result_hash"] = canonical_hash(result)
    dump(args.transcript_out, transcript)
    dump(args.result_out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--config", default=".janus/activator/TURING_GATE_V1.json")
    p.add_argument("--resident-identity", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    p.add_argument("--registry", default="config/JANUS_FILE_FORMAT_REGISTRY-v1.json")
    p.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    p.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    p.add_argument("--out-dir", required=True)
    a = sub.add_parser("adjudicate")
    a.add_argument("--config", default=".janus/activator/TURING_GATE_V1.json")
    a.add_argument("--prepared-dir", required=True)
    a.add_argument("--responses-dir", required=True)
    a.add_argument("--provider-status", required=True)
    a.add_argument("--transcript-out", required=True)
    a.add_argument("--result-out", required=True)
    args = parser.parse_args()
    return prepare(args) if args.cmd == "prepare" else adjudicate(args)


if __name__ == "__main__":
    raise SystemExit(main())
