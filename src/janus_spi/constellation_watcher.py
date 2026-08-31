from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from .activator import canonical_hash


class ConstellationWatcherError(RuntimeError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ConstellationWatcherError(code)


def _read_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _read_jsonl(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        _require(isinstance(value, dict), f"JSONL_OBJECT_REQUIRED:{path.name}")
        rows.append(value)
    return rows


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot_from_model_lock(model_lock: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    _require(model_lock.get("schema") == "janus.activator.model_lock.v1", "MODEL_LOCK_SCHEMA_INVALID")
    _require(model_lock.get("ready") is True, "MODEL_LOCK_NOT_READY")
    members = model_lock.get("members")
    _require(isinstance(members, Mapping) and bool(members), "MODEL_LOCK_MEMBERS_REQUIRED")

    snapshot: Dict[str, Dict[str, Any]] = {}
    for member_key, raw in members.items():
        if not isinstance(raw, Mapping):
            continue
        repository = str(raw.get("repository") or "").strip()
        head_sha = str(raw.get("head_sha") or "").strip()
        branch = str(raw.get("resolved_branch") or raw.get("branch") or "").strip()
        if not repository or not head_sha or not branch:
            continue
        _require(
            len(head_sha) == 40 and all(c in "0123456789abcdef" for c in head_sha.lower()),
            f"MEMBER_HEAD_INVALID:{repository}",
        )
        if repository in snapshot:
            raise ConstellationWatcherError(f"DUPLICATE_REPOSITORY:{repository}")
        snapshot[repository] = {
            "member_key": str(member_key),
            "repository": repository,
            "branch": branch,
            "head_sha": head_sha.lower(),
            "kind": raw.get("kind"),
            "member_class": raw.get("member_class"),
        }
    _require(bool(snapshot), "CONSTELLATION_SNAPSHOT_EMPTY")
    return dict(sorted(snapshot.items()))


class ConstellationWatcher:
    """Observe exact model-member HEAD drift and seal bounded fresh stimuli.

    Only exact branches present in the compiled model lock are watched. Persistent
    state branches such as ``janus/activator-state`` are therefore not sensory
    inputs and cannot wake JANUS from its own receipts.
    """

    def __init__(self, state_dir: str | Path, *, now_fn=time.time) -> None:
        self.state_dir = Path(state_dir)
        self.root = self.state_dir / "constellation"
        self.heads_path = self.root / "HEADS.json"
        self.ledger_path = self.root / "STIMULUS_LEDGER.jsonl"
        self.cycles_dir = self.root / "cycles"
        self.now_fn = now_fn

    def _baseline(self, model_lock: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "schema": "janus.constellation.heads.v1",
            "model_id": "JANUS",
            "model_digest": model_lock.get("model_digest"),
            "updated_at": float(self.now_fn()),
            "members": dict(snapshot),
            "watched_branch_policy": "EXACT_MODEL_MEMBER_BRANCHES_ONLY",
            "persistent_state_branches_are_sensory_inputs": False,
        }
        body["heads_hash"] = canonical_hash(body)
        return body

    def _verify_baseline(self, baseline: Mapping[str, Any]) -> Mapping[str, Any]:
        claimed_heads_hash = str(baseline.get("heads_hash") or "")
        baseline_body = dict(baseline)
        baseline_body.pop("heads_hash", None)
        _require(canonical_hash(baseline_body) == claimed_heads_hash, "CONSTELLATION_BASELINE_HASH_INVALID")
        members = baseline.get("members") or {}
        _require(isinstance(members, Mapping), "CONSTELLATION_BASELINE_MEMBERS_INVALID")
        return members

    def _verify_ledger(self, rows: list[Mapping[str, Any]]) -> None:
        parent = None
        seen: set[str] = set()
        for row in rows:
            _require(row.get("parent_stimulus_hash") == parent, "STIMULUS_LEDGER_PARENT_MISMATCH")
            stimulus_id = str(row.get("stimulus_id") or "")
            _require(stimulus_id and stimulus_id not in seen, "STIMULUS_ID_DUPLICATE_OR_MISSING")
            claimed = str(row.get("stimulus_receipt_hash") or "")
            body = dict(row)
            body.pop("stimulus_receipt_hash", None)
            _require(canonical_hash(body) == claimed, "STIMULUS_LEDGER_HASH_INVALID")
            event = row.get("event") or {}
            _require(event.get("fresh") is True, "STIMULUS_MUST_BE_FRESH")
            _require(event.get("self_generated") is False, "SELF_GENERATED_STIMULUS_FORBIDDEN")
            _require(event.get("command_authority") is False, "STIMULUS_COMMAND_AUTHORITY_FORBIDDEN")
            _require(event.get("effect_authorized") is False, "STIMULUS_EFFECT_AUTHORITY_FORBIDDEN")
            seen.add(stimulus_id)
            parent = claimed

    def _closed_cycle_ids(self) -> set[str]:
        if not self.cycles_dir.exists():
            return set()
        ids: set[str] = set()
        for path in sorted(self.cycles_dir.glob("*.json")):
            value = _read_json(path)
            if value and value.get("state") == "CLOSED_AT_HOME":
                ids.add(str(value.get("stimulus_id")))
        return ids

    def _pending_rows(self) -> list[Dict[str, Any]]:
        rows = _read_jsonl(self.ledger_path)
        self._verify_ledger(rows)
        closed = self._closed_cycle_ids()
        return [dict(row) for row in rows if str(row.get("stimulus_id")) not in closed]

    def preflight(self, reader: Any) -> Dict[str, Any]:
        """Cheap exact-HEAD gate before a full federated model compile.

        Quiet polls resolve only the branches already sealed in HEADS.json. They do
        not fetch topology/descriptor JSON and never mutate baseline or ledger.
        Any drift, unresolved ref, missing baseline, or crash-left pending stimulus
        escalates to the existing full scan, which remains the only authority for
        changing membership and sealing new stimuli.
        """

        baseline = _read_json(self.heads_path)
        if baseline is None:
            return {
                "schema": "janus.constellation.preflight.v1",
                "terminal": "CONSTELLATION_PREFLIGHT_BASELINE_MISSING",
                "requires_full_scan": True,
                "drift_count": 0,
                "unresolved_count": 0,
                "pending_stimulus_count": 0,
                "drift": [],
                "unresolved": [],
                "reason": "BASELINE_MISSING",
            }

        members = self._verify_baseline(baseline)
        pending = self._pending_rows()
        if pending:
            return {
                "schema": "janus.constellation.preflight.v1",
                "terminal": "CONSTELLATION_PREFLIGHT_PENDING_STIMULI",
                "requires_full_scan": True,
                "drift_count": 0,
                "unresolved_count": 0,
                "pending_stimulus_count": len(pending),
                "drift": [],
                "unresolved": [],
                "reason": "CRASH_SAFE_PENDING_RESUME",
            }

        drift: list[Dict[str, Any]] = []
        unresolved: list[Dict[str, Any]] = []
        for repository, old in sorted(members.items()):
            _require(isinstance(old, Mapping), f"CONSTELLATION_BASELINE_MEMBER_INVALID:{repository}")
            branch = str(old.get("branch") or "").strip()
            expected = str(old.get("head_sha") or "").strip().lower()
            _require(branch and expected, f"CONSTELLATION_BASELINE_REF_INVALID:{repository}")
            try:
                current = reader.branch_head(str(repository), branch)
            except Exception as exc:  # fail closed into full verification
                unresolved.append(
                    {
                        "repository": str(repository),
                        "branch": branch,
                        "expected_head": expected,
                        "error": type(exc).__name__,
                    }
                )
                continue
            current_text = str(current or "").strip().lower()
            if not current_text:
                unresolved.append(
                    {
                        "repository": str(repository),
                        "branch": branch,
                        "expected_head": expected,
                        "error": "HEAD_UNRESOLVED",
                    }
                )
                continue
            if current_text != expected:
                drift.append(
                    {
                        "repository": str(repository),
                        "branch": branch,
                        "previous_head": expected,
                        "current_head": current_text,
                    }
                )

        if unresolved:
            terminal = "CONSTELLATION_PREFLIGHT_INDETERMINATE"
            reason = "HEAD_RESOLUTION_INDETERMINATE"
            requires_full_scan = True
        elif drift:
            terminal = "CONSTELLATION_PREFLIGHT_DRIFT"
            reason = "EXACT_MEMBER_HEAD_DRIFT"
            requires_full_scan = True
        else:
            terminal = "CONSTELLATION_PREFLIGHT_QUIET"
            reason = "NO_REGISTERED_HEAD_DRIFT"
            requires_full_scan = False

        return {
            "schema": "janus.constellation.preflight.v1",
            "terminal": terminal,
            "requires_full_scan": requires_full_scan,
            "drift_count": len(drift),
            "unresolved_count": len(unresolved),
            "pending_stimulus_count": 0,
            "drift": drift,
            "unresolved": unresolved,
            "reason": reason,
            "heads_hash": baseline.get("heads_hash"),
            "persistent_state_branches_are_sensory_inputs": False,
        }

    def scan(self, model_lock: Mapping[str, Any]) -> Dict[str, Any]:
        snapshot = snapshot_from_model_lock(model_lock)
        current_baseline = _read_json(self.heads_path)
        rows = _read_jsonl(self.ledger_path)
        self._verify_ledger(rows)

        if current_baseline is None:
            baseline = self._baseline(model_lock, snapshot)
            _write_json(self.heads_path, baseline)
            return {
                "schema": "janus.constellation.scan.v1",
                "terminal": "CONSTELLATION_BASELINE_INITIALIZED",
                "model_digest": model_lock.get("model_digest"),
                "new_stimulus_count": 0,
                "pending_stimulus_count": 0,
                "pending_stimuli": [],
                "heads_hash": baseline["heads_hash"],
            }

        previous = self._verify_baseline(current_baseline)
        existing_ids = {str(row.get("stimulus_id")) for row in rows}
        parent = str(rows[-1]["stimulus_receipt_hash"]) if rows else None
        new_rows: list[Dict[str, Any]] = []

        for repository, current in snapshot.items():
            old = previous.get(repository)
            if not isinstance(old, Mapping):
                change_kind = "MODEL_MEMBER_APPEARED"
                old_head = None
            elif old.get("head_sha") != current.get("head_sha") or old.get("branch") != current.get("branch"):
                change_kind = "MODEL_MEMBER_HEAD_CHANGED"
                old_head = old.get("head_sha")
            else:
                continue

            identity = {
                "repository": repository,
                "branch": current["branch"],
                "previous_head": old_head,
                "current_head": current["head_sha"],
                "change_kind": change_kind,
            }
            stimulus_id = "stim-" + canonical_hash(identity)
            if stimulus_id in existing_ids:
                continue
            event = {
                "source_kind": "REPOSITORY_CONSTELLATION_CHANGE",
                "source_ref": f"{repository}@{current['head_sha']}",
                "payload": {
                    **identity,
                    "member_key": current.get("member_key"),
                    "member_kind": current.get("kind"),
                    "commit_text_interpreted_as_command": False,
                },
                "classifications": ["repository_constellation_change"],
                "fresh": True,
                "self_generated": False,
                "command_authority": False,
                "effect_authorized": False,
            }
            row: Dict[str, Any] = {
                "schema": "janus.constellation.stimulus_receipt.v1",
                "created_at": float(self.now_fn()),
                "stimulus_id": stimulus_id,
                "parent_stimulus_hash": parent,
                "identity": identity,
                "event": event,
                "laws": [
                    "COMMIT != COMMAND",
                    "SELF_OUTPUT != FRESH_TRIGGER",
                    "STIMULUS != EXECUTION_AUTHORITY",
                ],
            }
            row["stimulus_receipt_hash"] = canonical_hash(row)
            parent = row["stimulus_receipt_hash"]
            new_rows.append(row)
            existing_ids.add(stimulus_id)

        if new_rows:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                for row in new_rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()

        baseline = self._baseline(model_lock, snapshot)
        _write_json(self.heads_path, baseline)
        rows = _read_jsonl(self.ledger_path)
        self._verify_ledger(rows)
        closed = self._closed_cycle_ids()
        pending = [dict(row) for row in rows if str(row.get("stimulus_id")) not in closed]
        return {
            "schema": "janus.constellation.scan.v1",
            "terminal": "CONSTELLATION_STIMULI_PENDING" if pending else "CONSTELLATION_QUIET",
            "model_digest": model_lock.get("model_digest"),
            "new_stimulus_count": len(new_rows),
            "pending_stimulus_count": len(pending),
            "pending_stimuli": pending,
            "heads_hash": baseline["heads_hash"],
        }

    def reconcile(self, stimulus_id: str, runtime_receipt: Mapping[str, Any]) -> Dict[str, Any]:
        rows = _read_jsonl(self.ledger_path)
        self._verify_ledger(rows)
        row = next((r for r in rows if r.get("stimulus_id") == stimulus_id), None)
        _require(row is not None, "STIMULUS_NOT_FOUND")
        _require(runtime_receipt.get("schema") == "janus.activator.model_runtime_receipt.v1", "RUNTIME_RECEIPT_SCHEMA_INVALID")
        _require(runtime_receipt.get("event_id"), "RUNTIME_EVENT_ID_REQUIRED")
        _require(runtime_receipt.get("dispatch_authorized") is False, "R1_DISPATCH_MUST_REMAIN_FALSE")
        _require(runtime_receipt.get("command_authority_granted") is False, "R1_COMMAND_AUTHORITY_MUST_REMAIN_FALSE")
        _require(runtime_receipt.get("external_effect_authorized") is False, "R1_EXTERNAL_EFFECT_MUST_REMAIN_FALSE")
        _require(runtime_receipt.get("physical_runtime_effect_authorized") is False, "R1_PHYSICAL_EFFECT_MUST_REMAIN_FALSE")
        matches = [r for r in runtime_receipt.get("route_bindings") or [] if r.get("match") == "repository_constellation_change"]
        _require(bool(matches), "CONSTELLATION_ROUTE_NOT_SELECTED")
        runtime_hash = str(runtime_receipt.get("runtime_receipt_hash") or "")
        _require(bool(runtime_hash), "RUNTIME_RECEIPT_HASH_REQUIRED")

        target = self.cycles_dir / f"{stimulus_id}.json"
        existing = _read_json(target)
        if existing is not None:
            _require(existing.get("stimulus_id") == stimulus_id, "CYCLE_STIMULUS_ID_MISMATCH")
            _require(existing.get("stimulus_receipt_hash") == row.get("stimulus_receipt_hash"), "CYCLE_STIMULUS_HASH_MISMATCH")
            _require(existing.get("runtime_receipt_hash") == runtime_hash, "CYCLE_RUNTIME_RECEIPT_HASH_MISMATCH")
            _require(existing.get("state") == "CLOSED_AT_HOME", "CYCLE_NOT_CLOSED_AT_HOME")
            return existing

        cycle_body: Dict[str, Any] = {
            "schema": "janus.constellation.cycle_receipt.v1",
            "created_at": float(self.now_fn()),
            "stimulus_id": stimulus_id,
            "stimulus_receipt_hash": row["stimulus_receipt_hash"],
            "runtime_receipt_hash": runtime_hash,
            "model_digest": runtime_receipt.get("model_digest"),
            "activation_id": runtime_receipt.get("activation_id"),
            "event_id": runtime_receipt.get("event_id"),
            "terminal": runtime_receipt.get("terminal"),
            "active_members": list(runtime_receipt.get("active_members") or []),
            "dispatch_authorized": False,
            "external_effect_authorized": False,
            "state": "CLOSED_AT_HOME",
            "next_gate": "WAIT_FOR_NEW_FRESH_STIMULUS",
        }
        cycle_body["cycle_receipt_hash"] = canonical_hash(cycle_body)
        _write_json(target, cycle_body)
        return cycle_body

    def verify(self) -> Dict[str, Any]:
        baseline = _read_json(self.heads_path)
        _require(baseline is not None, "CONSTELLATION_BASELINE_MISSING")
        self._verify_baseline(baseline)
        claimed = str(baseline.get("heads_hash") or "")
        rows = _read_jsonl(self.ledger_path)
        self._verify_ledger(rows)
        known = {str(row.get("stimulus_id")): row for row in rows}
        closed = 0
        for path in sorted(self.cycles_dir.glob("*.json")) if self.cycles_dir.exists() else []:
            cycle = _read_json(path)
            assert cycle is not None
            cycle_hash = str(cycle.get("cycle_receipt_hash") or "")
            cycle_body = dict(cycle)
            cycle_body.pop("cycle_receipt_hash", None)
            _require(canonical_hash(cycle_body) == cycle_hash, "CYCLE_RECEIPT_HASH_INVALID")
            sid = str(cycle.get("stimulus_id") or "")
            _require(sid in known, "CYCLE_STIMULUS_UNKNOWN")
            _require(cycle.get("stimulus_receipt_hash") == known[sid].get("stimulus_receipt_hash"), "CYCLE_STIMULUS_HASH_MISMATCH")
            _require(cycle.get("state") == "CLOSED_AT_HOME", "CYCLE_NOT_CLOSED_AT_HOME")
            _require(cycle.get("dispatch_authorized") is False, "CYCLE_DISPATCH_AUTHORITY_FORBIDDEN")
            _require(cycle.get("external_effect_authorized") is False, "CYCLE_EFFECT_AUTHORITY_FORBIDDEN")
            closed += 1
        return {
            "ok": True,
            "schema": "janus.constellation.verify.v1",
            "stimulus_count": len(rows),
            "closed_cycle_count": closed,
            "pending_cycle_count": len(rows) - closed,
            "heads_hash": claimed,
            "persistent_state_branches_are_sensory_inputs": False,
        }


__all__ = ["ConstellationWatcher", "ConstellationWatcherError", "snapshot_from_model_lock"]
