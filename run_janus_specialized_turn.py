#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.activator import ActivationEvent
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12
from janus_spi.model_runtime import ModelBoundJanusRuntime
from janus_spi.organ_materializer import OrganMaterializer
from janus_spi.specialized_turn import SpecializedTurnLedger, reintegrate_specialized_turn


def write(path: str | Path, value) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Boot full JANUS, materialize routed organs on exact locked SHAs, and reintegrate one bounded turn")
    ap.add_argument("--event-file", required=True)
    ap.add_argument("--state-dir", default="runtime/specialized-state")
    ap.add_argument("--model-lock-out", default="runtime/janus-model-lock.json")
    ap.add_argument("--runtime-receipt-out", default="runtime/janus-model-runtime-receipt.json")
    ap.add_argument("--materialization-out", default="runtime/janus-organ-materialization.json")
    ap.add_argument("--turn-out", default="runtime/janus-specialized-turn.json")
    ap.add_argument("--organ-workspace", default="runtime/materialized-organs")
    args = ap.parse_args()

    raw = json.loads(Path(args.event_file).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("SPECIALIZED_EVENT_JSON_OBJECT_REQUIRED")

    compiler = ModelFabricCompilerV12.from_file(
        ".janus/activator/JANUS_MODEL_MANIFEST.json",
        reader=GitHubRepositoryReaderV11(),
    )
    lock = compiler.compile()
    write(args.model_lock_out, lock)
    if lock.get("ready") is not True or lock.get("optional_unavailable"):
        print(json.dumps({"terminal": "SPECIALIZED_TURN_BLOCKED_MODEL_FABRIC", "failures": lock.get("failures"), "optional_unavailable": lock.get("optional_unavailable")}, indent=2))
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
    runtime = ModelBoundJanusRuntime(lock, state_dir=args.state_dir)
    runtime_receipt = runtime.activate(event)
    write(args.runtime_receipt_out, runtime_receipt)

    materializer = OrganMaterializer.from_files(
        model_lock_path=args.model_lock_out,
        runtime_receipt_path=args.runtime_receipt_out,
        workspace=args.organ_workspace,
    )
    material = materializer.materialize()
    write(args.materialization_out, material)

    ledger = SpecializedTurnLedger(Path(args.state_dir) / "specialized_turn_ledger.jsonl")
    turn = reintegrate_specialized_turn(lock, runtime_receipt, material, ledger=ledger)
    write(args.turn_out, turn)

    print(json.dumps({
        "terminal": turn["terminal"],
        "model_digest": turn["model_digest"],
        "model_members": len(lock["members"]),
        "model_organs": sum(1 for x in lock["members"].values() if isinstance(x, dict) and x.get("kind") == "ORGAN"),
        "candidate_runtime_tissues": sorted(lock.get("candidate_runtime_tissues", {})),
        "active_organs": runtime_receipt["active_organs"],
        "materialized_members": material["materialized_member_count"],
        "executed_adapters": material["executed_adapters"],
        "next_gate": turn["next_gate"],
        "external_effect_authorized": turn["external_effect_authorized"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
