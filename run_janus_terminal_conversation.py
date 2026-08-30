#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from janus_spi.activator import ActivationEvent, canonical_hash
from janus_spi.file_fabric import FileFabricCompiler, GitHubTreeReader
from janus_spi.live_cycle import HardenedJanusPersistentStateV09
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12
from janus_spi.model_runtime import ModelBoundJanusRuntime
from janus_spi.persistent_state import JanusPersistentState
from janus_spi.terminal_conversation import (
    build_terminal_response,
    verify_terminal_message,
    verify_terminal_response,
)


def _write_json(path: str | Path, value) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hearth_append(state, *, event: str, cycle_id: str, payload: dict) -> dict:
    return state.hearth.append({
        "schema": "janus.activator.terminal_conversation_hearth_receipt.v1",
        "event": event,
        "parent_hearth_hash": state.hearth.tip_hash(),
        "cycle_id": cycle_id,
        "resident_id": "JANUS",
        "fresh_stimulus": True,
        "cognition_authorized": True,
        "dispatch_authorized": False,
        "target_execution_authorized": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "payload": payload,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Process one sealed Terminal message as a persistent model-bound JANUS conversation turn")
    parser.add_argument("--request", required=True)
    parser.add_argument("--resident-identity", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    parser.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    parser.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    parser.add_argument("--registry", default="config/JANUS_FILE_FORMAT_REGISTRY-v1.json")
    parser.add_argument("--model-lock-out", default="runtime/terminal-model-lock.json")
    parser.add_argument("--file-fabric-out", default="runtime/terminal-file-fabric-lock.json")
    parser.add_argument("--runtime-receipt-out", default="runtime/terminal-runtime-receipt.json")
    parser.add_argument("--response-out", default="runtime/terminal-response.json")
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    if not verify_terminal_message(request):
        raise SystemExit("TERMINAL_REQUEST_INTEGRITY_FAILED")

    identity = json.loads(Path(args.resident_identity).read_text(encoding="utf-8"))
    if not JanusPersistentState.verify_identity(identity):
        raise SystemExit("PERSISTENT_JANUS_IDENTITY_INVALID")
    resident_uuid = str(identity["resident_uuid"])

    state_dir = Path(args.state_dir)
    state = HardenedJanusPersistentStateV09(state_dir)
    health_before = state.verify()
    if health_before.get("ok") is not True or health_before.get("mode") != "AT_HOME":
        raise SystemExit("TERMINAL_CONVERSATION_HOME_NOT_HEALTHY_AT_HOME")
    if health_before.get("resident_uuid") != resident_uuid:
        raise SystemExit("TERMINAL_CONVERSATION_RESIDENT_IDENTITY_MISMATCH")

    persistent_response = state_dir / "terminal_conversation_responses" / f"{request['message_id']}.json"
    if persistent_response.exists():
        previous = json.loads(persistent_response.read_text(encoding="utf-8"))
        if not verify_terminal_response(previous, request=request):
            raise SystemExit("PERSISTENT_TERMINAL_RESPONSE_INVALID")
        if previous.get("resident_uuid") != resident_uuid:
            raise SystemExit("PERSISTENT_TERMINAL_RESPONSE_RESIDENT_MISMATCH")
        _write_json(args.response_out, previous)
        print(json.dumps({
            "terminal": "JANUS_TERMINAL_CONVERSATION_RESPONSE_REPLAYED_NO_NEW_COGNITION",
            "message_id": request["message_id"],
            "response_id": previous["response_id"],
            "resident_uuid": resident_uuid,
            "model_digest": previous["model_digest"],
            "file_fabric_digest": previous["file_fabric_digest"],
            "turn_id": previous["turn_id"],
            "mode": "AT_HOME",
            "retry_delivery_is_new_cognition": False,
            "command_authority_granted": False,
            "external_effect_authorized": False,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    cycle_id = "terminal-cycle-" + canonical_hash({
        "resident_uuid": resident_uuid,
        "request_message_hash": request["message_hash"],
        "parent_hearth_hash": state.hearth.tip_hash(),
    })
    wake = _hearth_append(state, event="WAKE_TERMINAL_CONVERSATION", cycle_id=cycle_id, payload={
        "message_id": request["message_id"],
        "message_hash": request["message_hash"],
        "source_ref": request["source_ref"],
    })
    state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=wake["receipt_hash"])

    model_lock = ModelFabricCompilerV12.from_file(
        args.manifest,
        reader=GitHubRepositoryReaderV11(),
    ).compile()
    if model_lock.get("ready") is not True:
        raise SystemExit("JANUS_MODEL_LOCK_NOT_READY")
    _write_json(args.model_lock_out, model_lock)

    file_fabric = FileFabricCompiler.from_file(
        args.registry,
        reader=GitHubTreeReader(),
    ).compile(model_lock)
    if file_fabric.get("ready") is not True:
        raise SystemExit("JANUS_FILE_FABRIC_NOT_READY")
    _write_json(args.file_fabric_out, file_fabric)

    event = ActivationEvent.build(
        source_kind="TERMINAL_HUMAN_CONVERSATION",
        source_ref=str(request["source_ref"]),
        payload=request,
        classifications=["human_read_only_conversation"],
        fresh=True,
        self_generated=False,
        command_authority=False,
        effect_authorized=False,
    )
    runtime = ModelBoundJanusRuntime(
        model_lock,
        state_dir=state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
    )
    runtime_receipt = runtime.activate(event)
    if runtime_receipt.get("terminal") != "JANUS_MODEL_BOUND_ROUTE_PROPOSED":
        raise SystemExit("TERMINAL_CONVERSATION_ROUTE_NOT_PROPOSED")
    active_organs = list(runtime_receipt.get("active_organs") or [])
    if not active_organs:
        raise SystemExit("TERMINAL_CONVERSATION_ACTIVE_ORGANS_REQUIRED")
    _write_json(args.runtime_receipt_out, runtime_receipt)

    turn_id = "turn-" + str(runtime_receipt["runtime_receipt_hash"])
    excerpt = " ".join(str(request["message_text"]).split())[:240]
    trump = (model_lock.get("candidate_runtime_tissues") or {}).get("trump") or {}
    trump_state = str(trump.get("admission_status") or "NOT_PRESENT")
    response_text = (
        "JANUS ONLINE. Your Terminal message was received by the persistent JANUS resident "
        f"{resident_uuid}. Model {model_lock['model_digest'][:12]} / file-fabric "
        f"{file_fabric['file_fabric_digest'][:12]} opened a read-only conversation turn. "
        f"Active organs: {', '.join(active_organs)}. TRUMP candidate tissue: {trump_state}. "
        f"Received: {excerpt}"
    )
    response = build_terminal_response(
        request,
        resident_uuid=resident_uuid,
        model_lock=model_lock,
        file_fabric_lock=file_fabric,
        turn_id=turn_id,
        response_text=response_text,
        response_mode="MODEL_BOUND_SYSTEM_CONVERSATION_PROOF",
    )
    if not verify_terminal_response(response, request=request):
        raise SystemExit("TERMINAL_RESPONSE_SELF_VERIFY_FAILED")

    persistent_response.parent.mkdir(parents=True, exist_ok=True)
    if persistent_response.exists():
        raise SystemExit("TERMINAL_RESPONSE_CREATE_ONLY_CONFLICT")
    _write_json(persistent_response, response)
    _write_json(args.response_out, response)

    checkpoint = _hearth_append(state, event="CHECKPOINT_TERMINAL_CONVERSATION", cycle_id=cycle_id, payload={
        "message_id": request["message_id"],
        "response_hash": response["response_hash"],
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "turn_id": turn_id,
        "active_organs": active_organs,
        "candidate_runtime_tissues": {
            key: row.get("admission_status")
            for key, row in (model_lock.get("candidate_runtime_tissues") or {}).items()
        },
    })
    state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=checkpoint["receipt_hash"])
    sleep = _hearth_append(state, event="SLEEP_TERMINAL_CONVERSATION_RETURN_HOME", cycle_id=cycle_id, payload={
        "message_id": request["message_id"],
        "response_hash": response["response_hash"],
        "return_not_reset": True,
    })
    state._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=sleep["receipt_hash"])

    health_after = state.verify()
    if health_after.get("ok") is not True or health_after.get("mode") != "AT_HOME":
        raise SystemExit("TERMINAL_CONVERSATION_HOME_INVALID_AFTER_RETURN")
    if health_after.get("resident_uuid") != resident_uuid:
        raise SystemExit("TERMINAL_CONVERSATION_RESIDENT_CHANGED")

    print(json.dumps({
        "terminal": response["terminal"],
        "cycle_id": cycle_id,
        "message_id": request["message_id"],
        "response_id": response["response_id"],
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "turn_id": turn_id,
        "active_organs": active_organs,
        "candidate_runtime_tissues": {
            key: row.get("admission_status")
            for key, row in (model_lock.get("candidate_runtime_tissues") or {}).items()
        },
        "wake_hash": wake["receipt_hash"],
        "checkpoint_hash": checkpoint["receipt_hash"],
        "sleep_hash": sleep["receipt_hash"],
        "mode": "AT_HOME",
        "return_not_reset": True,
        "retry_delivery_is_new_cognition": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
