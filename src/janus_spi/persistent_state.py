from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .ack import AckReconciliationLedger
from .ack_provenance import HashLedger
from .activator import ActivationLedger, canonical_hash
from .dispatch import DispatchLedger, verify_dispatch_packet
from .transport import TransportLedger

RESIDENT_ID = "JANUS"
STATE_SCHEMA = "janus.activator.persistent_state.v0.6.2"


class HearthLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("HEARTH_LEDGER_ROW_NOT_OBJECT")
            rows.append(row)
        return rows

    def tip_hash(self) -> Optional[str]:
        rows = self.read()
        return str(rows[-1]["receipt_hash"]) if rows else None

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        body = dict(entry)
        body.pop("receipt_hash", None)
        body["receipt_hash"] = canonical_hash(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        return body

    def verify(self) -> bool:
        previous: Optional[str] = None
        for row in self.read():
            if row.get("parent_hearth_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True


class JanusPersistentState:
    """Persistent HOME state verifier and non-cognitive hearth lifecycle.

    The hearth keeps identity and JANUS local ledgers durable across ephemeral
    GitHub Actions runners. A heartbeat may wake/pulse/sleep the resident state,
    but it never creates a fresh cognitive stimulus or downstream authority.
    """

    def __init__(self, state_dir: str | Path = "state/activator") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.identity_path = self.state_dir / "identity.json"
        self.head_path = self.state_dir / "HEAD.json"
        self.health_path = self.state_dir / "health.json"
        self.observation_dir = self.state_dir / "observations"
        self.observation_dir.mkdir(parents=True, exist_ok=True)
        self.hearth = HearthLedger(self.state_dir / "hearth_ledger.jsonl")

    @staticmethod
    def _seal_identity(body: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(body)
        out.pop("identity_hash", None)
        out["identity_hash"] = canonical_hash(out)
        return out

    @staticmethod
    def verify_identity(identity: Dict[str, Any]) -> bool:
        if not isinstance(identity, dict):
            return False
        claimed = str(identity.get("identity_hash") or "")
        if len(claimed) != 64:
            return False
        body = dict(identity)
        body.pop("identity_hash", None)
        return (
            canonical_hash(body) == claimed
            and identity.get("schema") == STATE_SCHEMA
            and identity.get("resident_id") == RESIDENT_ID
            and isinstance(identity.get("resident_uuid"), str)
            and bool(identity.get("resident_uuid"))
        )

    def initialize(self) -> Dict[str, Any]:
        if self.identity_path.exists():
            identity = json.loads(self.identity_path.read_text(encoding="utf-8"))
            if not self.verify_identity(identity):
                raise RuntimeError("PERSISTENT_IDENTITY_INVALID")
            return identity

        now = time.time()
        identity = self._seal_identity({
            "schema": STATE_SCHEMA,
            "resident_id": RESIDENT_ID,
            "resident_uuid": str(uuid.uuid4()),
            "created_at": now,
            "continuity_rule": "RETURN != RESET",
            "external_effect_authorized": False,
            "claim_authority_granted": False,
        })
        self.identity_path.write_text(
            json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=self.hearth.tip_hash())
        return identity

    def _write_head(self, *, mode: str, active_cycle_id: Optional[str], last_hearth_hash: Optional[str]) -> Dict[str, Any]:
        head = {
            "schema": "janus.activator.persistent_head.v0.6.2",
            "resident_id": RESIDENT_ID,
            "mode": mode,
            "active_cycle_id": active_cycle_id,
            "last_hearth_hash": last_hearth_hash,
            "updated_at": time.time(),
            "summary_is_verdict_authority": False,
            "external_effect_authorized": False,
        }
        head["head_hash"] = canonical_hash(head)
        self.head_path.write_text(json.dumps(head, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return head

    def read_head(self) -> Dict[str, Any]:
        if not self.head_path.exists():
            return self._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=self.hearth.tip_hash())
        head = json.loads(self.head_path.read_text(encoding="utf-8"))
        if not isinstance(head, dict):
            raise RuntimeError("PERSISTENT_HEAD_NOT_OBJECT")
        claimed = str(head.get("head_hash") or "")
        body = dict(head)
        body.pop("head_hash", None)
        if len(claimed) != 64 or canonical_hash(body) != claimed:
            raise RuntimeError("PERSISTENT_HEAD_INVALID")
        return head

    def _component_health(self) -> Dict[str, bool]:
        ledgers = {
            "activation": ActivationLedger(self.state_dir / "activation_ledger.jsonl"),
            "dispatch": DispatchLedger(self.state_dir / "dispatch_ledger.jsonl"),
            "transport": TransportLedger(self.state_dir / "transport_ledger.jsonl"),
            "ack_reconciliation": AckReconciliationLedger(self.state_dir / "ack_reconciliation_ledger.jsonl"),
            "ack_provenance": HashLedger(self.state_dir / "ack_provenance_ledger.jsonl", "parent_provenance_hash"),
            "ack_finalization": HashLedger(self.state_dir / "ack_authenticated_finalization_ledger.jsonl", "parent_finalization_hash"),
        }
        health: Dict[str, bool] = {}
        for name, ledger in ledgers.items():
            try:
                health[name] = bool(ledger.verify())
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                health[name] = False

        outbox_ok = True
        outbox = self.state_dir / "dispatch_outbox"
        if outbox.exists():
            for path in sorted(outbox.glob("*.json")):
                try:
                    packet = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    outbox_ok = False
                    break
                if not isinstance(packet, dict) or not verify_dispatch_packet(packet):
                    outbox_ok = False
                    break
                if path.name != f"{packet.get('packet_id')}.json":
                    outbox_ok = False
                    break
        health["dispatch_outbox"] = outbox_ok
        health["hearth"] = self.hearth.verify()
        return health

    def verify(self) -> Dict[str, Any]:
        reasons: list[str] = []
        try:
            identity = json.loads(self.identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            identity = {}
        identity_ok = self.verify_identity(identity)
        if not identity_ok:
            reasons.append("Persistent resident identity failed integrity or schema verification.")

        try:
            head = self.read_head()
            head_ok = (
                head.get("resident_id") == RESIDENT_ID
                and head.get("mode") in {"AT_HOME", "AWAKE"}
                and head.get("last_hearth_hash") == self.hearth.tip_hash()
            )
        except (OSError, ValueError, json.JSONDecodeError, RuntimeError, KeyError):
            head = {}
            head_ok = False
        if not head_ok:
            reasons.append("Mutable HEAD summary failed integrity or does not match the hearth ledger tip.")

        try:
            components = self._component_health()
        except (OSError, ValueError, json.JSONDecodeError, RuntimeError, KeyError):
            components = {"hearth": False}
        component_ok = all(components.values())
        if not component_ok:
            reasons.append("At least one local Activator ledger/outbox integrity check failed.")

        ok = identity_ok and head_ok and component_ok
        result = {
            "schema": "janus.activator.persistent_state_health.v0.6.2",
            "resident_id": RESIDENT_ID,
            "resident_uuid": identity.get("resident_uuid"),
            "ok": ok,
            "status": "HEALTHY" if ok else "CORRUPT_FAIL_CLOSED",
            "mode": head.get("mode"),
            "active_cycle_id": head.get("active_cycle_id"),
            "hearth_tip_hash": self.hearth.tip_hash(),
            "component_integrity": components,
            "fresh_stimulus": False,
            "cognition_authorized": False,
            "dispatch_authorized": False,
            "target_execution_authorized": False,
            "external_effect_authorized": False,
            "reasons": reasons,
            "checked_at": time.time(),
        }
        result["health_hash"] = canonical_hash(result)
        self.health_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    def record_architecture(self, architecture_sha: str, *, workflow_run_id: str = "") -> Dict[str, Any]:
        observation = {
            "schema": "janus.activator.architecture_observation.v0.6.2",
            "architecture_branch": "main",
            "architecture_sha": str(architecture_sha),
            "workflow_run_id": str(workflow_run_id),
            "observed_at": time.time(),
            "fresh_stimulus": False,
            "command_authority_granted": False,
            "external_effect_authorized": False,
        }
        observation["observation_hash"] = canonical_hash(observation)
        path = self.observation_dir / "latest_architecture.json"
        path.write_text(json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return observation

    def hearth_cycle(self, *, source: str, reason: str, architecture_sha: str, workflow_run_id: str = "") -> Dict[str, Any]:
        identity = self.initialize()
        before = self.verify()
        if not before["ok"]:
            raise RuntimeError("PERSISTENT_STATE_INVALID_BEFORE_WAKE")
        if before.get("mode") != "AT_HOME":
            raise RuntimeError("PERSISTENT_STATE_NOT_AT_HOME_BEFORE_WAKE")

        cycle_id = "hearth-" + canonical_hash({
            "resident_uuid": identity["resident_uuid"],
            "parent_hearth_hash": self.hearth.tip_hash(),
            "source": source,
            "reason": reason,
            "architecture_sha": architecture_sha,
            "nonce": str(uuid.uuid4()),
        })

        wake = self.hearth.append({
            "schema": "janus.activator.hearth_receipt.v0.6.2",
            "event": "WAKE",
            "created_at": time.time(),
            "parent_hearth_hash": self.hearth.tip_hash(),
            "cycle_id": cycle_id,
            "resident_id": RESIDENT_ID,
            "source": str(source),
            "reason": str(reason),
            "architecture_sha": str(architecture_sha),
            "fresh_stimulus": False,
            "cognition_authorized": False,
            "dispatch_authorized": False,
            "target_execution_authorized": False,
            "external_effect_authorized": False,
        })
        self._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=wake["receipt_hash"])

        pulse = self.hearth.append({
            "schema": "janus.activator.hearth_receipt.v0.6.2",
            "event": "HEARTBEAT",
            "created_at": time.time(),
            "parent_hearth_hash": self.hearth.tip_hash(),
            "cycle_id": cycle_id,
            "resident_id": RESIDENT_ID,
            "source": str(source),
            "reason": str(reason),
            "architecture_sha": str(architecture_sha),
            "fresh_stimulus": False,
            "cognition_authorized": False,
            "dispatch_authorized": False,
            "target_execution_authorized": False,
            "external_effect_authorized": False,
        })
        self._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=pulse["receipt_hash"])
        self.record_architecture(architecture_sha, workflow_run_id=workflow_run_id)

        sleep = self.hearth.append({
            "schema": "janus.activator.hearth_receipt.v0.6.2",
            "event": "SLEEP",
            "created_at": time.time(),
            "parent_hearth_hash": self.hearth.tip_hash(),
            "cycle_id": cycle_id,
            "resident_id": RESIDENT_ID,
            "source": str(source),
            "reason": str(reason),
            "architecture_sha": str(architecture_sha),
            "fresh_stimulus": False,
            "cognition_authorized": False,
            "dispatch_authorized": False,
            "target_execution_authorized": False,
            "external_effect_authorized": False,
        })
        self._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=sleep["receipt_hash"])

        after = self.verify()
        if not after["ok"] or after.get("mode") != "AT_HOME":
            raise RuntimeError("PERSISTENT_STATE_INVALID_AFTER_SLEEP")
        return {
            "schema": "janus.activator.hearth_cycle_result.v0.6.2",
            "cycle_id": cycle_id,
            "resident_id": RESIDENT_ID,
            "resident_uuid": identity["resident_uuid"],
            "wake_hash": wake["receipt_hash"],
            "heartbeat_hash": pulse["receipt_hash"],
            "sleep_hash": sleep["receipt_hash"],
            "hearth_tip_hash": after["hearth_tip_hash"],
            "state_healthy": True,
            "mode": "AT_HOME",
            "fresh_stimulus": False,
            "cognition_authorized": False,
            "dispatch_authorized": False,
            "target_execution_authorized": False,
            "external_effect_authorized": False,
        }


__all__ = ["HearthLedger", "JanusPersistentState", "RESIDENT_ID", "STATE_SCHEMA"]
