import json
from pathlib import Path

from janus_spi.execution_grant import ExecutionGrantLedger
from janus_spi.persistent_state_v07 import HardenedJanusPersistentState


def _tamper_first_row(path: Path):
    rows = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    row["created_at"] = float(row.get("created_at", 0)) + 1.0
    rows[0] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_v07_hearth_health_includes_execution_grant_chain(tmp_path):
    root = tmp_path / "state" / "activator"
    state = HardenedJanusPersistentState(root)
    state.hearth_cycle(
        source="PYTEST",
        reason="V07_GRANT_HEALTH",
        architecture_sha="a" * 40,
    )

    ledger = ExecutionGrantLedger(root / "execution_grant_ledger.jsonl")
    ledger.append({
        "schema": "test.execution.grant",
        "grant_id": "xg-test",
        "created_at": 1.0,
        "parent_grant_hash": None,
        "terminal": "TEST_ONLY",
    })

    healthy = HardenedJanusPersistentState(root).verify()
    assert healthy["ok"] is True
    assert healthy["component_integrity"]["execution_grant"] is True

    _tamper_first_row(root / "execution_grant_ledger.jsonl")
    corrupt = HardenedJanusPersistentState(root).verify()
    assert corrupt["ok"] is False
    assert corrupt["component_integrity"]["execution_grant"] is False
