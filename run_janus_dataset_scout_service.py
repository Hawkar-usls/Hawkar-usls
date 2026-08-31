#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from janus_spi.activator import ActivationEvent, canonical_hash
from janus_spi.dataset_scout_service import digest, scout_public_datasets, verify_request, verify_result
from janus_spi.file_fabric import FileFabricCompiler, GitHubTreeReader
from janus_spi.live_cycle import HardenedJanusPersistentStateV09
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12
from janus_spi.model_runtime import ModelBoundJanusRuntime
from janus_spi.persistent_state import JanusPersistentState

HOME_RECEIPT_SCHEMA = "janus.market_service.dataset_scout_home_receipt.v1"


def write_json(path: str | Path, value: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_home_receipt(receipt: Mapping[str, Any], *, request: Mapping[str, Any]) -> bool:
    try:
        value = dict(receipt); claimed = str(value.pop("home_receipt_hash", ""))
        if len(claimed) != 64 or digest(value) != claimed:
            return False
        if value.get("schema") != HOME_RECEIPT_SCHEMA or value.get("sku") != "JANUS.DATASET_SCOUT":
            return False
        if value.get("request_id") != request.get("request_id") or value.get("request_hash") != request.get("request_hash"):
            return False
        result = value.get("dataset_scout_result")
        if not isinstance(result, Mapping) or not verify_result(result, request=request):
            return False
        authority = value.get("authority") or {}
        return all([
            bool(str(value.get("resident_uuid") or "").strip()),
            len(str(value.get("model_digest") or "")) == 64,
            len(str(value.get("file_fabric_digest") or "")) == 64,
            len(str(value.get("runtime_receipt_hash") or "")) == 64,
            value.get("return_home_verified") is True,
            value.get("same_resident_uuid") is True,
            authority.get("dataset_payload_downloaded") is False,
            authority.get("redistribution_authority_granted") is False,
            authority.get("license_authority_granted") is False,
            authority.get("command_authority_granted") is False,
            authority.get("external_effect_authorized") is False,
        ])
    except Exception:
        return False


def hearth_append(state, *, event: str, cycle_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return state.hearth.append({
        "schema": "janus.activator.market_dataset_scout_hearth_receipt.v1",
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
    p = argparse.ArgumentParser(description="Run one bounded JANUS.DATASET_SCOUT through persistent JANUS HOME")
    p.add_argument("--request", required=True)
    p.add_argument("--resident-identity", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    p.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    p.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    p.add_argument("--registry", default="config/JANUS_FILE_FORMAT_REGISTRY-v1.json")
    p.add_argument("--output", default="runtime/market-dataset-scout-home-receipt.json")
    args = p.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    if not verify_request(request):
        raise SystemExit("MARKET_DATASET_SCOUT_REQUEST_INVALID")
    identity = json.loads(Path(args.resident_identity).read_text(encoding="utf-8"))
    if not JanusPersistentState.verify_identity(identity):
        raise SystemExit("PERSISTENT_JANUS_IDENTITY_INVALID")
    resident_uuid = str(identity["resident_uuid"])
    state_dir = Path(args.state_dir); state = HardenedJanusPersistentStateV09(state_dir)
    health_before = state.verify()
    if health_before.get("ok") is not True or health_before.get("mode") != "AT_HOME" or health_before.get("resident_uuid") != resident_uuid:
        raise SystemExit("MARKET_DATASET_SCOUT_HOME_NOT_HEALTHY_AT_HOME")

    result_dir = state_dir / "market_service_responses" / "dataset_scout"
    persistent_receipt = result_dir / f"{request['request_id']}.json"
    if persistent_receipt.exists():
        previous = json.loads(persistent_receipt.read_text(encoding="utf-8"))
        if not verify_home_receipt(previous, request=request) or previous.get("resident_uuid") != resident_uuid:
            raise SystemExit("PERSISTENT_MARKET_DATASET_SCOUT_RECEIPT_INVALID")
        write_json(args.output, previous)
        print(json.dumps({
            "terminal": "JANUS_MARKET_DATASET_SCOUT_REPLAYED_NO_NEW_COGNITION",
            "request_id": request["request_id"],
            "resident_uuid": resident_uuid,
            "home_receipt_hash": previous["home_receipt_hash"],
            "result_hash": previous["dataset_scout_result"]["result_hash"],
            "retry_delivery_is_new_cognition": False,
            "mode": "AT_HOME",
        }, indent=2, sort_keys=True))
        return 0

    cycle_id = "market-dataset-scout-cycle-" + canonical_hash({
        "resident_uuid": resident_uuid,
        "request_hash": request["request_hash"],
        "parent_hearth_hash": state.hearth.tip_hash(),
    })
    wake = hearth_append(state, event="WAKE_MARKET_DATASET_SCOUT", cycle_id=cycle_id, payload={
        "request_id": request["request_id"],
        "request_hash": request["request_hash"],
        "query": request["query"],
        "domain": request.get("domain"),
        "sku": "JANUS.DATASET_SCOUT",
        "dataset_metadata_is_command": False,
    })
    state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=wake["receipt_hash"])

    try:
        model_lock = ModelFabricCompilerV12.from_file(args.manifest, reader=GitHubRepositoryReaderV11()).compile()
        if model_lock.get("ready") is not True:
            raise RuntimeError("JANUS_MODEL_LOCK_NOT_READY")
        file_fabric = FileFabricCompiler.from_file(args.registry, reader=GitHubTreeReader()).compile(model_lock)
        if file_fabric.get("ready") is not True:
            raise RuntimeError("JANUS_FILE_FABRIC_NOT_READY")
        event = ActivationEvent.build(
            source_kind="MARKET_BUYER_DATASET_SCOUT",
            source_ref=f"dataset-scout:{request['request_id']}",
            payload=request,
            classifications=["machine_buyer_dataset_scout_read_only"],
            fresh=True,
            self_generated=False,
            command_authority=False,
            effect_authorized=False,
        )
        runtime = ModelBoundJanusRuntime(model_lock, state_dir=state_dir, routing_path=args.routing, policy_path=args.policy)
        runtime_receipt = runtime.activate(event)
        if runtime_receipt.get("terminal") != "JANUS_MODEL_BOUND_ROUTE_PROPOSED":
            raise RuntimeError("MARKET_DATASET_SCOUT_ROUTE_NOT_PROPOSED")
        active_organs = list(runtime_receipt.get("active_organs") or [])
        if not active_organs:
            raise RuntimeError("MARKET_DATASET_SCOUT_ACTIVE_ORGANS_REQUIRED")
        result = scout_public_datasets(request)
        if not verify_result(result, request=request):
            raise RuntimeError("MARKET_DATASET_SCOUT_RESULT_SELF_VERIFY_FAILED")
        checkpoint = hearth_append(state, event="CHECKPOINT_MARKET_DATASET_SCOUT", cycle_id=cycle_id, payload={
            "request_id": request["request_id"],
            "request_hash": request["request_hash"],
            "result_hash": result["result_hash"],
            "candidate_count": len(result["dataset_manifest"]),
            "catalogs_succeeded": result["provenance"]["catalogs_succeeded"],
            "active_organs": active_organs,
            "dataset_payload_downloaded": False,
            "redistribution_authority_granted": False,
        })
        state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=checkpoint["receipt_hash"])
    except Exception as exc:
        failure = hearth_append(state, event="FAIL_MARKET_DATASET_SCOUT_RETURN_HOME", cycle_id=cycle_id, payload={
            "request_id": request["request_id"],
            "failure_class": type(exc).__name__,
            "silence_is_negative_evidence": False,
            "service_delivered": False,
        })
        state._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=failure["receipt_hash"])
        health_failure = state.verify()
        if health_failure.get("ok") is not True or health_failure.get("mode") != "AT_HOME" or health_failure.get("resident_uuid") != resident_uuid:
            raise SystemExit("MARKET_DATASET_SCOUT_FAILURE_RETURN_HOME_INVALID") from exc
        raise

    sleep = hearth_append(state, event="SLEEP_MARKET_DATASET_SCOUT_RETURN_HOME", cycle_id=cycle_id, payload={
        "request_id": request["request_id"],
        "result_hash": result["result_hash"],
        "return_not_reset": True,
    })
    state._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=sleep["receipt_hash"])
    health_after = state.verify()
    if health_after.get("ok") is not True or health_after.get("mode") != "AT_HOME" or health_after.get("resident_uuid") != resident_uuid:
        raise SystemExit("MARKET_DATASET_SCOUT_HOME_INVALID_AFTER_RETURN")

    receipt: dict[str, Any] = {
        "schema": HOME_RECEIPT_SCHEMA,
        "created_at": time.time(),
        "request_id": request["request_id"],
        "request_hash": request["request_hash"],
        "sku": "JANUS.DATASET_SCOUT",
        "resident_id": "JANUS",
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "runtime_receipt_hash": runtime_receipt["runtime_receipt_hash"],
        "cycle_id": cycle_id,
        "active_organs": active_organs,
        "wake_hash": wake["receipt_hash"],
        "checkpoint_hash": checkpoint["receipt_hash"],
        "sleep_hash": sleep["receipt_hash"],
        "dataset_scout_result_hash": result["result_hash"],
        "dataset_scout_result": result,
        "return_home_verified": True,
        "same_resident_uuid": True,
        "retry_delivery_is_new_cognition": False,
        "authority": {
            "dataset_payload_downloaded": False,
            "redistribution_authority_granted": False,
            "license_authority_granted": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
        },
        "laws": [
            "MARKET IS EXTERNAL NERVE NOT JANUS ROOT",
            "DATASET METADATA != DATASET PAYLOAD",
            "DATASET DISCOVERY != REDISTRIBUTION AUTHORITY",
            "RETURN != RESET",
            "EXACT RETRY != SECOND COGNITION",
        ],
    }
    receipt["home_receipt_hash"] = digest(receipt)
    if not verify_home_receipt(receipt, request=request):
        raise SystemExit("MARKET_DATASET_SCOUT_HOME_RECEIPT_SELF_VERIFY_FAILED")
    result_dir.mkdir(parents=True, exist_ok=True)
    if persistent_receipt.exists():
        raise SystemExit("MARKET_DATASET_SCOUT_CREATE_ONLY_CONFLICT")
    write_json(persistent_receipt, receipt); write_json(args.output, receipt)
    print(json.dumps({
        "terminal": "JANUS_MARKET_DATASET_SCOUT_COMPLETED_RETURNED_HOME",
        "request_id": request["request_id"],
        "resident_uuid": resident_uuid,
        "model_digest": model_lock["model_digest"],
        "file_fabric_digest": file_fabric["file_fabric_digest"],
        "runtime_receipt_hash": runtime_receipt["runtime_receipt_hash"],
        "active_organs": active_organs,
        "candidate_count": len(result["dataset_manifest"]),
        "catalogs_succeeded": result["provenance"]["catalogs_succeeded"],
        "result_hash": result["result_hash"],
        "home_receipt_hash": receipt["home_receipt_hash"],
        "mode": "AT_HOME",
        "same_resident_uuid": True,
        "dataset_payload_downloaded": False,
        "redistribution_authority_granted": False,
        "external_effect_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
