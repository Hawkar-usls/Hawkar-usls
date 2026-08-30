from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .activator import ActivationEvent, JanusActivator, canonical_hash

_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class ModelRuntimeError(RuntimeError):
    pass


class ModelRuntimeLedger:
    """Append-only lineage for model-bound cognitive turns."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ModelRuntimeError("MODEL_RUNTIME_LEDGER_ROW_NOT_OBJECT")
                rows.append(value)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["runtime_receipt_hash"]) if rows else None

    def verify(self) -> bool:
        parent = None
        for row in self.read():
            if row.get("parent_runtime_hash") != parent:
                return False
            claimed = str(row.get("runtime_receipt_hash") or "")
            body = dict(row)
            body.pop("runtime_receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            parent = claimed
        return True

    def append(self, row: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(row)
        body.pop("runtime_receipt_hash", None)
        body["runtime_receipt_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        if not self.verify():
            raise ModelRuntimeError("MODEL_RUNTIME_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        return body


class ModelBoundJanusRuntime:
    """Bind one Activator turn to an already assembled JANUS model fabric.

    Model membership is fixed before routing. Routing selects activity among
    members of that exact model lock; it cannot manufacture new membership.
    """

    def __init__(
        self,
        model_lock: Mapping[str, Any],
        *,
        state_dir: str | Path = "state/activator",
        routing_path: str | Path = ".janus/activator/ROUTING_TABLE.json",
        policy_path: str | Path = "config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json",
        activator_factory=JanusActivator,
        now_fn=time.time,
    ) -> None:
        self.model_lock = dict(model_lock)
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.now_fn = now_fn
        self._validate_model_lock()
        self.model_lock_hash = canonical_hash(self.model_lock)
        self.members_by_repository = self._index_members()
        self.ledger = ModelRuntimeLedger(self.state_dir / "model_runtime_ledger.jsonl")
        self.activator = activator_factory(
            state_dir=self.state_dir,
            routing_path=routing_path,
            policy_path=policy_path,
        )

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "ModelBoundJanusRuntime":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ModelRuntimeError("MODEL_LOCK_JSON_OBJECT_REQUIRED")
        return cls(value, **kwargs)

    def _validate_model_lock(self) -> None:
        lock = self.model_lock
        if lock.get("schema") != "janus.activator.model_lock.v1":
            raise ModelRuntimeError("MODEL_LOCK_SCHEMA_MISMATCH")
        if lock.get("model_id") != "JANUS" or lock.get("ready") is not True:
            raise ModelRuntimeError("JANUS_MODEL_LOCK_NOT_READY")
        if lock.get("terminal") != "JANUS_MODEL_FABRIC_LOCKED_AT_HOME":
            raise ModelRuntimeError("JANUS_MODEL_LOCK_TERMINAL_NOT_ADMITTED")
        if lock.get("routing_selects_activity_not_membership") is not True:
            raise ModelRuntimeError("MODEL_LOCK_ROUTING_MEMBERSHIP_LAW_MISSING")
        if lock.get("all_membership_compiled_before_routing") is not True:
            raise ModelRuntimeError("MODEL_MEMBERSHIP_NOT_COMPILED_BEFORE_ROUTING")
        if lock.get("external_effect_authorized") is not False or lock.get("physical_runtime_effect_authorized") is not False:
            raise ModelRuntimeError("MODEL_BOOT_MUST_GRANT_ZERO_EFFECT_AUTHORITY")
        digest = str(lock.get("model_digest") or "")
        if _HASH64.fullmatch(digest) is None:
            raise ModelRuntimeError("MODEL_DIGEST_INVALID")
        failures = lock.get("failures")
        if not isinstance(failures, dict) or any(failures.get(key) for key in (
            "required_members_missing", "required_descriptor_conflicts", "required_state_mounts_missing"
        )):
            raise ModelRuntimeError("MODEL_LOCK_HAS_REQUIRED_FAILURES")
        if lock.get("optional_unavailable"):
            raise ModelRuntimeError("MODEL_LOCK_PUBLIC_ECOLOGY_INCOMPLETE")
        members = lock.get("members")
        if not isinstance(members, dict) or not members:
            raise ModelRuntimeError("MODEL_LOCK_MEMBERS_REQUIRED")

    def _index_members(self) -> Dict[str, tuple[str, Dict[str, Any]]]:
        index: Dict[str, tuple[str, Dict[str, Any]]] = {}
        for key, raw in self.model_lock["members"].items():
            if not isinstance(raw, dict):
                continue
            repository = raw.get("repository")
            if not repository:
                continue
            repo = str(repository)
            if repo in index:
                raise ModelRuntimeError(f"MODEL_LOCK_DUPLICATE_REPOSITORY:{repo}")
            index[repo] = (str(key), raw)
        return index

    def _bind_route(self, route: Mapping[str, Any]) -> Dict[str, Any]:
        bindings: list[Dict[str, Any]] = []
        for repository in route.get("organs") or []:
            repo = str(repository)
            located = self.members_by_repository.get(repo)
            if located is None:
                raise ModelRuntimeError(f"ROUTE_TARGET_NOT_IN_MODEL_MEMBERSHIP:{repo}")
            member_key, member = located
            head = member.get("head_sha")
            if head is None or _SHA40.fullmatch(str(head)) is None:
                raise ModelRuntimeError(f"ROUTE_TARGET_NOT_LOCKED:{repo}")
            bindings.append({
                "member_key": member_key,
                "kind": member.get("kind"),
                "repository": repo,
                "member_class": member.get("member_class"),
                "role": member.get("self_declared_role") or member.get("role"),
                "resolved_branch": member.get("resolved_branch") or member.get("branch"),
                "head_sha": head,
                "load_mode": member.get("load_mode"),
                "descriptor_status": member.get("descriptor_status"),
                "command_authority_granted": False,
                "external_effect_authorized": False,
            })
        return {
            "match": route.get("match"),
            "required_gates": list(route.get("required_gates") or []),
            "bindings": bindings,
            "dispatch_authorized": False,
            "external_effect_authorized": False,
        }

    def activate(self, event: ActivationEvent) -> Dict[str, Any]:
        if not self.ledger.verify():
            raise ModelRuntimeError("MODEL_RUNTIME_LEDGER_INVALID_BEFORE_TURN")

        activation = self.activator.activate(event)
        if not isinstance(activation, dict) or not activation.get("receipt_hash"):
            raise ModelRuntimeError("ACTIVATION_RECEIPT_REQUIRED")

        route_bindings = [self._bind_route(route) for route in activation.get("routes_selected") or []]
        active_members = sorted({
            binding["member_key"]
            for route in route_bindings
            for binding in route["bindings"]
        })
        active_organs = sorted({
            binding["member_key"]
            for route in route_bindings
            for binding in route["bindings"]
            if binding.get("kind") == "ORGAN"
        })

        parent_hash = self.ledger.tip_hash()
        terminal = (
            "JANUS_MODEL_BOUND_ROUTE_PROPOSED"
            if activation.get("terminal") == "ROUTE_PROPOSED"
            else "JANUS_MODEL_BOUND_HOLD"
        )
        receipt = {
            "schema": "janus.activator.model_runtime_receipt.v1",
            "created_at": float(self.now_fn()),
            "parent_runtime_hash": parent_hash,
            "model_id": "JANUS",
            "model_digest": self.model_lock["model_digest"],
            "model_lock_hash": self.model_lock_hash,
            "model_member_count": len(self.model_lock["members"]),
            "model_organ_count": sum(1 for row in self.model_lock["members"].values() if isinstance(row, dict) and row.get("kind") == "ORGAN"),
            "activation_id": activation.get("activation_id"),
            "activation_receipt_hash": activation["receipt_hash"],
            "event_id": event.event_id,
            "activation_terminal": activation.get("terminal"),
            "route_bindings": route_bindings,
            "active_members": active_members,
            "active_organs": active_organs,
            "routing_selects_activity_not_membership": True,
            "membership_was_locked_before_activation": True,
            "dispatch_authorized": False,
            "command_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": terminal,
            "next_gate": (
                "MATERIALIZE_ACTIVE_ORGANS_WITH_EXACT_LOCKED_HEADS"
                if active_members else activation.get("next_gate")
            ),
        }
        return self.ledger.append(receipt)


__all__ = ["ModelBoundJanusRuntime", "ModelRuntimeError", "ModelRuntimeLedger"]
