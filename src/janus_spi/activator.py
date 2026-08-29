from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ActivationEvent:
    event_id: str
    source_kind: str
    source_ref: str
    payload_sha256: str
    classifications: tuple[str, ...]
    fresh: bool
    self_generated: bool = False
    command_authority: bool = False
    effect_authorized: bool = False

    @classmethod
    def build(
        cls,
        *,
        source_kind: str,
        source_ref: str,
        payload: Any,
        classifications: Iterable[str] = (),
        fresh: bool,
        self_generated: bool = False,
        command_authority: bool = False,
        effect_authorized: bool = False,
    ) -> "ActivationEvent":
        source_kind = str(source_kind).strip().upper()
        source_ref = str(source_ref).strip()
        if not source_kind or not source_ref:
            raise ValueError("ACTIVATION_SOURCE_KIND_AND_REF_REQUIRED")
        digest = canonical_hash(payload)
        event_id = canonical_hash({
            "source_kind": source_kind,
            "source_ref": source_ref,
            "payload_sha256": digest,
        })
        normalized = tuple(dict.fromkeys(str(x).strip() for x in classifications if str(x).strip()))
        return cls(
            event_id=event_id,
            source_kind=source_kind,
            source_ref=source_ref,
            payload_sha256=digest,
            classifications=normalized,
            fresh=bool(fresh),
            self_generated=bool(self_generated),
            command_authority=bool(command_authority),
            effect_authorized=bool(effect_authorized),
        )


class ActivationLedger:
    """Append-only hash chained activation receipt ledger."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("ACTIVATION_LEDGER_ROW_NOT_OBJECT")
                rows.append(obj)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["receipt_hash"]) if rows else None

    def append(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(receipt)
        body.pop("receipt_hash", None)
        body["receipt_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return body

    def verify(self) -> bool:
        previous: Optional[str] = None
        for row in self.read():
            if row.get("parent_activation_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True


class JanusActivator:
    """Bounded HOME root activator.

    v0.2 consumes an already classified fresh stimulus, preserves lineage, and
    proposes routes. It does not execute downstream organs and grants no external
    effect authority. Natural-language classification and downstream execution are
    intentionally separate future gates.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path = "state/activator",
        routing_path: str | Path = ".janus/activator/ROUTING_TABLE.json",
        policy_path: str | Path = "config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json",
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.routing_path = Path(routing_path)
        self.policy_path = Path(policy_path)
        self.routing = json.loads(self.routing_path.read_text(encoding="utf-8"))
        self.policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        self.ledger = ActivationLedger(self.state_dir / "activation_ledger.jsonl")
        self._validate_contracts()

    def _validate_contracts(self) -> None:
        steps = self.policy.get("canonical_step_machine")
        if not isinstance(steps, list) or len(steps) != 17:
            raise ValueError("ACTIVATOR_REQUIRES_CANONICAL_17_STEP_POLICY")
        expected = [
            "INGEST_INTENT", "CLASSIFY_ENVIRONMENT", "LOAD_PROVENANCE_AND_STATE", "OBSERVE_STRUCTURE",
            "GENERATE_BOUNDED_CANDIDATES", "BUILD_MINIMUM_TESTABLE_MODEL", "ROUTE_SPECIALIZED_GATES",
            "FORWARD_CONSTRUCTION_PASS", "REVERSE_ADVERSARIAL_PASS", "EVIDENCE_DIVERSITY_AND_INDEPENDENCE_CHECK",
            "DEMIHEAD_ARBITRATION", "PRESERVE_FAILURE_AND_SHADOWS", "BOUND_THE_CLAIM", "STATE_DELTA_CHECK",
            "PROMOTE_OR_HOLD", "TRANSFER_SURVIVING_PRINCIPLE", "ORIGIN_PRIME",
        ]
        observed = [str(row.get("id")) for row in steps]
        if observed != expected:
            raise ValueError("ACTIVATOR_STEP_POLICY_DRIFT")
        if self.routing.get("default", {}).get("external_effect_authorized") is not False:
            raise ValueError("ACTIVATOR_ROUTING_MUST_DEFAULT_NO_EXTERNAL_EFFECT")

    @staticmethod
    def normalize_epistemic_terminal(raw_status: str) -> str:
        status = str(raw_status or "").strip().upper()
        if status in {"TIMEOUT", "RESOURCE_LIMIT", "BUDGET_EXHAUSTED", "WORKFLOW_TIMEOUT"}:
            return "UNKNOWN_RESOURCE_LIMIT"
        if status in {"TRANSPORT_FAILURE", "TARGET_UNAVAILABLE", "MODEL_UNAVAILABLE", "MISSING_DATA"}:
            return "UNRESOLVED"
        if status in {"NEGATIVE", "REFUTED_WITHIN_SCOPE", "FORMALLY_ADMITTED", "UNRESOLVED", "OPEN"}:
            return status
        return "UNRESOLVED"

    def _select_routes(self, classifications: Iterable[str]) -> list[Dict[str, Any]]:
        wanted = set(classifications)
        selected: list[Dict[str, Any]] = []
        for route in self.routing.get("routes", []):
            if not isinstance(route, dict) or route.get("match") not in wanted:
                continue
            selected.append({
                "match": route["match"],
                "organs": list(route.get("organs", [])),
                "required_gates": list(route.get("required_gates", [])),
                "dispatch_authorized": False,
                "external_effect_authorized": False,
            })
        return selected

    @staticmethod
    def _base_state() -> Dict[str, Any]:
        return {
            "lifecycle": "DORMANT",
            "cognition": "INGEST_INTENT",
            "epistemic": "UNRESOLVED",
            "capability_effect": "NO_CAPABILITY_REQUEST",
            "runtime_health": {
                "source_observation": "UNKNOWN",
                "model_synthesis": "UNKNOWN",
                "target_transport": "UNKNOWN",
                "ledger_integrity": "UNKNOWN",
            },
            "routing": "UNROUTED",
        }

    def activate(self, event: ActivationEvent) -> Dict[str, Any]:
        if not isinstance(event, ActivationEvent):
            raise TypeError("ACTIVATION_EVENT_REQUIRED")

        parent_hash = self.ledger.tip_hash()
        before = self._base_state()
        transitions = ["DORMANT", "WAKING", "ORIENTING", "GOVERNING"]
        routes: list[Dict[str, Any]] = []
        blocked: list[str] = []
        what_failed: list[str] = []
        unknown: list[str] = []
        next_gate = "WAIT_FOR_FRESH_TRIGGER"
        terminal = "HOLD"
        after = self._base_state()
        after["lifecycle"] = "CHECKPOINTING"
        after["runtime_health"]["ledger_integrity"] = "PASS" if self.ledger.verify() else "FAIL"

        if not event.fresh:
            blocked.append("STALE_BASELINE_NOT_FRESH_TRIGGER")
            unknown.append("No new cognitive generation was opened from stale history.")
            after["cognition"] = "INGEST_INTENT"
            after["routing"] = "ROUTE_BLOCKED"
            next_gate = "FRESH_TRIGGER_REQUIRED"
        elif event.self_generated:
            blocked.append("SELF_OUTPUT_NOT_FRESH_TRIGGER")
            unknown.append("Self-generated output cannot recursively awaken a new generation.")
            after["cognition"] = "INGEST_INTENT"
            after["routing"] = "ROUTE_BLOCKED"
            next_gate = "FRESH_NON_SELF_TRIGGER_REQUIRED"
        else:
            transitions.append("ROUTING")
            routes = self._select_routes(event.classifications)
            after["runtime_health"]["source_observation"] = "OK"
            after["runtime_health"]["target_transport"] = "UNKNOWN"
            after["epistemic"] = "OBSERVATION_BOUND"
            after["cognition"] = "ROUTE_SPECIALIZED_GATES"
            if routes:
                terminal = "ROUTE_PROPOSED"
                after["routing"] = "ROUTE_PROPOSED"
                next_gate = "RUN_SELECTED_SPECIALIZED_GATES_WITH_SEPARATE_AUTHORITY"
            else:
                blocked.append("NO_MATCHING_ROUTE")
                unknown.append("Stimulus is fresh but no declared classification matched the routing table.")
                after["routing"] = "ROUTE_BLOCKED"
                next_gate = "CLASSIFY_ENVIRONMENT_OR_EXTEND_ROUTING_TABLE"

        if event.effect_authorized:
            # v0.2 never consumes external effect authority. That belongs to the
            # Terminal/Third-Wish capability boundary and must be independently bound.
            blocked.append("EVENT_EFFECT_FLAG_NOT_CONSUMED_AS_AUTHORITY")
        if event.command_authority:
            blocked.append("EVENT_COMMAND_FLAG_NOT_CONSUMED_AS_AUTHORITY")

        transitions.extend(["CHECKPOINTING", "SLEEPING", "DORMANT"])
        after["lifecycle"] = "DORMANT"
        receipt = {
            "schema": "janus.activator.receipt.v0.2",
            "activation_id": f"act-{uuid.uuid4().hex}",
            "created_at": time.time(),
            "parent_activation_hash": parent_hash,
            "event": asdict(event),
            "state_vector_before": before,
            "state_vector_after": after,
            "lifecycle_trace": transitions,
            "routes_selected": routes,
            "routes_blocked": blocked,
            "epistemic_terminal": after["epistemic"],
            "effect_terminal": "NO_EXTERNAL_EFFECT",
            "health_terminal": after["runtime_health"],
            "terminal": terminal,
            "dispatch_authorized": False,
            "external_effect_authorized": False,
            "what_changed": ["Activation stimulus classified and checkpointed."],
            "what_failed": what_failed,
            "what_remains_unknown": unknown,
            "next_gate": next_gate,
            "policy_sha256": canonical_hash(self.policy),
            "routing_sha256": canonical_hash(self.routing),
        }
        sealed = self.ledger.append(receipt)
        if not self.ledger.verify():
            raise RuntimeError("ACTIVATION_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return sealed


__all__ = ["ActivationEvent", "ActivationLedger", "JanusActivator", "canonical_hash"]
