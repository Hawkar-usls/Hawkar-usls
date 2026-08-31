#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from janus_spi.activator import ActivationEvent, canonical_hash
from janus_spi.candidate_tissue_materializer import CandidateAwareOrganMaterializer
from janus_spi.file_fabric import FileFabricCompiler, GitHubTreeReader
from janus_spi.live_cycle import HardenedJanusPersistentStateV09
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12
from janus_spi.model_runtime import ModelBoundJanusRuntime
from janus_spi.persistent_state import JanusPersistentState
from janus_spi.specialized_turn import SpecializedTurnLedger, reintegrate_specialized_turn


SUCCESS_TERMINAL = "JANUS_REAL_LAUNCH_V2_COMPLETED_RETURNED_HOME"
REQUIRED_RESEARCH_ORGANS = {"anomaly_lab", "left_context", "orchestrator"}


def _write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hearth_append(state: HardenedJanusPersistentStateV09, *, event: str, cycle_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return state.hearth.append({
        "schema": "janus.activator.real_launch_v2_hearth_receipt.v1",
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
        "payload": dict(payload),
    })


def validate_launch_receipt(receipt: Mapping[str, Any]) -> bool:
    if receipt.get("terminal") != SUCCESS_TERMINAL:
        return False
    required_false = (
        "command_authority_granted",
        "claim_authority_granted",
        "scientific_evidence_authority_granted",
        "world_truth_authority_granted",
        "external_effect_authorized",
        "physical_runtime_effect_authorized",
        "candidate_result_promotion_performed",
    )
    if any(receipt.get(key) is not False for key in required_false):
        return False
    if receipt.get("fresh_external_stimulus") is not True:
        return False
    if receipt.get("model_first") is not True or receipt.get("all_membership_compiled_before_routing") is not True:
        return False
    if receipt.get("file_fabric_coverage_complete") is not True:
        return False
    if receipt.get("return_not_reset") is not True or receipt.get("mode") != "AT_HOME":
        return False
    if receipt.get("same_resident_uuid") is not True:
        return False
    if not REQUIRED_RESEARCH_ORGANS.issubset(set(receipt.get("active_organs") or [])):
        return False
    if "trump" not in set(receipt.get("executed_candidate_tissues") or []):
        return False
    trump = receipt.get("trump")
    if not isinstance(trump, Mapping):
        return False
    if trump.get("admission_status") != "ADMITTED_CANDIDATE_RUNTIME":
        return False
    if trump.get("native_selftest_pass") is not True:
        return False
    if trump.get("candidate_result_promoted") is not False:
        return False
    if trump.get("proof_authority_granted") is not False:
        return False
    if trump.get("scientific_claim_promotion_authority_granted") is not False:
        return False
    boundary = trump.get("scientific_boundary") or {}
    if boundary.get("P_equals_NP_proved") is not False or boundary.get("P_VS_NP") != "OPEN":
        return False
    claimed = str(receipt.get("launch_receipt_hash") or "")
    body = dict(receipt)
    body.pop("launch_receipt_hash", None)
    return len(claimed) == 64 and canonical_hash(body) == claimed


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the current model-first persistent JANUS organism and return the same resident AT_HOME")
    parser.add_argument("--event-file", required=True)
    parser.add_argument("--resident-identity", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    parser.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    parser.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    parser.add_argument("--registry", default="config/JANUS_FILE_FORMAT_REGISTRY-v1.json")
    parser.add_argument("--model-lock-out", default="runtime/real-launch-v2-model-lock.json")
    parser.add_argument("--file-fabric-out", default="runtime/real-launch-v2-file-fabric.json")
    parser.add_argument("--runtime-receipt-out", default="runtime/real-launch-v2-runtime-receipt.json")
    parser.add_argument("--materialization-out", default="runtime/real-launch-v2-materialization.json")
    parser.add_argument("--turn-out", default="runtime/real-launch-v2-specialized-turn.json")
    parser.add_argument("--result-out", default="runtime/real-launch-v2-result.json")
    parser.add_argument("--organ-workspace", default="runtime/real-launch-v2-organs")
    args = parser.parse_args()

    raw = json.loads(Path(args.event_file).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("REAL_LAUNCH_V2_EVENT_OBJECT_REQUIRED")
    if raw.get("fresh") is not True or raw.get("self_generated") is not False:
        raise SystemExit("REAL_LAUNCH_V2_FRESH_EXTERNAL_STIMULUS_REQUIRED")
    if raw.get("command_authority") is not False or raw.get("effect_authorized") is not False:
        raise SystemExit("REAL_LAUNCH_V2_AUTHORITY_CEILING_VIOLATION")
    classifications = list(raw.get("classifications") or [])
    if "research_or_anomaly_investigation" not in classifications:
        raise SystemExit("REAL_LAUNCH_V2_RESEARCH_ROUTE_REQUIRED")

    identity = json.loads(Path(args.resident_identity).read_text(encoding="utf-8"))
    if not JanusPersistentState.verify_identity(identity):
        raise SystemExit("REAL_LAUNCH_V2_PERSISTENT_IDENTITY_INVALID")
    resident_uuid = str(identity["resident_uuid"])

    state_dir = Path(args.state_dir)
    state = HardenedJanusPersistentStateV09(state_dir)
    before = state.verify()
    if before.get("ok") is not True or before.get("mode") != "AT_HOME" or before.get("active_cycle_id") is not None:
        raise SystemExit("REAL_LAUNCH_V2_HOME_NOT_HEALTHY_AT_HOME")
    if before.get("resident_uuid") != resident_uuid:
        raise SystemExit("REAL_LAUNCH_V2_RESIDENT_IDENTITY_MISMATCH")

    event = ActivationEvent.build(
        source_kind=str(raw.get("source_kind") or "EXPLICIT_HUMAN_ACTIVATOR_LAUNCH"),
        source_ref=str(raw.get("source_ref") or ""),
        payload=raw.get("payload"),
        classifications=classifications,
        fresh=True,
        self_generated=False,
        command_authority=False,
        effect_authorized=False,
    )
    cycle_id = "real-launch-v2-" + canonical_hash({
        "resident_uuid": resident_uuid,
        "event_id": event.event_id,
        "parent_hearth_hash": state.hearth.tip_hash(),
    })

    wake = _hearth_append(state, event="WAKE_REAL_LAUNCH_V2_MODEL_FIRST", cycle_id=cycle_id, payload={
        "event_id": event.event_id,
        "source_ref": event.source_ref,
        "model_first_required": True,
    })
    state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=wake["receipt_hash"])

    model_lock = ModelFabricCompilerV12.from_file(
        args.manifest,
        reader=GitHubRepositoryReaderV11(),
    ).compile()
    if model_lock.get("ready") is not True:
        raise SystemExit("REAL_LAUNCH_V2_MODEL_FABRIC_NOT_READY")
    if model_lock.get("optional_unavailable"):
        raise SystemExit("REAL_LAUNCH_V2_MODEL_OPTIONAL_UNAVAILABLE")
    if model_lock.get("candidate_tissue_unavailable"):
        raise SystemExit("REAL_LAUNCH_V2_CANDIDATE_TISSUE_UNAVAILABLE")
    trump_lock = (model_lock.get("candidate_runtime_tissues") or {}).get("trump") or {}
    if trump_lock.get("admission_status") != "ADMITTED_CANDIDATE_RUNTIME":
        raise SystemExit("REAL_LAUNCH_V2_TRUMP_NOT_ADMITTED")
    _write_json(args.model_lock_out, model_lock)

    file_fabric = FileFabricCompiler.from_file(
        args.registry,
        reader=GitHubTreeReader(),
    ).compile(model_lock)
    if file_fabric.get("ready") is not True or file_fabric.get("coverage_complete") is not True:
        raise SystemExit("REAL_LAUNCH_V2_FILE_FABRIC_NOT_COMPLETE")
    _write_json(args.file_fabric_out, file_fabric)

    runtime = ModelBoundJanusRuntime(
        model_lock,
        state_dir=state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
    )
    runtime_receipt = runtime.activate(event)
    if runtime_receipt.get("terminal") != "JANUS_MODEL_BOUND_ROUTE_PROPOSED":
        raise SystemExit("REAL_LAUNCH_V2_MODEL_BOUND_ROUTE_NOT_PROPOSED")
    if not REQUIRED_RESEARCH_ORGANS.issubset(set(runtime_receipt.get("active_organs") or [])):
        raise SystemExit("REAL_LAUNCH_V2_REQUIRED_RESEARCH_ORGANS_NOT_ACTIVE")
    _write_json(args.runtime_receipt_out, runtime_receipt)

    materializer = CandidateAwareOrganMaterializer.from_files(
        model_lock_path=args.model_lock_out,
        runtime_receipt_path=args.runtime_receipt_out,
        workspace=args.organ_workspace,
    )
    material = materializer.materialize()
    _write_json(args.materialization_out, material)

    ledger = SpecializedTurnLedger(state_dir / "specialized_turn_ledger.jsonl")
    turn = reintegrate_specialized_turn(model_lock, runtime_receipt, material, ledger=ledger)
    _write_json(args.turn_out, turn)
    if turn.get("terminal") != "JANUS_SPECIALIZED_ORGAN_AND_CANDIDATE_TURN_REINTEGRATED":
        raise SystemExit("REAL_LAUNCH_V2_SPECIALIZED_TURN_NOT_REINTEGRATED")
    if "trump" not in set(turn.get("executed_candidate_tissues") or []):
        raise SystemExit("REAL_LAUNCH_V2_TRUMP_NOT_EXECUTED")
    candidate = next((row for row in turn.get("candidate_outputs") or [] if row.get("candidate_tissue_key") == "trump"), None)
    if not isinstance(candidate, dict) or candidate.get("native_selftest_pass") is not True:
        raise SystemExit("REAL_LAUNCH_V2_TRUMP_NATIVE_SELFTEST_NOT_OBSERVED")

    checkpoint = _hearth_append(state, event="CHECKPOINT_REAL_LAUNCH_V2", cycle_id=cycle_id, payload={
        "event_id": event.event_id,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "runtime_receipt_hash": runtime_receipt["runtime_receipt_hash"],
        "specialized_turn_hash": turn["specialized_turn_hash"],
        "active_organs": list(runtime_receipt.get("active_organs") or []),
        "executed_candidate_tissues": list(turn.get("executed_candidate_tissues") or []),
        "candidate_result_promotion_performed": False,
    })
    state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=checkpoint["receipt_hash"])

    sleep = _hearth_append(state, event="SLEEP_REAL_LAUNCH_V2_RETURN_HOME", cycle_id=cycle_id, payload={
        "event_id": event.event_id,
        "model_digest": model_lock["model_digest"],
        "specialized_turn_hash": turn["specialized_turn_hash"],
        "return_not_reset": True,
    })
    state._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=sleep["receipt_hash"])

    after = state.verify()
    if after.get("ok") is not True or after.get("mode") != "AT_HOME" or after.get("active_cycle_id") is not None:
        raise SystemExit("REAL_LAUNCH_V2_HOME_INVALID_AFTER_RETURN")
    if after.get("resident_uuid") != resident_uuid:
        raise SystemExit("REAL_LAUNCH_V2_RESIDENT_CHANGED")

    result: dict[str, Any] = {
        "schema": "janus.activator.real_launch_v2_result.v1",
        "terminal": SUCCESS_TERMINAL,
        "cycle_id": cycle_id,
        "event_id": event.event_id,
        "resident_uuid": resident_uuid,
        "same_resident_uuid": True,
        "fresh_external_stimulus": True,
        "model_first": True,
        "all_membership_compiled_before_routing": model_lock.get("all_membership_compiled_before_routing") is True,
        "routing_selects_activity_not_membership": model_lock.get("routing_selects_activity_not_membership") is True,
        "model_digest": model_lock["model_digest"],
        "model_member_count": len(model_lock["members"]),
        "model_organ_count": sum(1 for row in model_lock["members"].values() if isinstance(row, dict) and row.get("kind") == "ORGAN"),
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "file_fabric_coverage_complete": file_fabric.get("coverage_complete") is True,
        "active_organs": list(runtime_receipt.get("active_organs") or []),
        "materialized_member_count": material.get("materialized_member_count"),
        "executed_adapters": list(material.get("executed_adapters") or []),
        "executed_candidate_tissues": list(turn.get("executed_candidate_tissues") or []),
        "specialized_turn_hash": turn["specialized_turn_hash"],
        "candidate_result_promotion_performed": False,
        "trump": {
            "admission_status": trump_lock.get("admission_status"),
            "manifest_hash": trump_lock.get("manifest_hash"),
            "parent_head_sha": trump_lock.get("parent_head_sha"),
            "native_selftest_pass": candidate.get("native_selftest_pass") is True,
            "candidate_result_promoted": False,
            "proof_authority_granted": False,
            "scientific_claim_promotion_authority_granted": False,
            "scientific_boundary": {
                "P_equals_NP_proved": False,
                "P_VS_NP": "OPEN",
            },
        },
        "wake_hash": wake["receipt_hash"],
        "checkpoint_hash": checkpoint["receipt_hash"],
        "sleep_hash": sleep["receipt_hash"],
        "mode": "AT_HOME",
        "return_not_reset": True,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    result["launch_receipt_hash"] = canonical_hash(result)
    if not validate_launch_receipt(result):
        raise SystemExit("REAL_LAUNCH_V2_RESULT_SELF_VERIFY_FAILED")

    persistent = state_dir / "real_launch_v2_receipts" / f"{cycle_id}.json"
    persistent.parent.mkdir(parents=True, exist_ok=True)
    if persistent.exists():
        raise SystemExit("REAL_LAUNCH_V2_CREATE_ONLY_RECEIPT_CONFLICT")
    _write_json(persistent, result)
    _write_json(args.result_out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
