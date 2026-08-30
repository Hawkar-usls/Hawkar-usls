from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol

from .ack_provenance import GitHubAPIReader, GitHubAckProvenanceVerifier
from .activator import ActivationEvent, JanusActivator, canonical_hash
from .dispatch import JanusDispatchBroker
from .execution_grant import JanusExecutionGrantIssuer, verify_execution_grant
from .execution_return import GitHubExecutionReturnVerifier, JanusExecutionResultFinalizer
from .execution_transport import JanusExecutionTransportBroker
from .local_lineage import HardenedJanusAckReconciler, HardenedJanusAuthenticatedAckFinalizer
from .persistent_state_v08 import HardenedJanusPersistentStateV08
from .transport import JanusTransportBroker

TARGET_REPOSITORY = "Hawkar-usls/Janus-Demiurge"
ACK_WORKFLOW_ID = 345454851
EXECUTION_WORKFLOW_ID = 345491145
API_BASE = "https://api.github.com"


class GitHubReader(Protocol):
    def get_json(self, url: str) -> Any: ...
    def get_bytes(self, url: str) -> bytes: ...


class LiveCycleLedger:
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
                raise ValueError("LIVE_CYCLE_LEDGER_ROW_NOT_OBJECT")
            rows.append(row)
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
            if row.get("parent_live_cycle_hash") != previous:
                return False
            claimed = str(row.get("receipt_hash") or "")
            body = dict(row)
            body.pop("receipt_hash", None)
            if canonical_hash(body) != claimed:
                return False
            previous = claimed
        return True


class HardenedJanusPersistentStateV09(HardenedJanusPersistentStateV08):
    def _component_health(self) -> Dict[str, bool]:
        health = super()._component_health()
        try:
            health["live_cycle"] = LiveCycleLedger(self.state_dir / "live_cycle_ledger.jsonl").verify()
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            health["live_cycle"] = False
        return health


def _workflow_runs_url(workflow_id: int) -> str:
    return f"{API_BASE}/repos/{TARGET_REPOSITORY}/actions/workflows/{workflow_id}/runs?per_page=50"


def _run_rows(reader: GitHubReader, workflow_id: int) -> list[Dict[str, Any]]:
    value = reader.get_json(_workflow_runs_url(workflow_id))
    rows = value.get("workflow_runs") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("WORKFLOW_RUN_LIST_MALFORMED")
    return [row for row in rows if isinstance(row, dict)]


def _run_ids(reader: GitHubReader, workflow_id: int) -> set[int]:
    ids: set[int] = set()
    for row in _run_rows(reader, workflow_id):
        value = row.get("id")
        if isinstance(value, int):
            ids.add(value)
    return ids


class JanusLiveCycle:
    """One persistent fresh-stimulus HOME -> Demiurge -> HOME closed loop.

    The cycle is intentionally narrow: one fresh external trigger, one declared
    research route, one low-risk read-only Demiurge handoff, authenticated ACK,
    explicit P12 grant, authenticated bounded execution return, checkpoint and
    return to AT_HOME. No command/claim/scientific/external-effect authority is
    created by the cycle.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path = "state/activator",
        routing_path: str | Path = ".janus/activator/ROUTING_TABLE.json",
        policy_path: str | Path = "config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json",
        reader: Optional[GitHubReader] = None,
        packet_opener=None,
        execution_opener=None,
        sleep_fn: Callable[[float], None] = time.sleep,
        poll_interval_seconds: float = 5.0,
        max_wait_seconds: float = 240.0,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.routing_path = Path(routing_path)
        self.policy_path = Path(policy_path)
        self.reader = reader
        self.packet_opener = packet_opener
        self.execution_opener = execution_opener
        self.sleep_fn = sleep_fn
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds))
        self.max_wait_seconds = max(5.0, float(max_wait_seconds))
        self.state = HardenedJanusPersistentStateV09(self.state_dir)
        self.live_ledger = LiveCycleLedger(self.state_dir / "live_cycle_ledger.jsonl")

    def _reader(self, provenance_token: str) -> GitHubReader:
        return self.reader or GitHubAPIReader(provenance_token)

    def _wait_for_ack(
        self,
        *,
        reader: GitHubReader,
        baseline: set[int],
        packet: Dict[str, Any],
        provenance_token: str,
    ) -> tuple[Optional[int], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        deadline = time.monotonic() + self.max_wait_seconds
        attempted: set[int] = set()
        while time.monotonic() < deadline:
            rows = _run_rows(reader, ACK_WORKFLOW_ID)
            candidates = [
                row for row in rows
                if isinstance(row.get("id"), int)
                and row["id"] not in baseline
                and row["id"] not in attempted
                and row.get("event") == "repository_dispatch"
                and row.get("status") == "completed"
            ]
            for row in candidates:
                run_id = int(row["id"])
                attempted.add(run_id)
                provenance, ack = GitHubAckProvenanceVerifier(self.state_dir, reader=reader).verify_run(
                    run_id, token=provenance_token
                )
                if (
                    provenance.get("source_authenticated") is True
                    and ack is not None
                    and ack.get("packet_id") == packet.get("packet_id")
                    and ack.get("packet_hash") == packet.get("packet_hash")
                ):
                    return run_id, provenance, ack
            self.sleep_fn(self.poll_interval_seconds)
        return None, None, None

    def _wait_for_execution(
        self,
        *,
        reader: GitHubReader,
        baseline: set[int],
        grant: Dict[str, Any],
        provenance_token: str,
    ) -> tuple[Optional[int], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        deadline = time.monotonic() + self.max_wait_seconds
        attempted: set[int] = set()
        while time.monotonic() < deadline:
            rows = _run_rows(reader, EXECUTION_WORKFLOW_ID)
            candidates = [
                row for row in rows
                if isinstance(row.get("id"), int)
                and row["id"] not in baseline
                and row["id"] not in attempted
                and row.get("event") == "repository_dispatch"
                and row.get("status") == "completed"
            ]
            for row in candidates:
                run_id = int(row["id"])
                attempted.add(run_id)
                provenance, receipt, snapshot = GitHubExecutionReturnVerifier(
                    self.state_dir, reader=reader
                ).verify_run(run_id, token=provenance_token)
                if (
                    provenance.get("source_authenticated") is True
                    and receipt is not None
                    and receipt.get("grant_id") == grant.get("grant_id")
                    and receipt.get("grant_hash") == grant.get("grant_hash")
                ):
                    return run_id, provenance, receipt, snapshot
            self.sleep_fn(self.poll_interval_seconds)
        return None, None, None, None

    def _hearth_event(self, event: str, *, cycle_id: str, parent: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "schema": "janus.activator.live_hearth_receipt.v0.9",
            "event": event,
            "created_at": time.time(),
            "parent_hearth_hash": parent,
            "cycle_id": cycle_id,
            "resident_id": "JANUS",
            "fresh_stimulus": True,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
            "payload": payload,
        }
        return self.state.hearth.append(body)

    def run(
        self,
        *,
        source_ref: str,
        payload: Any,
        dispatch_token: str,
        provenance_token: str,
    ) -> Dict[str, Any]:
        identity = self.state.initialize()
        before = self.state.verify()
        if not before.get("ok") or before.get("mode") != "AT_HOME":
            raise RuntimeError("LIVE_CYCLE_HOME_NOT_HEALTHY_AT_HOME")

        event = ActivationEvent.build(
            source_kind="EXPLICIT_EXTERNAL_WORKFLOW_TRIGGER",
            source_ref=source_ref,
            payload=payload,
            classifications=["research_or_anomaly_investigation"],
            fresh=True,
            self_generated=False,
            command_authority=False,
            effect_authorized=False,
        )
        cycle_id = "live-" + canonical_hash({
            "resident_uuid": identity["resident_uuid"],
            "event_id": event.event_id,
            "parent_live_cycle_hash": self.live_ledger.tip_hash(),
            "nonce": str(uuid.uuid4()),
        })

        result: Dict[str, Any] = {
            "schema": "janus.activator.live_cycle_result.v0.9",
            "cycle_id": cycle_id,
            "resident_uuid": identity["resident_uuid"],
            "event_id": event.event_id,
            "source_ref": source_ref,
            "fresh_external_stimulus": True,
            "activation_receipt_hash": None,
            "dispatch_packet_id": None,
            "dispatch_packet_hash": None,
            "packet_transport_receipt_hash": None,
            "ack_run_id": None,
            "ack_final_receipt_hash": None,
            "execution_grant_hash": None,
            "execution_transport_receipt_hash": None,
            "execution_run_id": None,
            "execution_result_receipt_hash": None,
            "target_execution_observed": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "terminal": "LIVE_CYCLE_INITIALIZING",
            "reasons": [],
        }

        # Preflight both credentials before opening a fresh cycle or crossing a
        # network boundary. This avoids creating avoidable unresolved transports.
        if not str(dispatch_token).strip() or not str(provenance_token).strip():
            result["terminal"] = "LIVE_CYCLE_BLOCKED_PREFLIGHT_CREDENTIAL"
            result["reasons"] = [
                "Both cross-repository dispatch and read-only provenance credentials are required before fresh-cycle WAKE."
            ]
            return self._record_cycle_result(result, wake=None, checkpoint=None, sleep=None)

        reader = self._reader(provenance_token)
        try:
            ack_baseline = _run_ids(reader, ACK_WORKFLOW_ID)
            execution_baseline = _run_ids(reader, EXECUTION_WORKFLOW_ID)
        except Exception as exc:
            result["terminal"] = "LIVE_CYCLE_BLOCKED_PREFLIGHT_PROVENANCE_READ"
            result["reasons"] = [f"Preflight GitHub run-index read failed with {type(exc).__name__}; no fresh-cycle WAKE occurred."]
            return self._record_cycle_result(result, wake=None, checkpoint=None, sleep=None)

        wake = self._hearth_event(
            "WAKE_FRESH_STIMULUS",
            cycle_id=cycle_id,
            parent=self.state.hearth.tip_hash(),
            payload={"event_id": event.event_id, "source_ref": source_ref, "cognition_authorized": True},
        )
        self.state._write_head(mode="AWAKE", active_cycle_id=cycle_id, last_hearth_hash=wake["receipt_hash"])
        checkpoint: Optional[Dict[str, Any]] = None
        sleep: Optional[Dict[str, Any]] = None

        try:
            activation = JanusActivator(
                state_dir=self.state_dir,
                routing_path=self.routing_path,
                policy_path=self.policy_path,
            ).activate(event)
            result["activation_receipt_hash"] = activation.get("receipt_hash")
            if activation.get("terminal") != "ROUTE_PROPOSED":
                result["terminal"] = "LIVE_CYCLE_BLOCKED_ACTIVATION"
                result["reasons"] = ["Fresh stimulus did not produce a declared route proposal."]
                return self._close(result, wake)

            dispatch = JanusDispatchBroker(self.state_dir).dispatch(
                activation,
                target_organ=TARGET_REPOSITORY,
            )
            if dispatch.get("terminal") not in {"AUTHORIZED_INTERNAL_HANDOFF", "ALREADY_EMITTED"}:
                result["terminal"] = "LIVE_CYCLE_BLOCKED_DISPATCH"
                result["reasons"] = [f"Dispatch broker terminal: {dispatch.get('terminal')}."]
                return self._close(result, wake)
            packet_path = Path(str(dispatch["packet_path"]))
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            result["dispatch_packet_id"] = packet.get("packet_id")
            result["dispatch_packet_hash"] = packet.get("packet_hash")

            packet_broker = JanusTransportBroker(
                state_dir=self.state_dir,
                **({"opener": self.packet_opener} if self.packet_opener is not None else {}),
            )
            transport = packet_broker.send(packet, token=dispatch_token)
            result["packet_transport_receipt_hash"] = transport.get("receipt_hash")
            if transport.get("terminal") not in {"TRANSPORT_SENT_AWAITING_ACK", "TRANSPORT_OUTCOME_UNDETERMINED"}:
                result["terminal"] = "LIVE_CYCLE_BLOCKED_PACKET_TRANSPORT"
                result["reasons"] = [f"Packet transport terminal: {transport.get('terminal')}."]
                return self._close(result, wake)

            ack_run_id, ack_provenance, ack = self._wait_for_ack(
                reader=reader,
                baseline=ack_baseline,
                packet=packet,
                provenance_token=provenance_token,
            )
            if ack is None or ack_provenance is None or ack_run_id is None:
                result["terminal"] = "LIVE_CYCLE_ACK_WAIT_UNRESOLVED"
                result["reasons"] = ["No authenticated matching receiver ACK was observed before the bounded wait deadline; transport is not replayed."]
                return self._close(result, wake)
            result["ack_run_id"] = ack_run_id

            structural = HardenedJanusAckReconciler(self.state_dir).reconcile(packet, transport, ack)
            if structural.get("terminal") != "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION":
                result["terminal"] = "LIVE_CYCLE_BLOCKED_ACK_STRUCTURAL_BINDING"
                result["reasons"] = [f"ACK structural terminal: {structural.get('terminal')}."]
                return self._close(result, wake)
            ack_final = HardenedJanusAuthenticatedAckFinalizer(self.state_dir).finalize(structural, ack_provenance)
            result["ack_final_receipt_hash"] = ack_final.get("receipt_hash")
            if ack_final.get("terminal") != "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION":
                result["terminal"] = "LIVE_CYCLE_BLOCKED_ACK_FINALIZATION"
                result["reasons"] = [f"ACK finalization terminal: {ack_final.get('terminal')}."]
                return self._close(result, wake)

            grant = JanusExecutionGrantIssuer(self.state_dir).issue(ack_final)
            result["execution_grant_hash"] = grant.get("grant_hash")
            if not verify_execution_grant(grant):
                result["terminal"] = "LIVE_CYCLE_BLOCKED_EXECUTION_GRANT"
                result["reasons"] = [f"Execution-grant terminal: {grant.get('terminal')}."]
                return self._close(result, wake)

            execution_broker = JanusExecutionTransportBroker(
                state_dir=self.state_dir,
                **({"opener": self.execution_opener} if self.execution_opener is not None else {}),
            )
            execution_transport = execution_broker.send(grant, token=dispatch_token)
            result["execution_transport_receipt_hash"] = execution_transport.get("receipt_hash")
            if execution_transport.get("terminal") not in {"EXECUTION_TRANSPORT_SENT_AWAITING_RESULT", "EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED"}:
                result["terminal"] = "LIVE_CYCLE_BLOCKED_EXECUTION_TRANSPORT"
                result["reasons"] = [f"Execution transport terminal: {execution_transport.get('terminal')}."]
                return self._close(result, wake)

            execution_run_id, execution_provenance, execution_receipt, _snapshot = self._wait_for_execution(
                reader=reader,
                baseline=execution_baseline,
                grant=grant,
                provenance_token=provenance_token,
            )
            if execution_receipt is None or execution_provenance is None or execution_run_id is None:
                result["terminal"] = "LIVE_CYCLE_EXECUTION_WAIT_UNRESOLVED"
                result["reasons"] = ["No authenticated matching bounded-execution result was observed before the wait deadline; grant transport is not replayed."]
                return self._close(result, wake)
            result["execution_run_id"] = execution_run_id

            execution_final = JanusExecutionResultFinalizer(self.state_dir).finalize(
                grant, execution_transport, execution_provenance, execution_receipt
            )
            result["execution_result_receipt_hash"] = execution_final.get("receipt_hash")
            if execution_final.get("terminal") != "EXECUTION_RESULT_AUTHENTICATED_READ_ONLY_ORIENTATION_OBSERVED":
                result["terminal"] = "LIVE_CYCLE_BLOCKED_EXECUTION_FINALIZATION"
                result["reasons"] = [f"Execution-result final terminal: {execution_final.get('terminal')}."]
                return self._close(result, wake)

            result["target_execution_observed"] = True
            result["terminal"] = "LIVE_CYCLE_COMPLETED_RETURNED_HOME"
            result["reasons"] = [
                "Fresh external stimulus produced a declared HOME route and bounded internal dispatch.",
                "Janus-Demiurge delivery ACK was authenticated under the pinned GitHub Actions trust model.",
                "P12 execution grant was issued only after authenticated no-execution delivery finalization.",
                "Bounded read-only target execution was independently authenticated and finalized back into persistent HOME lineage.",
                "No command, claim, scientific-evidence, world-truth, external-effect or physical-runtime authority was granted by this cycle.",
            ]
            return self._close(result, wake)
        except Exception as exc:
            result["terminal"] = "LIVE_CYCLE_ABORTED_EXCEPTION"
            result["reasons"] = [f"Live cycle raised {type(exc).__name__}; partial lineage is preserved and HOME will return to AT_HOME."]
            return self._close(result, wake)

    def _close(self, result: Dict[str, Any], wake: Dict[str, Any]) -> Dict[str, Any]:
        checkpoint = self._hearth_event(
            "CHECKPOINT_LIVE_CYCLE",
            cycle_id=result["cycle_id"],
            parent=self.state.hearth.tip_hash(),
            payload={
                "terminal": result["terminal"],
                "activation_receipt_hash": result.get("activation_receipt_hash"),
                "execution_result_receipt_hash": result.get("execution_result_receipt_hash"),
                "target_execution_observed": result.get("target_execution_observed", False),
            },
        )
        self.state._write_head(mode="AWAKE", active_cycle_id=result["cycle_id"], last_hearth_hash=checkpoint["receipt_hash"])
        sleep = self._hearth_event(
            "SLEEP_LIVE_CYCLE",
            cycle_id=result["cycle_id"],
            parent=self.state.hearth.tip_hash(),
            payload={"terminal": result["terminal"], "return_to_home": True},
        )
        self.state._write_head(mode="AT_HOME", active_cycle_id=None, last_hearth_hash=sleep["receipt_hash"])
        return self._record_cycle_result(result, wake=wake, checkpoint=checkpoint, sleep=sleep)

    def _record_cycle_result(
        self,
        result: Dict[str, Any],
        *,
        wake: Optional[Dict[str, Any]],
        checkpoint: Optional[Dict[str, Any]],
        sleep: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        row = dict(result)
        row.update({
            "parent_live_cycle_hash": self.live_ledger.tip_hash(),
            "wake_hearth_hash": wake.get("receipt_hash") if wake else None,
            "checkpoint_hearth_hash": checkpoint.get("receipt_hash") if checkpoint else None,
            "sleep_hearth_hash": sleep.get("receipt_hash") if sleep else None,
            "returned_at_home": bool(sleep is not None),
            "persistence_replay_required_for_launch_witness": result.get("terminal") == "LIVE_CYCLE_COMPLETED_RETURNED_HOME",
            "created_at": time.time(),
        })
        sealed = self.live_ledger.append(row)
        if not self.live_ledger.verify():
            raise RuntimeError("LIVE_CYCLE_LEDGER_CHAIN_INVALID_AFTER_APPEND")
        if sleep is not None:
            health = self.state.verify()
            if not health.get("ok") or health.get("mode") != "AT_HOME":
                raise RuntimeError("LIVE_CYCLE_HOME_INVALID_AFTER_SLEEP")
        return sealed


__all__ = [
    "HardenedJanusPersistentStateV09",
    "JanusLiveCycle",
    "LiveCycleLedger",
]
