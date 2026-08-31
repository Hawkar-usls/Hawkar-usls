from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .activator import canonical_hash

LEDGER_SCHEMA = "janus.activator.real_launch_v2_arm_ledger_entry.v1"
LEDGER_FILE = "real_launch_v2_arm_ledger.jsonl"
SUCCESS_TERMINAL = "JANUS_REAL_LAUNCH_V2_COMPLETED_RETURNED_HOME"


class LaunchArmError(RuntimeError):
    pass


def verify_arm(arm: Mapping[str, Any]) -> bool:
    if not isinstance(arm, Mapping):
        return False
    if arm.get("schema") != "janus.activator.real_launch_v2_arm.v1":
        return False
    if not str(arm.get("arm_id") or ""):
        return False
    if arm.get("one_shot") is not True:
        return False
    for key in (
        "command_authority_granted", "claim_authority_granted", "scientific_evidence_authority_granted",
        "world_truth_authority_granted", "external_effect_authorized", "physical_runtime_effect_authorized",
    ):
        if arm.get(key) is not False:
            return False
    consumed = arm.get("consumed") is True
    armed = arm.get("armed") is True
    if consumed and armed:
        return False
    if not consumed and not armed:
        return False
    return True


def _ledger_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / LEDGER_FILE


def _load_rows(state_dir: str | Path) -> list[Dict[str, Any]]:
    path = _ledger_path(state_dir)
    if not path.exists():
        return []
    rows: list[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise LaunchArmError("ARM_LEDGER_ROW_OBJECT_REQUIRED")
        core = dict(row)
        claimed = str(core.pop("entry_hash", ""))
        if len(claimed) != 64 or canonical_hash(core) != claimed:
            raise LaunchArmError("ARM_LEDGER_ENTRY_HASH_INVALID")
        if row.get("schema") != LEDGER_SCHEMA:
            raise LaunchArmError("ARM_LEDGER_SCHEMA_INVALID")
        rows.append(row)
    return rows


def arm_status(arm: Mapping[str, Any], *, state_dir: str | Path) -> Dict[str, Any]:
    if not verify_arm(arm):
        raise LaunchArmError("REAL_LAUNCH_V2_ARM_INVALID")
    arm_id = str(arm["arm_id"])
    rows = [row for row in _load_rows(state_dir) if row.get("arm_id") == arm_id]
    if len(rows) > 1:
        unique = {(row.get("cycle_id"), row.get("launch_receipt_hash")) for row in rows}
        if len(unique) > 1:
            raise LaunchArmError("ARM_LEDGER_CONFLICT")
    ledger_row = rows[-1] if rows else None
    consumed = arm.get("consumed") is True or ledger_row is not None
    return {
        "schema": "janus.activator.real_launch_v2_arm_status.v1",
        "arm_id": arm_id,
        "consumed": consumed,
        "should_launch": bool(arm.get("armed") is True and not consumed),
        "static_consumed": arm.get("consumed") is True,
        "ledger_consumed": ledger_row is not None,
        "cycle_id": ledger_row.get("cycle_id") if ledger_row else arm.get("consumed_cycle_id"),
        "launch_receipt_hash": ledger_row.get("launch_receipt_hash") if ledger_row else arm.get("consumed_receipt_hash"),
        "retry_delivery_is_new_launch": False if consumed else None,
    }


def consume_arm(arm: Mapping[str, Any], *, state_dir: str | Path, launch_result: Mapping[str, Any]) -> Dict[str, Any]:
    if not verify_arm(arm):
        raise LaunchArmError("REAL_LAUNCH_V2_ARM_INVALID")
    if arm.get("consumed") is True:
        raise LaunchArmError("STATICALLY_CONSUMED_ARM_CANNOT_BE_CONSUMED_AGAIN")
    if launch_result.get("terminal") != SUCCESS_TERMINAL:
        raise LaunchArmError("ARM_CONSUMPTION_REQUIRES_SUCCESSFUL_LAUNCH")
    required_false = (
        "command_authority_granted", "claim_authority_granted", "scientific_evidence_authority_granted",
        "world_truth_authority_granted", "external_effect_authorized", "physical_runtime_effect_authorized",
    )
    for key in required_false:
        if launch_result.get(key) is not False:
            raise LaunchArmError(f"ARM_CONSUMPTION_AUTHORITY_VIOLATION:{key}")
    receipt_hash = str(launch_result.get("launch_receipt_hash") or "")
    cycle_id = str(launch_result.get("cycle_id") or "")
    resident_uuid = str(launch_result.get("resident_uuid") or "")
    model_digest = str(launch_result.get("model_digest") or "")
    if len(receipt_hash) != 64 or not cycle_id or not resident_uuid or len(model_digest) != 64:
        raise LaunchArmError("ARM_CONSUMPTION_RESULT_BINDING_INVALID")

    current = arm_status(arm, state_dir=state_dir)
    if current["consumed"]:
        if current.get("cycle_id") == cycle_id and current.get("launch_receipt_hash") == receipt_hash:
            return current
        raise LaunchArmError("ARM_ALREADY_CONSUMED_BY_DIFFERENT_LAUNCH")

    core: Dict[str, Any] = {
        "schema": LEDGER_SCHEMA,
        "arm_id": str(arm["arm_id"]),
        "status": "CONSUMED_BY_SUCCESSFUL_CANONICAL_LAUNCH",
        "cycle_id": cycle_id,
        "launch_receipt_hash": receipt_hash,
        "resident_uuid": resident_uuid,
        "model_digest": model_digest,
        "terminal": SUCCESS_TERMINAL,
        "retry_delivery_is_new_launch": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }
    core["entry_hash"] = canonical_hash(core)
    path = _ledger_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(core, ensure_ascii=False, sort_keys=True) + "\n")
    return arm_status(arm, state_dir=state_dir)
