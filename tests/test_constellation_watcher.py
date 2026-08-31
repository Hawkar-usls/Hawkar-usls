from __future__ import annotations

import json
from pathlib import Path

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.constellation_watcher import ConstellationWatcher, ConstellationWatcherError


class FakeReader:
    def __init__(self, heads):
        self.heads = dict(heads)
        self.calls = []

    def branch_head(self, repository: str, branch: str):
        self.calls.append((repository, branch))
        value = self.heads.get((repository, branch))
        if isinstance(value, Exception):
            raise value
        return value


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


def baseline_reader(head_a="a" * 40, head_b="b" * 40):
    return FakeReader(
        {
            ("Hawkar-usls/Hawkar-usls", "main"): head_a,
            ("Hawkar-usls/janus-meta-registry", "main"): head_b,
        }
    )


def test_first_scan_initializes_without_cognition(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 1.0)
    result = watcher.scan(model_lock("a" * 40))
    assert result["terminal"] == "CONSTELLATION_BASELINE_INITIALIZED"
    assert result["new_stimulus_count"] == 0
    assert result["pending_stimulus_count"] == 0
    verified = watcher.verify()
    assert verified["ok"] is True
    assert verified["stimulus_count"] == 0


def test_preflight_requires_full_scan_when_baseline_missing(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 1.0)
    reader = baseline_reader()
    result = watcher.preflight(reader)
    assert result["terminal"] == "CONSTELLATION_PREFLIGHT_BASELINE_MISSING"
    assert result["requires_full_scan"] is True
    assert reader.calls == []


def test_preflight_quiet_uses_only_sealed_exact_refs(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 2.0)
    watcher.scan(model_lock("a" * 40))
    reader = baseline_reader()
    result = watcher.preflight(reader)
    assert result["terminal"] == "CONSTELLATION_PREFLIGHT_QUIET"
    assert result["requires_full_scan"] is False
    assert result["drift_count"] == 0
    assert sorted(reader.calls) == [
        ("Hawkar-usls/Hawkar-usls", "main"),
        ("Hawkar-usls/janus-meta-registry", "main"),
    ]


def test_preflight_drift_escalates_without_mutating_baseline(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 3.0)
    watcher.scan(model_lock("a" * 40))
    before = (tmp_path / "constellation" / "HEADS.json").read_text()
    reader = baseline_reader(head_b="c" * 40)
    result = watcher.preflight(reader)
    after = (tmp_path / "constellation" / "HEADS.json").read_text()
    assert result["terminal"] == "CONSTELLATION_PREFLIGHT_DRIFT"
    assert result["requires_full_scan"] is True
    assert result["drift_count"] == 1
    assert result["drift"][0]["repository"] == "Hawkar-usls/janus-meta-registry"
    assert before == after


def test_preflight_unresolved_escalates_fail_closed(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 4.0)
    watcher.scan(model_lock("a" * 40))
    reader = baseline_reader()
    reader.heads[("Hawkar-usls/janus-meta-registry", "main")] = None
    result = watcher.preflight(reader)
    assert result["terminal"] == "CONSTELLATION_PREFLIGHT_INDETERMINATE"
    assert result["requires_full_scan"] is True
    assert result["unresolved_count"] == 1


def test_head_change_becomes_one_pending_stimulus_and_retry_dedups(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 5.0)
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


def test_preflight_resumes_crash_safe_pending_before_head_poll(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 6.0)
    watcher.scan(model_lock("a" * 40))
    changed = watcher.scan(model_lock("c" * 40))
    assert changed["pending_stimulus_count"] == 1
    reader = FakeReader({})
    result = watcher.preflight(reader)
    assert result["terminal"] == "CONSTELLATION_PREFLIGHT_PENDING_STIMULI"
    assert result["requires_full_scan"] is True
    assert result["pending_stimulus_count"] == 1
    assert reader.calls == []


def test_pending_survives_until_cycle_receipt_then_quiets(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 7.0)
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


def test_exact_reconcile_retry_returns_existing_cycle_without_timestamp_conflict(tmp_path: Path):
    first = ConstellationWatcher(tmp_path, now_fn=lambda: 8.0)
    first.scan(model_lock("a" * 40))
    changed = first.scan(model_lock("c" * 40))
    sid = changed["pending_stimuli"][0]["stimulus_id"]
    receipt = runtime_receipt(sid)
    a = first.reconcile(sid, receipt)
    second = ConstellationWatcher(tmp_path, now_fn=lambda: 999.0)
    b = second.reconcile(sid, receipt)
    assert a == b
    assert b["created_at"] == 8.0


def test_reconcile_fails_closed_on_motor_authority(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 9.0)
    watcher.scan(model_lock("a" * 40))
    changed = watcher.scan(model_lock("c" * 40))
    sid = changed["pending_stimuli"][0]["stimulus_id"]
    receipt = runtime_receipt(sid)
    receipt["dispatch_authorized"] = True
    with pytest.raises(ConstellationWatcherError, match="R1_DISPATCH_MUST_REMAIN_FALSE"):
        watcher.reconcile(sid, receipt)


def test_persistent_state_branch_is_not_part_of_sensory_snapshot(tmp_path: Path):
    watcher = ConstellationWatcher(tmp_path, now_fn=lambda: 10.0)
    result = watcher.scan(model_lock("a" * 40))
    heads = json.loads((tmp_path / "constellation" / "HEADS.json").read_text())
    assert heads["persistent_state_branches_are_sensory_inputs"] is False
    branches = {row["branch"] for row in heads["members"].values()}
    assert "janus/activator-state" not in branches
    assert result["pending_stimulus_count"] == 0
