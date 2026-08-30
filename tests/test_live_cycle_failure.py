from janus_spi.live_cycle import HardenedJanusPersistentStateV09, JanusLiveCycle


class Response204:
    status = 204


class BaselineReader:
    def get_json(self, url):
        if "/actions/workflows/" in url and "/runs?" in url:
            return {"workflow_runs": []}
        raise AssertionError(url)

    def get_bytes(self, url):
        raise AssertionError(url)


class ExplodingAfterWakeCycle(JanusLiveCycle):
    def _wait_for_ack(self, **kwargs):
        raise RuntimeError("synthetic post-WAKE failure")


def test_exception_after_wake_is_checkpointed_and_returns_at_home(tmp_path):
    root = tmp_path / "state" / "activator"
    network_calls = {"count": 0}

    def packet_opener(request, timeout=20.0):
        network_calls["count"] += 1
        return Response204()

    cycle = ExplodingAfterWakeCycle(
        state_dir=root,
        reader=BaselineReader(),
        packet_opener=packet_opener,
        execution_opener=packet_opener,
        sleep_fn=lambda _seconds: None,
        poll_interval_seconds=0,
        max_wait_seconds=5,
    )
    result = cycle.run(
        source_ref="TEST_EXTERNAL_TRIGGER/POST_WAKE_FAILURE",
        payload={"purpose": "prove fail-closed return home"},
        dispatch_token="dispatch-token",
        provenance_token="provenance-token",
    )

    assert result["terminal"] == "LIVE_CYCLE_ABORTED_EXCEPTION"
    assert result["wake_hearth_hash"] is not None
    assert result["checkpoint_hearth_hash"] is not None
    assert result["sleep_hearth_hash"] is not None
    assert result["returned_at_home"] is True
    assert result["target_execution_observed"] is False
    assert result["external_effect_authorized"] is False
    assert network_calls["count"] == 1

    health = HardenedJanusPersistentStateV09(root).verify()
    assert health["ok"] is True
    assert health["mode"] == "AT_HOME"
    assert health["active_cycle_id"] is None
    assert health["component_integrity"]["live_cycle"] is True

    events = [row["event"] for row in cycle.state.hearth.read()]
    assert events[-3:] == [
        "WAKE_FRESH_STIMULUS",
        "CHECKPOINT_LIVE_CYCLE",
        "SLEEP_LIVE_CYCLE",
    ]
