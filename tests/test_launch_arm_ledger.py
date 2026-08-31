import json
from pathlib import Path

import pytest

from janus_spi.launch_arm_ledger import LaunchArmError, arm_status, consume_arm, verify_arm


def arm(consumed=False):
    row = {
        "schema": "janus.activator.real_launch_v2_arm.v1",
        "arm_id": "ARM-1",
        "armed": not consumed,
        "one_shot": True,
        "consumed": consumed,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    if consumed:
        row["consumed_cycle_id"] = "cycle-old"
        row["consumed_receipt_hash"] = "a" * 64
    return row


def result(cycle="cycle-1", receipt="b" * 64):
    return {
        "terminal": "JANUS_REAL_LAUNCH_V2_COMPLETED_RETURNED_HOME",
        "cycle_id": cycle,
        "launch_receipt_hash": receipt,
        "resident_uuid": "75e514ab-be76-42c8-bcb3-fc9670164f96",
        "model_digest": "c" * 64,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }


def test_unconsumed_arm_launches(tmp_path):
    a = arm(False)
    assert verify_arm(a)
    s = arm_status(a, state_dir=tmp_path)
    assert s["should_launch"] is True and s["consumed"] is False


def test_static_consumed_arm_never_launches(tmp_path):
    s = arm_status(arm(True), state_dir=tmp_path)
    assert s["consumed"] is True and s["should_launch"] is False
    assert s["retry_delivery_is_new_launch"] is False


def test_consume_writes_create_once_semantics(tmp_path):
    a = arm(False)
    r = result()
    s = consume_arm(a, state_dir=tmp_path, launch_result=r)
    assert s["consumed"] is True and s["cycle_id"] == "cycle-1"
    s2 = consume_arm(a, state_dir=tmp_path, launch_result=r)
    assert s2["consumed"] is True and s2["launch_receipt_hash"] == "b" * 64
    lines = (tmp_path / "real_launch_v2_arm_ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_different_second_launch_is_blocked(tmp_path):
    a = arm(False)
    consume_arm(a, state_dir=tmp_path, launch_result=result())
    with pytest.raises(LaunchArmError, match="DIFFERENT_LAUNCH"):
        consume_arm(a, state_dir=tmp_path, launch_result=result("cycle-2", "d" * 64))


def test_failed_launch_does_not_consume(tmp_path):
    a = arm(False)
    r = result()
    r["terminal"] = "FAILED"
    with pytest.raises(LaunchArmError, match="SUCCESSFUL_LAUNCH"):
        consume_arm(a, state_dir=tmp_path, launch_result=r)
    assert arm_status(a, state_dir=tmp_path)["consumed"] is False


def test_authority_escalation_cannot_consume(tmp_path):
    a = arm(False)
    r = result()
    r["world_truth_authority_granted"] = True
    with pytest.raises(LaunchArmError, match="AUTHORITY_VIOLATION"):
        consume_arm(a, state_dir=tmp_path, launch_result=r)


def test_tampered_ledger_fails_closed(tmp_path):
    path = tmp_path / "real_launch_v2_arm_ledger.jsonl"
    path.write_text(json.dumps({"schema": "bad", "arm_id": "ARM-1", "entry_hash": "0" * 64}) + "\n")
    with pytest.raises(LaunchArmError, match="ENTRY_HASH_INVALID"):
        arm_status(arm(False), state_dir=tmp_path)


def test_invalid_static_state_rejected():
    a = arm(False)
    a["consumed"] = True
    assert verify_arm(a) is False
