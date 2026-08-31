from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping

from .slime_memory import JanusActivatorSlimeMemoryR0, RECEIPT_CLASS


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _gold_choice(case: Mapping[str, Any]) -> Dict[str, Any]:
    ranked = []
    for index, route in enumerate(case["candidates"]):
        rows = case["training"][route]
        successes = sum(row["terminal"] == "VERIFIED_SUCCESS" for row in rows)
        losses = sum(
            row["terminal"] in {"VERIFIED_FAILURE", "VERIFIED_RESOURCE_LIMIT"}
            for row in rows
        )
        scored_bouts = successes + losses
        win_rate = successes / scored_bouts if scored_bouts else 0.5
        ranked.append(
            {
                "route": route,
                "win_rate": win_rate,
                "scored_bouts": scored_bouts,
                "declared_index": index,
            }
        )
    ranked.sort(key=lambda row: (-row["win_rate"], -row["scored_bouts"], row["declared_index"]))
    return {"choice": ranked[0]["route"], "ranking": ranked}


def _seal_training_receipt(case_id: str, route: str, index: int, row: Mapping[str, Any]) -> Dict[str, Any]:
    body = {
        "receipt_class": RECEIPT_CLASS,
        "finalized": True,
        "route_match": route,
        "route_terminal": row["terminal"],
        "source_digest": hashlib.sha256(f"{case_id}|{route}|{index}".encode("utf-8")).hexdigest(),
        "verifier_digest": hashlib.sha256(b"JANUS_SLIME_GOLD_VS_IDEAL_FROZEN_BENCH_V1").hexdigest(),
        "resource_cost": {
            "synthetic_work": float(row["gross_saved_work"]) + float(row["learning_cost_work"])
        },
        "gross_saved_work": float(row["gross_saved_work"]),
        "learning_cost_work": float(row["learning_cost_work"]),
    }
    return {**body, "receipt_hash": canonical_hash(body)}


def _ideal_choice(case: Mapping[str, Any]) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="janus-slime-bench-") as tmp:
        memory = JanusActivatorSlimeMemoryR0(Path(tmp) / "memory")
        for route in case["candidates"]:
            for index, row in enumerate(case["training"][route]):
                memory.learn_from_finalized_receipt(
                    _seal_training_receipt(str(case["id"]), str(route), index, row)
                )
        declared = [{"match": route} for route in case["candidates"]]
        advice = memory.advise(declared, context={"frozen_case": case["id"]})
        return {
            "choice": advice["routes"][0]["match"],
            "ranking": advice["ranked_routes"],
            "authority": advice["authority"],
            "episode_count": advice["episode_count"],
        }


def _evaluate_choice(case: Mapping[str, Any], route: str, utility: Mapping[str, float]) -> Dict[str, Any]:
    if route not in case["candidates"]:
        raise ValueError("BENCHMARK_CHOICE_OUTSIDE_DECLARED_CANDIDATES")
    holdout = case["holdout"][route]
    terminal = str(holdout["terminal"])
    execution_cost = float(holdout["execution_cost_work"])
    return {
        "route": route,
        "terminal": terminal,
        "terminal_utility": float(utility[terminal]),
        "execution_cost_work": execution_cost,
        "pre_training_composite": float(utility[terminal]) - execution_cost / 1000.0,
    }


def run_frozen_benchmark(spec_path: str | Path) -> Dict[str, Any]:
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("benchmark"), dict):
        raise ValueError("SLIME_BENCHMARK_SPEC_OBJECT_REQUIRED")
    core = spec["benchmark"]
    observed_core_sha = canonical_hash(core)
    expected_core_sha = str(spec.get("benchmark_core_sha256") or "")
    if observed_core_sha != expected_core_sha:
        raise ValueError("SLIME_BENCHMARK_FROZEN_CORE_HASH_MISMATCH")
    if spec.get("winner_preregistered") is not False:
        raise ValueError("SLIME_BENCHMARK_WINNER_MUST_NOT_BE_PREREGISTERED")
    if core.get("holdout_learned_before_selection") is not False:
        raise ValueError("SLIME_BENCHMARK_HOLDOUT_LEAKAGE_FORBIDDEN")

    utility = {str(k): float(v) for k, v in core["terminal_utility"].items()}
    per_case = []
    shared_observed_learning_cost = 0.0
    training_episode_count = 0
    authority_escalations = 0

    aggregate = {
        "gold": {"terminal_utility": 0.0, "execution_cost_work": 0.0, "terminal_counts": {}},
        "ideal": {"terminal_utility": 0.0, "execution_cost_work": 0.0, "terminal_counts": {}},
    }

    for case in core["scenarios"]:
        for route in case["candidates"]:
            for row in case["training"][route]:
                training_episode_count += 1
                shared_observed_learning_cost += float(row["learning_cost_work"])

        gold = _gold_choice(case)
        ideal = _ideal_choice(case)
        if any(bool(value) for value in ideal["authority"].values()):
            authority_escalations += 1

        gold_eval = _evaluate_choice(case, gold["choice"], utility)
        ideal_eval = _evaluate_choice(case, ideal["choice"], utility)
        for name, evaluation in (("gold", gold_eval), ("ideal", ideal_eval)):
            aggregate[name]["terminal_utility"] += evaluation["terminal_utility"]
            aggregate[name]["execution_cost_work"] += evaluation["execution_cost_work"]
            terminal = evaluation["terminal"]
            counts = aggregate[name]["terminal_counts"]
            counts[terminal] = int(counts.get(terminal, 0)) + 1

        per_case.append(
            {
                "id": case["id"],
                "purpose": case["purpose"],
                "gold": {**gold, "holdout": gold_eval},
                "ideal": {**ideal, "holdout": ideal_eval},
                "same_choice": gold["choice"] == ideal["choice"],
            }
        )

    accounting = core["training_cost_accounting"]
    gold_training_cost = shared_observed_learning_cost + training_episode_count * float(
        accounting["gold_algorithm_overhead_per_training_episode"]
    )
    ideal_training_cost = shared_observed_learning_cost + training_episode_count * float(
        accounting["ideal_algorithm_overhead_per_training_episode"]
    )
    for name, train_cost in (("gold", gold_training_cost), ("ideal", ideal_training_cost)):
        aggregate[name]["training_cost_work"] = train_cost
        aggregate[name]["pre_training_composite"] = (
            aggregate[name]["terminal_utility"] - aggregate[name]["execution_cost_work"] / 1000.0
        )
        aggregate[name]["net_composite"] = aggregate[name]["pre_training_composite"] - train_cost / 1000.0

    def count(name: str, terminal: str) -> int:
        return int(aggregate[name]["terminal_counts"].get(terminal, 0))

    gates = core["gates"]
    gate_results = {
        "composite_net_margin": (
            aggregate["ideal"]["net_composite"] - aggregate["gold"]["net_composite"]
        ) >= float(gates["composite_net_margin_min"]),
        "successes": (not gates["ideal_successes_gte_gold"]) or count("ideal", "VERIFIED_SUCCESS") >= count("gold", "VERIFIED_SUCCESS"),
        "failures": (not gates["ideal_failures_lte_gold"]) or count("ideal", "VERIFIED_FAILURE") <= count("gold", "VERIFIED_FAILURE"),
        "unknowns": (not gates["ideal_unknowns_lte_gold"]) or count("ideal", "VERIFIED_UNKNOWN") <= count("gold", "VERIFIED_UNKNOWN"),
        "execution_cost": (not gates["ideal_holdout_execution_cost_lte_gold"]) or aggregate["ideal"]["execution_cost_work"] <= aggregate["gold"]["execution_cost_work"],
        "declared_candidate_set": all(
            row["gold"]["choice"] in next(case["candidates"] for case in core["scenarios"] if case["id"] == row["id"])
            and row["ideal"]["choice"] in next(case["candidates"] for case in core["scenarios"] if case["id"] == row["id"])
            for row in per_case
        ),
        "authority": authority_escalations <= int(gates["authority_escalations_allowed"]),
    }
    status = "PASS" if all(gate_results.values()) else "FAIL"
    return {
        "schema": "janus.activator.slime_gold_vs_ideal_benchmark.result.v1",
        "status": status,
        "benchmark_id": core["benchmark_id"],
        "frozen_core_sha256": observed_core_sha,
        "gold_baseline": core["gold_baseline"],
        "ideal_candidate": core["ideal_candidate"],
        "training_episode_count": training_episode_count,
        "shared_observed_learning_cost_work": shared_observed_learning_cost,
        "authority_escalations": authority_escalations,
        "per_case": per_case,
        "aggregate": aggregate,
        "net_composite_margin_ideal_minus_gold": aggregate["ideal"]["net_composite"] - aggregate["gold"]["net_composite"],
        "gate_results": gate_results,
        "claim": (
            "BETTER_THAN_GOLDEN_ARENA_BASELINE_WITHIN_FROZEN_ACTIVATOR_ROUTE_MEMORY_BENCH"
            if status == "PASS"
            else "NO_SCOPED_SUPERIORITY_ESTABLISHED"
        ),
        "claim_boundary": spec["claim_boundary"],
    }


__all__ = ["run_frozen_benchmark"]
