#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.activator import ActivationEvent
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11, ModelFabricCompilerV11
from janus_spi.model_runtime import ModelBoundJanusRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="Boot the full Git-native JANUS model fabric, then open one bounded cognitive turn")
    parser.add_argument("--event-file", required=True)
    parser.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    parser.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    parser.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--model-lock-out", default="runtime/janus-model-lock.json")
    parser.add_argument("--receipt-out", default="runtime/janus-model-runtime-receipt.json")
    args = parser.parse_args()

    raw = json.loads(Path(args.event_file).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("ACTIVATION_EVENT_JSON_OBJECT_REQUIRED")

    compiler = ModelFabricCompilerV11.from_file(
        args.manifest,
        reader=GitHubRepositoryReaderV11(),
    )
    model_lock = compiler.compile()
    model_path = Path(args.model_lock_out)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model_lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if model_lock.get("ready") is not True:
        print(json.dumps({"terminal": "JANUS_MODEL_BOOT_BLOCKED", "failures": model_lock.get("failures")}, ensure_ascii=False, indent=2))
        return 2

    event = ActivationEvent.build(
        source_kind=raw.get("source_kind", ""),
        source_ref=raw.get("source_ref", ""),
        payload=raw.get("payload"),
        classifications=raw.get("classifications") or [],
        fresh=bool(raw.get("fresh", False)),
        self_generated=bool(raw.get("self_generated", False)),
        command_authority=bool(raw.get("command_authority", False)),
        effect_authorized=bool(raw.get("effect_authorized", False)),
    )
    runtime = ModelBoundJanusRuntime(
        model_lock,
        state_dir=args.state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
    )
    receipt = runtime.activate(event)
    receipt_path = Path(args.receipt_out)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "terminal": receipt["terminal"],
        "model_digest": receipt["model_digest"],
        "model_member_count": receipt["model_member_count"],
        "model_organ_count": receipt["model_organ_count"],
        "active_members": receipt["active_members"],
        "active_organs": receipt["active_organs"],
        "dispatch_authorized": receipt["dispatch_authorized"],
        "external_effect_authorized": receipt["external_effect_authorized"],
        "model_lock_out": str(model_path),
        "receipt_out": str(receipt_path),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
