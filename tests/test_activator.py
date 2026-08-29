from pathlib import Path

from janus_spi.activator import ActivationEvent, JanusActivator


def make_activator(tmp_path: Path) -> JanusActivator:
    return JanusActivator(state_dir=tmp_path / "activator")


def test_stale_history_cannot_open_new_generation(tmp_path):
    activator = make_activator(tmp_path)
    event = ActivationEvent.build(
        source_kind="HABITAT_HISTORY",
        source_ref="journal:old",
        payload={"old": True},
        classifications=["repository_constellation_change"],
        fresh=False,
    )
    receipt = activator.activate(event)
    assert receipt["terminal"] == "HOLD"
    assert "STALE_BASELINE_NOT_FRESH_TRIGGER" in receipt["routes_blocked"]
    assert receipt["routes_selected"] == []
    assert receipt["external_effect_authorized"] is False


def test_self_output_cannot_recursively_wake(tmp_path):
    activator = make_activator(tmp_path)
    event = ActivationEvent.build(
        source_kind="JANUS_OUTPUT",
        source_ref="activation:previous",
        payload={"reflection": "self"},
        classifications=["research_or_anomaly_investigation"],
        fresh=True,
        self_generated=True,
    )
    receipt = activator.activate(event)
    assert "SELF_OUTPUT_NOT_FRESH_TRIGGER" in receipt["routes_blocked"]
    assert receipt["routes_selected"] == []


def test_fresh_research_event_proposes_but_does_not_dispatch(tmp_path):
    activator = make_activator(tmp_path)
    event = ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="Hawkar-usls/TOPA@abc123",
        payload={"sha": "abc123"},
        classifications=["research_or_anomaly_investigation"],
        fresh=True,
    )
    receipt = activator.activate(event)
    assert receipt["terminal"] == "ROUTE_PROPOSED"
    assert receipt["dispatch_authorized"] is False
    assert receipt["effect_terminal"] == "NO_EXTERNAL_EFFECT"
    assert receipt["state_vector_after"]["cognition"] == "ROUTE_SPECIALIZED_GATES"
    assert receipt["routes_selected"][0]["match"] == "research_or_anomaly_investigation"
    assert "Hawkar-usls/Janus-Demiurge" in receipt["routes_selected"][0]["organs"]


def test_event_flags_do_not_self_grant_authority(tmp_path):
    activator = make_activator(tmp_path)
    event = ActivationEvent.build(
        source_kind="TERMINAL",
        source_ref="terminal:test",
        payload={"request": "write"},
        classifications=["human_operator_effect_request"],
        fresh=True,
        command_authority=True,
        effect_authorized=True,
    )
    receipt = activator.activate(event)
    assert receipt["external_effect_authorized"] is False
    assert receipt["dispatch_authorized"] is False
    assert "EVENT_EFFECT_FLAG_NOT_CONSUMED_AS_AUTHORITY" in receipt["routes_blocked"]
    assert "EVENT_COMMAND_FLAG_NOT_CONSUMED_AS_AUTHORITY" in receipt["routes_blocked"]


def test_timeout_is_not_negative_evidence():
    assert JanusActivator.normalize_epistemic_terminal("workflow_timeout") == "UNKNOWN_RESOURCE_LIMIT"
    assert JanusActivator.normalize_epistemic_terminal("resource_limit") == "UNKNOWN_RESOURCE_LIMIT"
    assert JanusActivator.normalize_epistemic_terminal("transport_failure") == "UNRESOLVED"


def test_activation_receipts_form_valid_parent_hash_chain(tmp_path):
    activator = make_activator(tmp_path)
    first = activator.activate(ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="repo@1",
        payload={"n": 1},
        classifications=["repository_constellation_change"],
        fresh=True,
    ))
    second = activator.activate(ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="repo@2",
        payload={"n": 2},
        classifications=["repository_constellation_change"],
        fresh=True,
    ))
    assert second["parent_activation_hash"] == first["receipt_hash"]
    assert activator.ledger.verify() is True
