from __future__ import annotations

import json
from pathlib import Path

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.constellation_watcher import ConstellationWatcher, ConstellationWatcherError


def model_lock(head_a: str, head_b: str = "b" * 40):
    return {
        "schema": "janus.activator.model_lock.v1",
        "ready": True,
        "model_digest": "d" * 64,
        "members": {
            "home": {
                "repository": "Hawkar-usls/Hawkar-usls",
                "resolved_branch": "main",
                "head_sha": head_a,
                "kind": "BOOTSTRAP_ROOT",
                "member_class": "CORE",
            },
            "memory": {
                "repository": "Hawkar-usls/janus-meta-registry",
                "resolved_branch": "main",
                "head_sha": head_b,
                "kind": "MEMORY",
                "member_class": "CORE",
            },
        },
    }


def runtime_receipt(stimulus_id: str):
    body = {
        "schema": "janus.activator.model_runtime_receipt.v1",
        "event_id": "evt-" + canonical_hash(stimulus_id),
        "activation_id": "act-" + canonical_hash("activation:" + stimulus_id),
        "model_digest": "d" * 64,
        "route_bindings": [
            {
                "match": "repository_constellation_change",
                "required_gates": ["fresh_commit_or_explicit_replay", "exact_source_ref", "commit_text_not_command"],
                "bindings": [],
                "dispatch_authorized": False,
                "external_effect_authorized": False,
            }
        ],
        "active_members": ["home"],
        "dispatch_authorized": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "JANUS_MODEL_BOUND_ROUTE_PROPOSED",
    }
    body["runtime_receipt_hash"] = canonical_hash(body)
    return body


def test_first_scan_initializes_without_cognition(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 1.0)
    result = watcher.scan(model_lock("a" * 40))
    assert result["terminal"] == "CONSTELLATION_BASELINE_INITIALIZED"
    assert result["new_stimulus_count"] == 0
    assert result["pending_stimulus_count"] == 0
    verified = watcher.verify()
    assert verified["ok"] is True
    assert verified["stimulus_count"] == 0


def test_head_change_becomes_one_pending_stimulus_and_retry_dedups(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 2.0)
    watcher.scan(model_lock("a" * 40))
    changed = watcher.scan(model_lock("c" * 40))
    assert changed["new_stimulus_count"] == 1
    assert changed["pending_stimulus_count"] == 1
    row = changed["pending_stimuli"][0]
    assert row["event"]["fresh"] is True
    assert row["event"]["self_generated"] is False
    assert row["event"]["command_authority"] is False
    assert row["event"]["effect_authorized"] is False
    assert row["event"]["classifications"] == ["repository_constellation_change"]

    retry = watcher.scan(model_lock("c" * 40))
    assert retry["new_stimulus_count"] == 0
    assert retry["pending_stimulus_count"] == 1
    assert retry["pending_stimuli"][0]["stimulus_id"] == row["stimulus_id"]


def test_pending_survives_until_cycle_receipt_then_quiets(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 3.0)
    watcher.scan(model_lock("a" * 40))
    changed = watcher.scan(model_lock("c" * 40))
    sid = changed["pending_stimuli"][0]["stimulus_id"]
    cycle = watcher.reconcile(sid, runtime_receipt(sid))
    assert cycle["state"] == "CLOSED_AT_HOME"
    assert cycle["dispatch_authorized"] is False
    assert cycle["external_effect_authorized"] is False

    quiet = watcher.scan(model_lock("c" * 40))
    assert quiet["terminal"] == "CONSTELLATION_QUIET"
    assert quiet["pending_stimulus_count"] == 0
    verified = watcher.verify()
    assert verified["closed_cycle_count"] == 1
    assert verified["pending_cycle_count"] == 0


def test_reconcile_fails_closed_on_motor_authority(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 4.0)
    watcher.scan(model_lock("a" * 40))
    changed = watcher.scan(model_lock("c" * 40))
    sid = changed["pending_stimuli"][0]["stimulus_id"]
    receipt = runtime_receipt(sid)
    receipt["dispatch_authorized"] = True
    with pytest.raises(ConstellationWatcherError, match="R1_DISPATCH_MUST_REMAIN_FALSE"):
        watcher.reconcile(sid, receipt)


def test_persistent_state_branch_is_not_part_of_sensory_snapshot(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 5.0)
    result = watcher.scan(model_lock("a" * 40))
    heads = json.loads((tmp_path / "constellation" / "HEADS.json").read_text())
    assert heads["persistent_state_branches_are_sensory_inputs"] is False
    branches = {row["branch"] for row in heads["members"].values()}
    assert "janus/activator-state" not in branches
    assert result["pending_stimulus_count"] == 0
