from __future__ import annotations

import json
from pathlib import Path

import pytest

from run_janus_unified import load_or_compile_model_lock


def valid_lock():
    return {
        "schema": "janus.activator.model_lock.v1",
        "ready": True,
        "model_digest": "d" * 64,
        "members": {
            "bootstrap_root": {
                "repository": "Hawkar-usls/Hawkar-usls",
                "resolved_branch": "main",
                "head_sha": "a" * 40,
            }
        },
        "organs": {},
        "candidate_runtime_tissues": {},
    }


def test_precompiled_lock_is_loaded_without_live_compile(tmp_path: Path):
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(valid_lock()), encoding="utf-8")
    value, source = load_or_compile_model_lock(model_lock_in=str(path), manifest="must-not-be-read.json")
    assert source == "PRECOMPILED_EXACT_LOCK"
    assert value["model_digest"] == "d" * 64


def test_precompiled_lock_must_be_ready(tmp_path: Path):
    lock = valid_lock()
    lock["ready"] = False
    lock["failures"] = {"required_members_missing": ["memory"]}
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        load_or_compile_model_lock(model_lock_in=str(path), manifest="unused.json")
    assert exc.value.code == 2


def test_precompiled_lock_requires_expected_schema(tmp_path: Path):
    lock = valid_lock()
    lock["schema"] = "wrong"
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(SystemExit, match="JANUS_MODEL_LOCK_SCHEMA_INVALID"):
        load_or_compile_model_lock(model_lock_in=str(path), manifest="unused.json")
