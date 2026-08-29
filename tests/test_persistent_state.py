import json
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.persistent_state import JanusPersistentState
from janus_spi.transport import TransportLedger


def _cycle(state: JanusPersistentState, architecture_sha="a" * 40):
    return state.hearth_cycle(
        source="PYTEST",
        reason="CONTINUITY_TEST",
        architecture_sha=architecture_sha,
        workflow_run_id="123",
    )


def _tamper_first_row(path: Path):
    rows = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    row["created_at"] = float(row.get("created_at", 0)) + 0.25
    rows[0] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_first_hearth_cycle_initializes_and_returns_home(tmp_path):
    root = tmp_path / "state" / "activator"
    state = JanusPersistentState(root)

    result = _cycle(state)
    health = state.verify()

    assert result["state_healthy"] is True
    assert result["mode"] == "AT_HOME"
    assert result["fresh_stimulus"] is False
    assert result["cognition_authorized"] is False
    assert result["dispatch_authorized"] is False
    assert result["target_execution_authorized"] is False
    assert result["external_effect_authorized"] is False
    assert health["ok"] is True
    assert health["mode"] == "AT_HOME"
    assert len(state.hearth.read()) == 3
    assert [x["event"] for x in state.hearth.read()] == ["WAKE", "HEARTBEAT", "SLEEP"]


def test_second_process_style_cycle_preserves_identity_and_extends_hash_chain(tmp_path):
    root = tmp_path / "state" / "activator"
    first = JanusPersistentState(root)
    first_result = _cycle(first, "a" * 40)
    identity_one = json.loads((root / "identity.json").read_text(encoding="utf-8"))

    second = JanusPersistentState(root)
    second_result = _cycle(second, "b" * 40)
    identity_two = json.loads((root / "identity.json").read_text(encoding="utf-8"))

    assert identity_two == identity_one
    assert second_result["resident_uuid"] == first_result["resident_uuid"]
    rows = second.hearth.read()
    assert len(rows) == 6
    assert rows[3]["parent_hearth_hash"] == rows[2]["receipt_hash"]
    assert second.hearth.verify() is True
    assert second.verify()["ok"] is True


def test_scheduled_hearth_never_creates_fresh_cognitive_stimulus(tmp_path):
    state = JanusPersistentState(tmp_path / "state" / "activator")
    _cycle(state)

    for row in state.hearth.read():
        assert row["fresh_stimulus"] is False
        assert row["cognition_authorized"] is False
        assert row["dispatch_authorized"] is False
        assert row["target_execution_authorized"] is False
        assert row["external_effect_authorized"] is False


def test_identity_tamper_fails_closed(tmp_path):
    root = tmp_path / "state" / "activator"
    state = JanusPersistentState(root)
    _cycle(state)
    identity = json.loads((root / "identity.json").read_text(encoding="utf-8"))
    identity["resident_uuid"] = "forged"
    (root / "identity.json").write_text(json.dumps(identity), encoding="utf-8")

    health = JanusPersistentState(root).verify()

    assert health["ok"] is False
    assert health["status"] == "CORRUPT_FAIL_CLOSED"


def test_hearth_chain_tamper_fails_closed(tmp_path):
    root = tmp_path / "state" / "activator"
    state = JanusPersistentState(root)
    _cycle(state)
    _tamper_first_row(root / "hearth_ledger.jsonl")

    health = JanusPersistentState(root).verify()

    assert health["ok"] is False
    assert health["component_integrity"]["hearth"] is False


def test_known_component_ledger_corruption_fails_persistent_health(tmp_path):
    root = tmp_path / "state" / "activator"
    state = JanusPersistentState(root)
    _cycle(state)

    ledger = TransportLedger(root / "transport_ledger.jsonl")
    row = {
        "schema": "test.transport.row",
        "parent_transport_hash": None,
        "packet_id": "dsp-" + "1" * 64,
        "created_at": 1.0,
    }
    row["receipt_hash"] = canonical_hash(row)
    (root / "transport_ledger.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    assert ledger.verify() is True

    _tamper_first_row(root / "transport_ledger.jsonl")
    health = JanusPersistentState(root).verify()

    assert health["ok"] is False
    assert health["component_integrity"]["transport"] is False


def test_architecture_observation_is_non_authoritative(tmp_path):
    root = tmp_path / "state" / "activator"
    state = JanusPersistentState(root)
    _cycle(state, "c" * 40)

    observation = json.loads((root / "observations" / "latest_architecture.json").read_text(encoding="utf-8"))
    claimed = observation.pop("observation_hash")

    assert canonical_hash(observation) == claimed
    assert observation["architecture_sha"] == "c" * 40
    assert observation["fresh_stimulus"] is False
    assert observation["command_authority_granted"] is False
    assert observation["external_effect_authorized"] is False
