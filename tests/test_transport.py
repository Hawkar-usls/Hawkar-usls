import json
import urllib.error
from pathlib import Path

from janus_spi.activator import ActivationEvent, JanusActivator
from janus_spi.dispatch import JanusDispatchBroker
from janus_spi.transport import JanusTransportBroker


class FakeResponse:
    def __init__(self, status=204):
        self.status = status


class CountingOpener:
    def __init__(self, *, status=204, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def __call__(self, request, timeout=20.0):
        self.calls.append({
            "url": request.full_url,
            "method": request.get_method(),
            "timeout": timeout,
            "authorization_present": bool(request.headers.get("Authorization")),
            "payload": json.loads(request.data.decode("utf-8")),
        })
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status)


def demiurge_packet(tmp_path: Path):
    state = tmp_path / "state"
    activator = JanusActivator(state_dir=state)
    activation = activator.activate(ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="Hawkar-usls/janus-meta-registry@transport-test",
        payload={"kind": "registry_change"},
        classifications=["research_or_anomaly_investigation"],
        fresh=True,
    ))
    dispatch = JanusDispatchBroker(state_dir=state).dispatch(
        activation,
        target_organ="Hawkar-usls/Janus-Demiurge",
    )
    packet = json.loads(Path(dispatch["packet_path"]).read_text(encoding="utf-8"))
    return state, packet


def test_http_204_is_sent_awaiting_ack_not_execution(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    opener = CountingOpener(status=204)
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    receipt = broker.send(packet, token="test-token-never-persist")

    assert receipt["terminal"] == "TRANSPORT_SENT_AWAITING_ACK"
    assert receipt["network_boundary_entered"] is True
    assert receipt["automatic_retry_allowed"] is False
    assert receipt["http_status"] == 204
    assert receipt["external_effect_authorized"] is False
    assert receipt["target_execution_authorized"] is False
    assert len(opener.calls) == 1
    assert opener.calls[0]["payload"]["event_type"] == "janus-activator-dispatch-v0.3"
    assert opener.calls[0]["payload"]["client_payload"]["packet"]["packet_id"] == packet["packet_id"]
    assert broker.ledger.verify() is True

    ledger_text = (state / "transport_ledger.jsonl").read_text(encoding="utf-8")
    assert "test-token-never-persist" not in ledger_text


def test_same_packet_cannot_cross_network_boundary_twice(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    opener = CountingOpener(status=204)
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    first = broker.send(packet, token="token")
    second = broker.send(packet, token="token")

    assert first["terminal"] == "TRANSPORT_SENT_AWAITING_ACK"
    assert second["terminal"] == "TRANSPORT_REPLAY_BLOCKED"
    assert second["network_boundary_entered"] is False
    assert second["automatic_retry_allowed"] is False
    assert len(opener.calls) == 1
    assert broker.ledger.verify() is True


def test_timeout_becomes_outcome_undetermined_and_blocks_retry(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    opener = CountingOpener(error=TimeoutError("ambiguous network timeout"))
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    first = broker.send(packet, token="token")
    second = broker.send(packet, token="token")

    assert first["terminal"] == "TRANSPORT_OUTCOME_UNDETERMINED"
    assert first["network_boundary_entered"] is True
    assert first["automatic_retry_allowed"] is False
    assert second["terminal"] == "TRANSPORT_REPLAY_BLOCKED"
    assert len(opener.calls) == 1


def test_missing_credential_is_pre_effect_and_can_retry_after_fix(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    opener = CountingOpener(status=204)
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    blocked = broker.send(packet, token="")
    sent = broker.send(packet, token="now-present")

    assert blocked["terminal"] == "TRANSPORT_BLOCKED_NO_CREDENTIAL"
    assert blocked["network_boundary_entered"] is False
    assert blocked["automatic_retry_allowed"] is True
    assert sent["terminal"] == "TRANSPORT_SENT_AWAITING_ACK"
    assert len(opener.calls) == 1


def test_invalid_packet_is_pre_effect_rejected_without_network(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    packet["route_match"] = "tampered"
    opener = CountingOpener(status=204)
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    receipt = broker.send(packet, token="token")

    assert receipt["terminal"] == "TRANSPORT_PRE_EFFECT_REJECTED_INVALID_PACKET"
    assert receipt["network_boundary_entered"] is False
    assert receipt["automatic_retry_allowed"] is True
    assert len(opener.calls) == 0


def test_unsupported_target_is_pre_effect_rejected(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    # Rebuilding the dispatch packet for another target is outside v0.4 transport scope.
    packet["target_organ"] = "Hawkar-usls/Demi_Head"
    from janus_spi.activator import canonical_hash
    packet["packet_id"] = "dsp-" + canonical_hash({
        "activation_receipt_hash": packet["activation_receipt_hash"],
        "target_organ": packet["target_organ"],
        "operation": packet["operation"],
    })
    packet.pop("packet_hash", None)
    packet["packet_hash"] = canonical_hash(packet)
    opener = CountingOpener(status=204)
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    receipt = broker.send(packet, token="token")

    assert receipt["terminal"] == "TRANSPORT_PRE_EFFECT_REJECTED_UNSUPPORTED_TARGET"
    assert receipt["network_boundary_entered"] is False
    assert len(opener.calls) == 0


def test_unexpected_http_status_is_ambiguous_and_not_retried(tmp_path):
    state, packet = demiurge_packet(tmp_path)
    opener = CountingOpener(status=202)
    broker = JanusTransportBroker(state_dir=state, opener=opener)

    first = broker.send(packet, token="token")
    second = broker.send(packet, token="token")

    assert first["terminal"] == "TRANSPORT_OUTCOME_UNDETERMINED"
    assert first["http_status"] == 202
    assert second["terminal"] == "TRANSPORT_REPLAY_BLOCKED"
    assert len(opener.calls) == 1
