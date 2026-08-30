from __future__ import annotations

import json
from pathlib import Path

import pytest

from janus_spi.file_fabric import FileFabricCompiler, FileFabricError


REGISTRY = Path("config/JANUS_FILE_FORMAT_REGISTRY-v1.json")


class FakeTreeReader:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def recursive_tree(self, repository, sha):
        self.calls.append((repository, sha))
        value = self.values.get((repository, sha))
        if isinstance(value, Exception):
            raise value
        return value


def model_lock(*, optional=False):
    members = {
        "bootstrap_root": {
            "kind": "BOOTSTRAP_ROOT",
            "repository": "Hawkar-usls/Hawkar-usls",
            "head_sha": "a" * 40,
            "required": True,
            "load_mode": "REQUIRED_BOOT_PRESENCE",
        },
        "anomaly_lab": {
            "kind": "ORGAN",
            "repository": "Hawkar-usls/TOPA",
            "head_sha": "b" * 40,
            "required": True,
            "load_mode": "REQUIRED_BOOT_PRESENCE",
        },
    }
    if optional:
        members["toolchain:legacy"] = {
            "kind": "TOOLCHAIN_DEPENDENCY",
            "repository": "Hawkar-usls/legacy-tool",
            "head_sha": "c" * 40,
            "required": False,
            "load_mode": "REFERENCE_ONLY",
        }
    return {
        "schema": "janus.activator.model_lock.v1",
        "ready": True,
        "model_digest": "d" * 64,
        "members": members,
    }


def tree(*paths, truncated=False):
    return {
        "sha": "0" * 40,
        "truncated": truncated,
        "tree": [
            {"path": path, "type": "blob", "sha": str(index + 1) * 40}
            for index, path in enumerate(paths)
        ],
    }


def compiler(values):
    return FileFabricCompiler.from_file(REGISTRY, reader=FakeTreeReader(values))


def test_registry_knows_canonical_polyglot_formats_and_vce_stays_opaque():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    required = {
        ".json", ".py", ".js", ".mjs", ".html", ".c", ".cpp", ".cc", ".cxx",
        ".h", ".hpp", ".sh", ".ps1", ".bat", ".cmd", ".yml", ".yaml", ".vce",
    }
    assert required.issubset(registry["formats"])
    assert all(row["default_execution_authorized"] is False for row in registry["formats"].values())
    assert registry["formats"][".vce"]["family"] == "CUSTOM"
    assert registry["formats"][".vce"]["adapter"] is None
    assert "NO_SEMANTIC_GUESSING" in registry["formats"][".vce"]["execution_mode"]


def test_exact_sha_file_fabric_classifies_multiple_tissue_families_without_authority():
    lock = model_lock()
    values = {
        ("Hawkar-usls/Hawkar-usls", "a" * 40): tree(
            "root.json", "src/main.py", ".github/workflows/boot.yml", "web/index.html", "web/app.js"
        ),
        ("Hawkar-usls/TOPA", "b" * 40): tree(
            "tools/detective.py", "protocol.json", "native/engine.cpp", "native/engine.hpp",
            "scripts/test.sh", "custom/mystery.vce", "README.md", "blob.weird"
        ),
    }
    result = compiler(values).compile(lock)
    assert result["ready"] is True
    assert result["coverage_complete"] is True
    assert result["terminal"] == "JANUS_POLYGLOT_FILE_FABRIC_LOCKED"
    assert result["scanned_member_count"] == 2
    assert result["family_totals"]["JSON"] == 2
    assert result["family_totals"]["PYTHON"] == 2
    assert result["family_totals"]["YAML"] == 1
    assert result["family_totals"]["HTML"] == 1
    assert result["family_totals"]["JAVASCRIPT"] == 1
    assert result["family_totals"]["C_CPP"] == 2
    assert result["family_totals"]["SHELL"] == 1
    assert result["family_totals"]["CUSTOM"] == 1
    topa = result["member_tissues"]["anomaly_lab"]
    assert topa["custom_tissue_files"] == 1
    assert topa["unknown_extension_counts"][".weird"] == 1
    assert result["execution_authority_granted"] is False
    assert result["external_effect_authorized"] is False
    assert result["physical_runtime_effect_authorized"] is False
    assert len(result["file_fabric_digest"]) == 64


def test_required_truncated_tree_is_unknown_resource_limit_and_fail_closed():
    lock = model_lock()
    values = {
        ("Hawkar-usls/Hawkar-usls", "a" * 40): tree("main.py"),
        ("Hawkar-usls/TOPA", "b" * 40): tree("detective.py", truncated=True),
    }
    result = compiler(values).compile(lock)
    assert result["ready"] is False
    assert result["coverage_complete"] is False
    assert result["terminal"] == "JANUS_POLYGLOT_FILE_FABRIC_FAIL_CLOSED"
    assert result["required_failures"] == ["anomaly_lab"]
    assert result["member_tissues"]["anomaly_lab"]["scan_status"] == "UNKNOWN_RESOURCE_LIMIT"


def test_optional_truncated_tree_preserves_ready_but_never_claims_complete_coverage():
    lock = model_lock(optional=True)
    values = {
        ("Hawkar-usls/Hawkar-usls", "a" * 40): tree("main.py"),
        ("Hawkar-usls/TOPA", "b" * 40): tree("detective.py"),
        ("Hawkar-usls/legacy-tool", "c" * 40): tree("legacy.cpp", truncated=True),
    }
    result = compiler(values).compile(lock)
    assert result["ready"] is True
    assert result["coverage_complete"] is False
    assert result["terminal"] == "JANUS_POLYGLOT_FILE_FABRIC_LOCKED_WITH_BOUNDED_UNKNOWN"
    assert result["bounded_unknown"] == ["toolchain:legacy"]


def test_missing_required_tree_is_not_silently_treated_as_no_files():
    lock = model_lock()
    values = {
        ("Hawkar-usls/Hawkar-usls", "a" * 40): tree("main.py"),
        ("Hawkar-usls/TOPA", "b" * 40): None,
    }
    result = compiler(values).compile(lock)
    assert result["ready"] is False
    assert result["required_failures"] == ["anomaly_lab"]
    assert result["member_tissues"]["anomaly_lab"]["scan_status"] == "REQUIRED_TREE_UNAVAILABLE"


def test_model_must_be_locked_before_tissue_scan():
    bad = model_lock()
    bad["ready"] = False
    with pytest.raises(FileFabricError, match="MODEL_LOCK_MUST_BE_READY"):
        compiler({}).compile(bad)


def test_registry_rejects_any_format_that_grants_execution_by_extension():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["formats"][".py"]["default_execution_authorized"] = True
    with pytest.raises(FileFabricError, match="FORMAT_MUST_NOT_GRANT_DEFAULT_EXECUTION"):
        FileFabricCompiler(registry, reader=FakeTreeReader({}))
