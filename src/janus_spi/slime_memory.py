from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


RECEIPT_CLASS = "JANUS_SLIME_VERIFIED_ROUTE_OUTCOME"
ALLOWED_ROUTE_TERMINALS = {
    "VERIFIED_SUCCESS",
    "VERIFIED_FAILURE",
    "VERIFIED_RESOURCE_LIMIT",
    "VERIFIED_UNKNOWN",
}


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower())


def _finite_nonnegative(value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("SLIME_RESOURCE_COST_MUST_BE_FINITE_NONNEGATIVE")
    return number


def _repetition_shape(replay_streak: int) -> tuple[float, float, float]:
    """Canonical TOPA attention shape: early salience, then replay fatigue."""
    r = max(0, int(replay_streak))
    burst = 0.18 * (1.0 - math.exp(-0.9 * min(r, 6)))
    fatigue = 0.58 * (1.0 - math.exp(-0.45 * max(0, r - 3)))
    return burst, fatigue, burst - fatigue


class JanusActivatorSlimeMemoryR0:
    """Receipt-bound advisory route memory for the JANUS Activator.

    R0 can retrieve and reorder declared candidate routes. It cannot create a
    route, fresh trigger, claim verdict, authorization, dispatch, or external
    effect. Promotable route confidence is updated only from finalized,
    integrity-valid downstream route-outcome receipts.
    """

    schema = "janus.activator.slime_memory.r0"

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_path = self.state_dir / "verified_route_episodes.jsonl"
        self.attention_path = self.state_dir / "attention_state.json"

    def read_episodes(self) -> list[Dict[str, Any]]:
        if not self.episodes_path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.episodes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("SLIME_EPISODE_ROW_NOT_OBJECT")
            rows.append(row)
        return rows

    def _read_attention(self) -> Dict[str, Dict[str, Any]]:
        if not self.attention_path.exists():
            return {}
        obj = json.loads(self.attention_path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("SLIME_ATTENTION_STATE_NOT_OBJECT")
        return {str(k): dict(v) for k, v in obj.items() if isinstance(v, dict)}

    def _write_attention(self, state: Mapping[str, Mapping[str, Any]]) -> None:
        tmp = self.attention_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.attention_path)

    @staticmethod
    def _validate_finalized_receipt(receipt: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(receipt, Mapping):
            raise TypeError("SLIME_FINALIZED_RECEIPT_OBJECT_REQUIRED")
        body = dict(receipt)
        claimed_hash = str(body.pop("receipt_hash", "")).lower()
        required = {
            "receipt_class",
            "finalized",
            "route_match",
            "route_terminal",
            "source_digest",
            "verifier_digest",
            "resource_cost",
            "gross_saved_work",
            "learning_cost_work",
        }
        missing = sorted(name for name in required if name not in body)
        if missing:
            raise ValueError("SLIME_FINALIZED_RECEIPT_MISSING_FIELDS:" + ",".join(missing))
        if body["receipt_class"] != RECEIPT_CLASS:
            raise ValueError("SLIME_RECEIPT_CLASS_REJECTED")
        if body["finalized"] is not True:
            raise ValueError("SLIME_RECEIPT_NOT_FINALIZED")
        route_match = str(body["route_match"]).strip()
        if not route_match:
            raise ValueError("SLIME_ROUTE_MATCH_REQUIRED")
        terminal = str(body["route_terminal"]).strip().upper()
        if terminal not in ALLOWED_ROUTE_TERMINALS:
            raise ValueError("SLIME_ROUTE_TERMINAL_REJECTED")
        source_digest = str(body["source_digest"]).lower()
        verifier_digest = str(body["verifier_digest"]).lower()
        if not _is_sha256(source_digest) or not _is_sha256(verifier_digest):
            raise ValueError("SLIME_SOURCE_AND_VERIFIER_SHA256_REQUIRED")
        resource_cost = body["resource_cost"]
        if not isinstance(resource_cost, Mapping):
            raise ValueError("SLIME_RESOURCE_COST_OBJECT_REQUIRED")
        normalized_cost = {str(k): _finite_nonnegative(v) for k, v in resource_cost.items()}
        gross_saved_work = _finite_nonnegative(body["gross_saved_work"])
        learning_cost_work = _finite_nonnegative(body["learning_cost_work"])
        if not _is_sha256(claimed_hash):
            raise ValueError("SLIME_RECEIPT_HASH_REQUIRED")
        if _canonical_hash(body) != claimed_hash:
            raise ValueError("SLIME_RECEIPT_HASH_INVALID")
        body["route_match"] = route_match
        body["route_terminal"] = terminal
        body["source_digest"] = source_digest
        body["verifier_digest"] = verifier_digest
        body["resource_cost"] = normalized_cost
        body["gross_saved_work"] = gross_saved_work
        body["learning_cost_work"] = learning_cost_work
        body["receipt_hash"] = claimed_hash
        return body

    def learn_from_finalized_receipt(self, receipt: Mapping[str, Any]) -> Dict[str, Any]:
        episode = self._validate_finalized_receipt(receipt)
        existing = {str(row.get("receipt_hash")) for row in self.read_episodes()}
        if episode["receipt_hash"] in existing:
            return {
                "schema": self.schema + ".learn",
                "status": "DUPLICATE_IGNORED",
                "receipt_hash": episode["receipt_hash"],
                "promotable_route_confidence_changed": False,
            }
        with self.episodes_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(episode, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return {
            "schema": self.schema + ".learn",
            "status": "APPENDED_VERIFIED_EPISODE",
            "receipt_hash": episode["receipt_hash"],
            "route_match": episode["route_match"],
            "route_terminal": episode["route_terminal"],
            "promotable_route_confidence_changed": episode["route_terminal"] != "VERIFIED_UNKNOWN",
        }

    @staticmethod
    def _route_stats(route_match: str, episodes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        rows = [row for row in episodes if str(row.get("route_match")) == route_match]
        success = sum(row.get("route_terminal") == "VERIFIED_SUCCESS" for row in rows)
        failure = sum(row.get("route_terminal") == "VERIFIED_FAILURE" for row in rows)
        resource_limit = sum(row.get("route_terminal") == "VERIFIED_RESOURCE_LIMIT" for row in rows)
        unknown = sum(row.get("route_terminal") == "VERIFIED_UNKNOWN" for row in rows)
        directional_n = success + failure + resource_limit
        utility_sum = float(success) - float(failure) - 0.35 * float(resource_limit)

        # Four neutral pseudo-observations shrink tiny samples toward no preference.
        shrunk_utility = utility_sum / float(directional_n + 4)

        gross = sum(float(row.get("gross_saved_work") or 0.0) for row in rows)
        learning = sum(float(row.get("learning_cost_work") or 0.0) for row in rows)
        net = gross - learning
        scale = abs(gross) + abs(learning) + 1.0
        cost_efficiency = math.tanh(net / scale)

        contradiction_pairs = min(success, failure)
        contradiction_urgency = min(0.16, 0.05 * contradiction_pairs)
        exploration_bonus = 0.12 / math.sqrt(len(rows) + 1.0)

        return {
            "episodes": len(rows),
            "successes": success,
            "failures": failure,
            "resource_limits": resource_limit,
            "unknown": unknown,
            "shrunk_utility": round(shrunk_utility, 6),
            "gross_saved_work": gross,
            "learning_cost_work": learning,
            "net_saved_work": net,
            "cost_efficiency": round(cost_efficiency, 6),
            "contradiction_urgency": round(contradiction_urgency, 6),
            "exploration_bonus": round(exploration_bonus, 6),
        }

    def advise(
        self,
        candidate_routes: Iterable[Mapping[str, Any]],
        *,
        context: Mapping[str, Any] | None = None,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        routes = [dict(route) for route in candidate_routes]
        episodes = self.read_episodes()
        previous_attention = self._read_attention()
        next_attention = dict(previous_attention)
        scored: list[tuple[float, int, Dict[str, Any], Dict[str, Any]]] = []

        for index, route in enumerate(routes):
            match = str(route.get("match") or "")
            stats = self._route_stats(match, episodes)
            prev = dict(previous_attention.get(match) or {})
            prior_episode_count = int(prev.get("episode_count_at_last_advice") or 0)
            fresh_verified_episode = stats["episodes"] > prior_episode_count
            prior_streak = int(prev.get("replay_streak") or 0)
            replay_streak = 0 if fresh_verified_episode else prior_streak + 1
            burst, fatigue, repetition_net = _repetition_shape(replay_streak)

            base_attention = 0.30
            novelty_bonus = 0.14 if fresh_verified_episode else 0.0
            target_attention = max(
                0.0,
                min(
                    0.99,
                    base_attention
                    + novelty_bonus
                    + repetition_net
                    + float(stats["contradiction_urgency"]),
                ),
            )
            old_attention = float(prev.get("attention_weight", base_attention))
            alpha = 0.72 if fresh_verified_episode else 0.50
            attention_weight = max(
                0.0,
                min(0.99, old_attention + alpha * (target_attention - old_attention)),
            )
            next_attention[match] = {
                "attention_weight": round(attention_weight, 6),
                "replay_streak": replay_streak,
                "episode_count_at_last_advice": stats["episodes"],
            }

            # Route utility and resource accounting dominate. Attention is bounded
            # discovery priority; exploration prevents tiny-n adviser monoculture.
            rank_score = (
                0.55 * float(stats["shrunk_utility"])
                + 0.20 * float(stats["cost_efficiency"])
                + 0.15 * (attention_weight - 0.30)
                + float(stats["exploration_bonus"])
            )
            detail = {
                "match": match,
                "rank_score": round(rank_score, 6),
                "verified_route_score": stats["shrunk_utility"],
                "resource_efficiency_score": stats["cost_efficiency"],
                "attention_weight": round(attention_weight, 6),
                "attention_is_evidence": False,
                "fresh_verified_episode_since_last_advice": fresh_verified_episode,
                "replay_streak": replay_streak,
                "repetition_burst": round(burst, 6),
                "replay_fatigue": round(fatigue, 6),
                "stats": stats,
            }
            scored.append((rank_score, index, route, detail))

        self._write_attention(next_attention)
        scored.sort(key=lambda row: (-row[0], row[1]))
        reordered_routes = [row[2] for row in scored]
        ranked_details = [row[3] for row in scored]
        top_matches = [row["match"] for row in ranked_details[: max(0, int(top_k))]]
        return {
            "schema": self.schema + ".advice",
            "role": "ADVISORY_PERSISTENT_ADAPTATION_AND_ROUTE_MEMORY",
            "authority": {
                "root_activation_authority": False,
                "claim_verdict_authority": False,
                "authorization_authority": False,
                "dispatch_authority": False,
                "effect_authority": False,
                "can_create_fresh_trigger": False,
            },
            "context_digest": _canonical_hash(dict(context or {})),
            "routes": reordered_routes,
            "ranked_routes": ranked_details,
            "top_k_routes": top_matches,
            "episode_count": len(episodes),
            "laws": [
                "SLIME_MAY_REORDER_DECLARED_ROUTES_BUT_MAY_NOT_CREATE_AUTHORITY",
                "ONLY_FINALIZED_INTEGRITY_VALID_ROUTE_RECEIPTS_UPDATE_CONFIDENCE",
                "UNKNOWN_IS_PRESERVED_AND_DIRECTIONALLY_NEUTRAL",
                "SMALL_N_IS_SHRUNK_TOWARD_NEUTRAL",
                "ATTENTION_IS_NOT_EVIDENCE",
                "REPLAY_FATIGUE_DOES_NOT_DELETE_HISTORY",
                "TRAINING_COST_COUNTS_AGAINST_GROSS_SAVINGS",
                "NO_ROUTE_IS_DROPPED_BY_R0",
            ],
        }


__all__ = [
    "ALLOWED_ROUTE_TERMINALS",
    "JanusActivatorSlimeMemoryR0",
    "RECEIPT_CLASS",
]
