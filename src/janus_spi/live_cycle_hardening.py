from __future__ import annotations

from typing import Any, Dict

from .activator import ActivationEvent, ActivationLedger, canonical_hash
from .live_cycle import JanusLiveCycle


class HardenedJanusLiveCycleV091(JanusLiveCycle):
    """Fail-closed v0.9.1 wrapper for the first real-launch candidate.

    Two launch-critical properties are enforced here before the v0.9 cycle may
    cross a network boundary:

    * an external stimulus identity that already reached WAKE/activation may not
      be forced fresh again;
    * every sealed live-cycle result explicitly carries the physical-runtime
      authority ceiling required by the launch constitution.

    The wrapper intentionally does not broaden any authority or execution scope.
    """

    def _event_previously_consumed(self, event_id: str) -> bool:
        # Activation rows exist only after the fresh-cycle WAKE path reached the
        # Activator. A previous activation therefore consumes this deterministic
        # stimulus identity for execution/replay purposes.
        try:
            activation_rows = ActivationLedger(self.state_dir / "activation_ledger.jsonl").read()
        except (OSError, ValueError):
            # Corrupt/unreadable local lineage is not a reason to execute again.
            return True
        for row in activation_rows:
            event = row.get("event") if isinstance(row, dict) else None
            if isinstance(event, dict) and event.get("event_id") == event_id:
                return True

        # Also reject a live-cycle row for the same event when that row records a
        # real WAKE. Preflight failures with wake_hearth_hash=None did not consume
        # the stimulus and may be retried only if the caller intentionally reuses
        # the identity.
        try:
            live_rows = self.live_ledger.read()
        except (OSError, ValueError):
            return True
        return any(
            isinstance(row, dict)
            and row.get("event_id") == event_id
            and row.get("wake_hearth_hash") is not None
            for row in live_rows
        )

    def _record_cycle_result(self, result: Dict[str, Any], *, wake, checkpoint, sleep) -> Dict[str, Any]:
        # This is part of the sealed row, not an after-the-fact annotation.
        result["physical_runtime_effect_authorized"] = False
        return super()._record_cycle_result(
            result,
            wake=wake,
            checkpoint=checkpoint,
            sleep=sleep,
        )

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
        if self._event_previously_consumed(event.event_id):
            result: Dict[str, Any] = {
                "schema": "janus.activator.live_cycle_result.v0.9",
                "cycle_id": "live-replay-block-" + canonical_hash({
                    "resident_uuid": identity["resident_uuid"],
                    "event_id": event.event_id,
                    "parent_live_cycle_hash": self.live_ledger.tip_hash(),
                }),
                "resident_uuid": identity["resident_uuid"],
                "event_id": event.event_id,
                "source_ref": source_ref,
                "fresh_external_stimulus": False,
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
                "physical_runtime_effect_authorized": False,
                "terminal": "LIVE_CYCLE_BLOCKED_REPLAYED_STIMULUS",
                "reasons": [
                    "The deterministic external stimulus event_id is already present in persistent consumed lineage.",
                    "Replay is blocked before WAKE, dispatch, transport, or target execution.",
                ],
            }
            return self._record_cycle_result(result, wake=None, checkpoint=None, sleep=None)

        return super().run(
            source_ref=source_ref,
            payload=payload,
            dispatch_token=dispatch_token,
            provenance_token=provenance_token,
        )


__all__ = ["HardenedJanusLiveCycleV091"]
