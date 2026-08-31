from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .activator import canonical_hash

ARM_SCHEMA = "janus.activator.turing_style_gate_arm.v1"
ENTRY_SCHEMA = "janus.activator.turing_style_gate_arm_ledger_entry.v1"
LEDGER_FILE = "turing_style_gate_arm_ledger.jsonl"
READY_TERMINAL = "JANUS_TURING_STYLE_MACHINE_GATE_READY_FOR_HUMAN_BLIND_JUDGMENT"


class TuringGateArmError(RuntimeError):
    pass


def verify_arm(arm: Mapping[str, Any]) -> bool:
    if not isinstance(arm, Mapping) or arm.get("schema") != ARM_SCHEMA:
        return False
    if not str(arm.get("arm_id") or "") or not str(arm.get("gate_id") or ""):
        return False
    if arm.get("one_shot") is not True:
        return False
    consumed = arm.get("consumed") is True
    armed = arm.get("armed") is True
    if consumed == armed:
        return False
    for key in (
        "command_authority_granted", "claim_authority_granted",
        "scientific_evidence_authority_granted", "world_truth_authority_granted",
        "external_effect_authorized", "physical_runtime_effect_authorized",
    ):
        if arm.get(key) is not False:
            return False
    return True


def _path(state_dir: str | Path) -> Path:
    return Path(state_dir) / LEDGER_FILE


def _rows(state_dir: str | Path) -> list[Dict[str, Any]]:
    path = _path(state_dir)
    if not path.exists():
        return []
    out: list[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("schema") != ENTRY_SCHEMA:
            raise TuringGateArmError("TURING_ARM_LEDGER_ROW_INVALID")
        core = dict(row)
        claimed = str(core.pop("entry_hash", ""))
        if len(claimed) != 64 or canonical_hash(core) != claimed:
            raise TuringGateArmError("TURING_ARM_LEDGER_ENTRY_HASH_INVALID")
        out.append(row)
    return out


def arm_status(arm: Mapping[str, Any], *, state_dir: str | Path) -> Dict[str, Any]:
    if not verify_arm(arm):
        raise TuringGateArmError("TURING_GATE_ARM_INVALID")
    arm_id = str(arm["arm_id"])
    matches = [row for row in _rows(state_dir) if row.get("arm_id") == arm_id]
    if len(matches) > 1:
        bindings = {(row.get("session_hash"), row.get("result_hash")) for row in matches}
        if len(bindings) > 1:
            raise TuringGateArmError("TURING_ARM_LEDGER_CONFLICT")
    row = matches[-1] if matches else None
    consumed = arm.get("consumed") is True or row is not None
    return {
        "schema": "janus.activator.turing_style_gate_arm_status.v1",
        "arm_id": arm_id,
        "gate_id": str(arm["gate_id"]),
        "consumed": consumed,
        "should_run": bool(arm.get("armed") is True and not consumed),
        "static_consumed": arm.get("consumed") is True,
        "ledger_consumed": row is not None,
        "session_hash": row.get("session_hash") if row else arm.get("consumed_session_hash"),
        "result_hash": row.get("result_hash") if row else arm.get("consumed_result_hash"),
        "retry_delivery_is_new_test": False if consumed else None,
    }


def consume_arm(
    arm: Mapping[str, Any], *, state_dir: str | Path,
    session: Mapping[str, Any], result: Mapping[str, Any], transcript: Mapping[str, Any],
) -> Dict[str, Any]:
    if not verify_arm(arm):
        raise TuringGateArmError("TURING_GATE_ARM_INVALID")
    if arm.get("consumed") is True:
        raise TuringGateArmError("STATICALLY_CONSUMED_TURING_ARM")
    if result.get("terminal") != READY_TERMINAL or result.get("machine_gate_ready") is not True:
        raise TuringGateArmError("TURING_ARM_CONSUMPTION_REQUIRES_MACHINE_READY_WITNESS")
    if result.get("human_blind_adjudication_required") is not True or result.get("classical_turing_verdict") != "NOT_ADJUDICATED":
        raise TuringGateArmError("TURING_ARM_CONSUMPTION_HUMAN_GATE_INVALID")
    if session.get("gate_id") != arm.get("gate_id") or result.get("gate_id") != arm.get("gate_id"):
        raise TuringGateArmError("TURING_ARM_GATE_BINDING_MISMATCH")
    if result.get("transcript_hash") != transcript.get("transcript_hash"):
        raise TuringGateArmError("TURING_ARM_TRANSCRIPT_BINDING_MISMATCH")
    if result.get("session_hash") != session.get("session_hash"):
        raise TuringGateArmError("TURING_ARM_SESSION_BINDING_MISMATCH")
    for key in ("command_authority_granted", "external_effect_authorized"):
        if result.get(key) is not False:
            raise TuringGateArmError(f"TURING_ARM_AUTHORITY_VIOLATION:{key}")

    current = arm_status(arm, state_dir=state_dir)
    if current["consumed"]:
        if current.get("session_hash") == session.get("session_hash") and current.get("result_hash") == result.get("result_hash"):
            return current
        raise TuringGateArmError("TURING_ARM_ALREADY_CONSUMED_BY_DIFFERENT_WITNESS")

    core: Dict[str, Any] = {
        "schema": ENTRY_SCHEMA,
        "arm_id": str(arm["arm_id"]),
        "gate_id": str(arm["gate_id"]),
        "status": "CONSUMED_BY_MACHINE_READY_BLIND_DIALOGUE_WITNESS",
        "session_hash": str(session["session_hash"]),
        "result_hash": str(result["result_hash"]),
        "transcript_hash": str(transcript["transcript_hash"]),
        "resident_uuid": str(result["resident_uuid"]),
        "model_digest": str(result["model_digest"]),
        "human_blind_adjudication_required": True,
        "classical_turing_verdict": "NOT_ADJUDICATED",
        "retry_delivery_is_new_test": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }
    core["entry_hash"] = canonical_hash(core)
    path = _path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(core, ensure_ascii=False, sort_keys=True) + "\n")
    return arm_status(arm, state_dir=state_dir)
