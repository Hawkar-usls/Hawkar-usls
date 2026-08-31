from pathlib import Path

from janus_spi.slime_gold_benchmark import run_frozen_benchmark


SPEC = Path(".janus/activator/SLIME_GOLD_VS_IDEAL_FROZEN_BENCH_V1.json")
FROZEN_CORE_SHA256 = "27455db8612cbd6e82eb3a364cce65f6985de5a72c0feaa7f9d6e579f3bebef1"


def test_frozen_gold_vs_ideal_benchmark_passes_all_preregistered_gates():
    result = run_frozen_benchmark(SPEC)
    assert result["frozen_core_sha256"] == FROZEN_CORE_SHA256
    assert result["status"] == "PASS"
    assert all(result["gate_results"].values())
    assert result["claim"] == "BETTER_THAN_GOLDEN_ARENA_BASELINE_WITHIN_FROZEN_ACTIVATOR_ROUTE_MEMORY_BENCH"


def test_controls_are_not_forced_to_disagree_and_ideal_does_not_escalate_authority():
    result = run_frozen_benchmark(SPEC)
    rows = {row["id"]: row for row in result["per_case"]}
    assert rows["STABLE_CHAMPION_CONTROL"]["same_choice"] is True
    assert rows["ROBUST_AGREEMENT_CONTROL"]["same_choice"] is True
    assert result["authority_escalations"] == 0


def test_scoped_winner_is_better_after_training_cost_is_charged():
    result = run_frozen_benchmark(SPEC)
    gold = result["aggregate"]["gold"]
    ideal = result["aggregate"]["ideal"]
    assert ideal["training_cost_work"] > gold["training_cost_work"]
    assert ideal["net_composite"] > gold["net_composite"]
    assert result["net_composite_margin_ideal_minus_gold"] >= 1.0
