from janus_spi.activator import ActivationLedger
from janus_spi.live_cycle_hardening import HardenedJanusLiveCycleV091
from tests.test_live_cycle import FakeControlPlane


def _cycle(root, control):
    return HardenedJanusLiveCycleV091(
        state_dir=root,
        reader=control,
        packet_opener=control.packet_opener,
        execution_opener=control.execution_opener,
        sleep_fn=lambda _seconds: None,
        poll_interval_seconds=0,
        max_wait_seconds=5,
    )


def test_success_seals_physical_runtime_authority_false(tmp_path):
    control = FakeControlPlane()
    root = tmp_path / "state" / "activator"
    result = _cycle(root, control).run(
        source_ref="TEST_EXTERNAL_TRIGGER/PHYSICAL_CEILING",
        payload={"purpose": "physical-authority witness"},
        dispatch_token="dispatch-token",
        provenance_token="provenance-token",
    )
    assert result["terminal"] == "LIVE_CYCLE_COMPLETED_RETURNED_HOME"
    assert result["physical_runtime_effect_authorized"] is False
    assert result["external_effect_authorized"] is False


def test_same_consumed_stimulus_is_blocked_before_second_wake_or_network(tmp_path):
    control = FakeControlPlane()
    root = tmp_path / "state" / "activator"
    cycle = _cycle(root, control)
    kwargs = {
        "source_ref": "TEST_EXTERNAL_TRIGGER/REPLAY",
        "payload": {"purpose": "one deterministic stimulus only"},
        "dispatch_token": "dispatch-token",
        "provenance_token": "provenance-token",
    }

    first = cycle.run(**kwargs)
    assert first["terminal"] == "LIVE_CYCLE_COMPLETED_RETURNED_HOME"
    activation_rows_before = ActivationLedger(root / "activation_ledger.jsonl").read()
    assert len(activation_rows_before) == 1
    packet_calls_before = control.packet_calls
    execution_calls_before = control.execution_calls

    second = cycle.run(**kwargs)
    assert second["terminal"] == "LIVE_CYCLE_BLOCKED_REPLAYED_STIMULUS"
    assert second["fresh_external_stimulus"] is False
    assert second["wake_hearth_hash"] is None
    assert second["returned_at_home"] is False
    assert second["target_execution_observed"] is False
    assert second["physical_runtime_effect_authorized"] is False
    assert control.packet_calls == packet_calls_before == 1
    assert control.execution_calls == execution_calls_before == 1
    assert len(ActivationLedger(root / "activation_ledger.jsonl").read()) == 1


def test_preflight_failure_does_not_consume_stimulus_identity(tmp_path):
    control = FakeControlPlane()
    root = tmp_path / "state" / "activator"
    cycle = _cycle(root, control)
    source_ref = "TEST_EXTERNAL_TRIGGER/PREFLIGHT_RETRY"
    payload = {"purpose": "credential preflight is not WAKE"}

    blocked = cycle.run(
        source_ref=source_ref,
        payload=payload,
        dispatch_token="",
        provenance_token="",
    )
    assert blocked["terminal"] == "LIVE_CYCLE_BLOCKED_PREFLIGHT_CREDENTIAL"
    assert blocked["wake_hearth_hash"] is None
    assert not (root / "activation_ledger.jsonl").exists()

    completed = cycle.run(
        source_ref=source_ref,
        payload=payload,
        dispatch_token="dispatch-token",
        provenance_token="provenance-token",
    )
    assert completed["terminal"] == "LIVE_CYCLE_COMPLETED_RETURNED_HOME"
    assert control.packet_calls == 1
    assert control.execution_calls == 1
