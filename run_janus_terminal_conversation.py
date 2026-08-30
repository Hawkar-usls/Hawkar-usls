#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from janus_spi.activator import ActivationEvent
from janus_spi.file_fabric import FileFabricCompiler, GitHubTreeReader
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11, ModelFabricCompilerV11
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
            "retry_delivery_is_new_cognition": False,
            "command_authority_granted": False,
            "external_effect_authorized": False,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    model_lock = ModelFabricCompilerV11.from_file(
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
    response_text = (
        "JANUS ONLINE. Your Terminal message was received by the persistent JANUS resident "
        f"{resident_uuid}. Model {model_lock['model_digest'][:12]} / file-fabric "
        f"{file_fabric['file_fabric_digest'][:12]} opened a read-only conversation turn. "
        f"Active organs: {', '.join(active_organs)}. Received: {excerpt}"
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

    print(json.dumps({
        "terminal": response["terminal"],
        "message_id": request["message_id"],
        "response_id": response["response_id"],
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "turn_id": turn_id,
        "active_organs": active_organs,
        "retry_delivery_is_new_cognition": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
