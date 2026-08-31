import hashlib
import json

import pytest

from janus_spi.activator import ActivationEvent
from janus_spi.activator_slime_r0 import SlimeAwareJanusActivatorR0
from janus_spi.slime_memory import JanusActivatorSlimeMemoryR0, RECEIPT_CLASS


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sealed_receipt(
    route_match,
    *,
    terminal="VERIFIED_SUCCESS",
    source="a",
    verifier="b",
    gross_saved_work=10.0,
    learning_cost_work=1.0,
    finalized=True,
):
    body = {
        "receipt_class": RECEIPT_CLASS,
        "finalized": finalized,
        "route_match": route_match,
        "route_terminal": terminal,
        "source_digest": source * 64,
        "verifier_digest": verifier * 64,
        "resource_cost": {"pair_work": 12.0},
        "gross_saved_work": gross_saved_work,
        "learning_cost_work": learning_cost_work,
    }
    return {**body, "receipt_hash": canonical_hash(body)}


def test_unfinalized_or_tampered_receipt_cannot_enter_memory(tmp_path):
    memory = JanusActivatorSlimeMemoryR0(tmp_path / "slime")
    unfinalized = sealed_receipt("research_or_anomaly_investigation", finalized=False)
    with pytest.raises(ValueError, match="SLIME_RECEIPT_NOT_FINALIZED"):
        memory.learn_from_finalized_receipt(unfinalized)

    tampered = sealed_receipt("research_or_anomaly_investigation")
    tampered["gross_saved_work"] = 999.0
    with pytest.raises(ValueError, match="SLIME_RECEIPT_HASH_INVALID"):
        memory.learn_from_finalized_receipt(tampered)
    assert memory.read_episodes() == []


def test_duplicate_verified_receipt_is_not_new_evidence(tmp_path):
    memory = JanusActivatorSlimeMemoryR0(tmp_path / "slime")
    receipt = sealed_receipt("research_or_anomaly_investigation")
    first = memory.learn_from_finalized_receipt(receipt)
    second = memory.learn_from_finalized_receipt(receipt)
    assert first["status"] == "APPENDED_VERIFIED_EPISODE"
    assert second["status"] == "DUPLICATE_IGNORED"
    assert len(memory.read_episodes()) == 1


def test_small_n_is_shrunk_and_no_route_is_dropped(tmp_path):
    memory = JanusActivatorSlimeMemoryR0(tmp_path / "slime")
    memory.learn_from_finalized_receipt(sealed_receipt("A"))
    advice = memory.advise([{"match": "B"}, {"match": "A"}])
    assert {row["match"] for row in advice["routes"]} == {"A", "B"}
    a = next(row for row in advice["ranked_routes"] if row["match"] == "A")
    assert a["stats"]["successes"] == 1
    assert a["verified_route_score"] == 0.2
    assert abs(a["verified_route_score"]) < 0.5


def test_training_cost_can_defeat_gross_success_score(tmp_path):
    memory = JanusActivatorSlimeMemoryR0(tmp_path / "slime")
    memory.learn_from_finalized_receipt(
        sealed_receipt("EXPENSIVE", gross_saved_work=0.0, learning_cost_work=1000.0)
    )
    advice = memory.advise([{"match": "EXPENSIVE"}, {"match": "UNTRAINED"}])
    expensive = next(row for row in advice["ranked_routes"] if row["match"] == "EXPENSIVE")
    assert expensive["stats"]["net_saved_work"] == -1000.0
    assert advice["routes"][0]["match"] == "UNTRAINED"


def test_unknown_is_preserved_but_does_not_promote_route_confidence(tmp_path):
    memory = JanusActivatorSlimeMemoryR0(tmp_path / "slime")
    result = memory.learn_from_finalized_receipt(
        sealed_receipt("A", terminal="VERIFIED_UNKNOWN")
    )
    assert result["promotable_route_confidence_changed"] is False
    advice = memory.advise([{"match": "A"}])
    row = advice["ranked_routes"][0]
    assert row["stats"]["unknown"] == 1
    assert row["verified_route_score"] == 0.0


def test_spider_replay_attention_rises_then_fatigues_without_history_deletion(tmp_path):
    memory = JanusActivatorSlimeMemoryR0(tmp_path / "slime")
    weights = []
    for _ in range(12):
        advice = memory.advise([{"match": "A"}])
        weights.append(advice["ranked_routes"][0]["attention_weight"])
    assert max(weights[:4]) > weights[0]
    assert weights[-1] < max(weights[:4])
    assert memory.read_episodes() == []


def test_slime_aware_activator_only_reorders_declared_routes_and_does_not_learn_on_activate(tmp_path):
    activator = SlimeAwareJanusActivatorR0(state_dir=tmp_path / "activator")
    activator.learn_slime_receipt(
        sealed_receipt(
            "cross_domain_candidate_generation",
            gross_saved_work=100.0,
            learning_cost_work=0.0,
        )
    )
    episode_count_before = len(activator.slime_memory.read_episodes())
    event = ActivationEvent.build(
        source_kind="GITHUB_COMMIT",
        source_ref="repo@slime-r0",
        payload={"sha": "slime-r0"},
        classifications=[
            "research_or_anomaly_investigation",
            "cross_domain_candidate_generation",
        ],
        fresh=True,
    )
    receipt = activator.activate(event)
    matches = [route["match"] for route in receipt["routes_selected"]]
    assert matches[0] == "cross_domain_candidate_generation"
    assert set(matches) == {
        "research_or_anomaly_investigation",
        "cross_domain_candidate_generation",
    }
    assert len(activator.slime_memory.read_episodes()) == episode_count_before
    assert receipt["dispatch_authorized"] is False
    assert receipt["external_effect_authorized"] is False
