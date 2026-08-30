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

    model_lock = ModelFabricCompilerV11.from_file(
        args.manifest,
        reader=GitHubRepositoryReaderV11(),
    ).compile()
    if model_lock.get("ready") is not True:
        raise SystemExit("JANUS_MODEL_LOCK_NOT_READY")
    model_path = Path(args.model_lock_out)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model_lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    file_fabric = FileFabricCompiler.from_file(
        args.registry,
        reader=GitHubTreeReader(),
    ).compile(model_lock)
    if file_fabric.get("ready") is not True:
        raise SystemExit("JANUS_FILE_FABRIC_NOT_READY")
    fabric_path = Path(args.file_fabric_out)
    fabric_path.parent.mkdir(parents=True, exist_ok=True)
    fabric_path.write_text(json.dumps(file_fabric, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        state_dir=args.state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
    )
    runtime_receipt = runtime.activate(event)
    if runtime_receipt.get("terminal") != "JANUS_MODEL_BOUND_ROUTE_PROPOSED":
        raise SystemExit("TERMINAL_CONVERSATION_ROUTE_NOT_PROPOSED")
    active_organs = list(runtime_receipt.get("active_organs") or [])
    if not active_organs:
        raise SystemExit("TERMINAL_CONVERSATION_ACTIVE_ORGANS_REQUIRED")

    runtime_path = Path(args.runtime_receipt_out)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
    response_path = Path(args.response_out)
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "terminal": response["terminal"],
        "message_id": request["message_id"],
        "response_id": response["response_id"],
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "turn_id": turn_id,
        "active_organs": active_organs,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
