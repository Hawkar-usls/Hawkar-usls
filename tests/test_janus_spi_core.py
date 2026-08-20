import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from janus_spi.core import JanusSPICore, SemanticEvent


def test_semantic_ingest_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        core = JanusSPICore(tmp)
        a = SemanticEvent.build("test", "a", "black hole ringdown and horizon area")
        b = SemanticEvent.build("test", "b", "bacterial cellulose oil sorbent")
        assert core.observe(a) is True
        assert core.observe(b) is True
        hits = core.semantic_search("horizon black hole", limit=2)
        assert hits
        assert hits[0]["event"]["event_id"] == a.event_id


def test_binary_online_learning_forecast_and_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        core = JanusSPICore(tmp)
        positive = SemanticEvent.build("test", "positive", "high activity many verified commits")
        negative = SemanticEvent.build("test", "negative", "quiet interval no changes")
        for _ in range(8):
            core.learn("activity", "BINARY_PROBABILITY", positive, 1.0, provenance={"EVIDENCE_SOURCE": "TEST"})
            core.learn("activity", "BINARY_PROBABILITY", negative, 0.0, provenance={"EVIDENCE_SOURCE": "TEST"})

        target_time = time.time() + 0.05
        forecast = core.predict(
            "activity",
            positive,
            {"event": "activity", "resolution": "binary"},
            target_time=target_time,
        )
        assert 0.0 <= forecast.probability_or_value <= 1.0
        time.sleep(0.06)
        result = core.resolve(forecast.forecast_id, 1.0)
        assert result["scoring_rule"] == "BRIER"
        assert result["score"] >= 0.0


def test_untrained_task_cannot_predict():
    with tempfile.TemporaryDirectory() as tmp:
        core = JanusSPICore(tmp)
        event = SemanticEvent.build("test", "x", "no resolved label yet")
        try:
            core.predict("unknown", event, {"event": "x"}, time.time() + 10)
        except ValueError as exc:
            assert "no resolved-label training history" in str(exc)
        else:
            raise AssertionError("untrained task must fail closed")
