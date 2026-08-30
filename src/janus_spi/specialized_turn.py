from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .activator import canonical_hash


class SpecializedTurnError(RuntimeError):
    pass


class SpecializedTurnLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise SpecializedTurnError("SPECIALIZED_TURN_LEDGER_ROW_NOT_OBJECT")
                rows.append(row)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["specialized_turn_hash"]) if rows else None

    def verify(self) -> bool:
        parent = None
        for row in self.read():
            if row.get("parent_specialized_turn_hash") != parent:
                return False
            claimed = str(row.get("specialized_turn_hash") or "")
            body = dict(row)
            body.pop("specialized_turn_hash", None)
            if canonical_hash(body) != claimed:
                return False
            parent = claimed
        return True

    def append(self, row: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(row)
        body.pop("specialized_turn_hash", None)
        body["specialized_turn_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
        if not self.verify():
            raise SpecializedTurnError("SPECIALIZED_TURN_LEDGER_INVALID_AFTER_APPEND")
        return body


def _verify_adapter_hash(adapter: Mapping[str, Any], *, error_prefix: str) -> str:
    claimed = str(adapter.get("adapter_result_hash") or "")
    body = dict(adapter)
    body.pop("adapter_result_hash", None)
    if not claimed or canonical_hash(body) != claimed:
        raise SpecializedTurnError(f"{error_prefix}_ADAPTER_RESULT_HASH_MISMATCH")
    return claimed


def reintegrate_specialized_turn(
    model_lock: Mapping[str, Any],
    runtime_receipt: Mapping[str, Any],
    materialization_receipt: Mapping[str, Any],
    *,
    ledger: SpecializedTurnLedger,
    now_fn=time.time,
) -> Dict[str, Any]:
    if not ledger.verify():
        raise SpecializedTurnError("SPECIALIZED_TURN_LEDGER_INVALID_BEFORE_REINTEGRATION")
    lock = dict(model_lock)
    runtime = dict(runtime_receipt)
    material = dict(materialization_receipt)
    digest = lock.get("model_digest")
    if runtime.get("model_digest") != digest or material.get("model_digest") != digest:
        raise SpecializedTurnError("SPECIALIZED_TURN_MODEL_DIGEST_MISMATCH")
    if runtime.get("model_lock_hash") != canonical_hash(lock):
        raise SpecializedTurnError("SPECIALIZED_TURN_MODEL_LOCK_HASH_MISMATCH")
    if material.get("model_lock_hash") != canonical_hash(lock):
        raise SpecializedTurnError("MATERIALIZATION_MODEL_LOCK_HASH_MISMATCH")
    if material.get("model_runtime_receipt_hash") != runtime.get("runtime_receipt_hash"):
        raise SpecializedTurnError("SPECIALIZED_TURN_RUNTIME_PARENT_MISMATCH")
    if material.get("terminal") != "JANUS_ACTIVE_ORGANS_MATERIALIZED_EXACT_SHA":
        raise SpecializedTurnError("MATERIALIZATION_NOT_SUCCESSFUL")
    for row in (runtime, material):
        for field in (
            "command_authority_granted",
            "world_truth_authority_granted",
            "external_effect_authorized",
            "physical_runtime_effect_authorized",
        ):
            if row.get(field) is not False:
                raise SpecializedTurnError(f"SPECIALIZED_TURN_AUTHORITY_CEILING_VIOLATION:{field}")

    materialized = material.get("materialized") or []
    if not isinstance(materialized, list):
        raise SpecializedTurnError("MATERIALIZATION_ROWS_REQUIRED")
    organ_outputs = []
    for row in materialized:
        if not isinstance(row, dict):
            raise SpecializedTurnError("MATERIALIZATION_ROW_NOT_OBJECT")
        adapter = row.get("adapter_result")
        if not isinstance(adapter, dict):
            raise SpecializedTurnError("ADAPTER_RESULT_REQUIRED")
        claimed = _verify_adapter_hash(adapter, error_prefix="ORGAN")
        if row.get("locked_head_sha") != row.get("materialized_head_sha"):
            raise SpecializedTurnError("REINTEGRATION_EXACT_SHA_MISMATCH")
        organ_outputs.append({
            "member_key": row.get("member_key"),
            "repository": row.get("repository"),
            "exact_head_sha": row.get("materialized_head_sha"),
            "adapter": adapter.get("adapter"),
            "adapter_terminal": adapter.get("terminal"),
            "adapter_result_hash": claimed,
            "output_class": "CONTEXT_OR_BOUNDED_ORGAN_RECEIPT_NOT_EVIDENCE",
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
        })

    required = {"anomaly_lab", "left_context", "orchestrator"}
    observed = {str(x.get("member_key")) for x in organ_outputs}
    if not required.issubset(observed):
        raise SpecializedTurnError("INITIAL_RESEARCH_TRIAD_INCOMPLETE")
    executed = set(material.get("executed_adapters") or [])
    if "anomaly_lab" not in executed:
        raise SpecializedTurnError("TOPA_DETECTIVE_DID_NOT_PERFORM_ADMITTED_WORK")

    raw_candidates = material.get("materialized_candidate_tissues") or []
    if not isinstance(raw_candidates, list):
        raise SpecializedTurnError("CANDIDATE_MATERIALIZATION_ROWS_NOT_LIST")
    candidate_outputs: list[Dict[str, Any]] = []
    for row in raw_candidates:
        if not isinstance(row, dict):
            raise SpecializedTurnError("CANDIDATE_MATERIALIZATION_ROW_NOT_OBJECT")
        key = str(row.get("candidate_tissue_key") or "")
        locked = (lock.get("candidate_runtime_tissues") or {}).get(key)
        if not isinstance(locked, Mapping) or locked.get("admission_status") != "ADMITTED_CANDIDATE_RUNTIME":
            raise SpecializedTurnError(f"CANDIDATE_OUTPUT_NOT_ADMITTED_IN_MODEL:{key}")
        parent = str(row.get("parent_member_key") or "")
        parent_output = next((x for x in organ_outputs if x.get("member_key") == parent), None)
        if parent_output is None:
            raise SpecializedTurnError(f"CANDIDATE_PARENT_OUTPUT_MISSING:{key}:{parent}")
        if row.get("parent_head_sha") != locked.get("parent_head_sha") or row.get("parent_head_sha") != parent_output.get("exact_head_sha"):
            raise SpecializedTurnError(f"CANDIDATE_PARENT_EXACT_SHA_MISMATCH:{key}")
        if row.get("manifest_hash") != locked.get("manifest_hash"):
            raise SpecializedTurnError(f"CANDIDATE_MANIFEST_HASH_MISMATCH:{key}")
        adapter = row.get("adapter_result")
        if not isinstance(adapter, Mapping):
            raise SpecializedTurnError(f"CANDIDATE_ADAPTER_RESULT_REQUIRED:{key}")
        claimed = _verify_adapter_hash(adapter, error_prefix="CANDIDATE")
        if adapter.get("candidate_execution_performed") is not True:
            raise SpecializedTurnError(f"CANDIDATE_EXECUTION_NOT_OBSERVED:{key}")
        if adapter.get("candidate_result_promoted") is not False:
            raise SpecializedTurnError(f"CANDIDATE_RESULT_PROMOTION_FORBIDDEN:{key}")
        for field in (
            "proof_authority",
            "scientific_claim_promotion_authority",
            "command_authority_granted",
            "world_truth_authority_granted",
            "external_effect_authorized",
            "physical_runtime_effect_authorized",
        ):
            if adapter.get(field) is not False:
                raise SpecializedTurnError(f"CANDIDATE_AUTHORITY_CEILING_VIOLATION:{key}:{field}")
        boundary = adapter.get("scientific_boundary") or {}
        if boundary.get("P_equals_NP_proved") is not False or boundary.get("P_VS_NP") != "OPEN":
            raise SpecializedTurnError(f"CANDIDATE_SCIENTIFIC_BOUNDARY_VIOLATION:{key}")
        candidate_outputs.append({
            "candidate_tissue_key": key,
            "component": adapter.get("component"),
            "repository": row.get("repository"),
            "parent_member_key": parent,
            "exact_parent_head_sha": row.get("parent_head_sha"),
            "manifest_hash": row.get("manifest_hash"),
            "adapter": adapter.get("adapter"),
            "adapter_terminal": adapter.get("terminal"),
            "adapter_result_hash": claimed,
            "native_selftest_pass": adapter.get("native_selftest_pass") is True,
            "output_class": "CANDIDATE_COMPUTATION_RECEIPT_NOT_PROOF_AUTHORITY",
            "candidate_result_promoted": False,
            "proof_authority_granted": False,
            "scientific_claim_promotion_authority_granted": False,
            "world_truth_authority_granted": False,
        })

    route_matches = {
        str(route.get("match"))
        for route in runtime.get("route_bindings") or []
        if isinstance(route, Mapping) and route.get("match")
    }
    trump = (lock.get("candidate_runtime_tissues") or {}).get("trump")
    trump_required_for_route = bool(
        isinstance(trump, Mapping)
        and trump.get("admission_status") == "ADMITTED_CANDIDATE_RUNTIME"
        and route_matches.intersection({"research_or_anomaly_investigation", "formal_or_theorem_claim"})
    )
    observed_candidates = {str(row.get("candidate_tissue_key")) for row in candidate_outputs}
    if trump_required_for_route and "trump" not in observed_candidates:
        raise SpecializedTurnError("ADMITTED_TRUMP_CANDIDATE_NOT_MATERIALIZED_FOR_ELIGIBLE_ROUTE")

    if material.get("candidate_result_promotion_performed") is not False:
        raise SpecializedTurnError("MATERIALIZATION_CANDIDATE_PROMOTION_FORBIDDEN")

    receipt = {
        "schema": "janus.activator.specialized_turn_receipt.v1.1",
        "created_at": float(now_fn()),
        "parent_specialized_turn_hash": ledger.tip_hash(),
        "model_id": "JANUS",
        "model_digest": digest,
        "model_lock_hash": canonical_hash(lock),
        "activation_id": runtime.get("activation_id"),
        "activation_receipt_hash": runtime.get("activation_receipt_hash"),
        "model_runtime_receipt_hash": runtime.get("runtime_receipt_hash"),
        "materialization_receipt_hash": material.get("materialization_receipt_hash"),
        "active_organs": list(runtime.get("active_organs") or []),
        "organ_outputs": organ_outputs,
        "candidate_outputs": candidate_outputs,
        "executed_adapters": sorted(executed),
        "executed_candidate_tissues": sorted(set(material.get("executed_candidate_tissues") or [])),
        "reintegrated_into": "JANUS_HOME_CURRENT_COGNITIVE_TURN",
        "claim_promotion_performed": False,
        "candidate_result_promotion_performed": False,
        "proof_authority_granted": False,
        "scientific_claim_promotion_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "dispatch_authorized": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "JANUS_SPECIALIZED_ORGAN_AND_CANDIDATE_TURN_REINTEGRATED",
        "next_gate": "PERSISTENT_HOME_CHECKPOINT_AND_RETURN",
    }
    return ledger.append(receipt)


__all__ = ["SpecializedTurnLedger", "SpecializedTurnError", "reintegrate_specialized_turn"]
