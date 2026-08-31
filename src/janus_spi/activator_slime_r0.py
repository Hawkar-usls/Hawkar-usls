from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .activator import ActivationEvent, JanusActivator
from .slime_memory import JanusActivatorSlimeMemoryR0


class SlimeAwareJanusActivatorR0(JanusActivator):
    """JANUS HOME Activator with advisory Slime Memory R0 route ordering.

    The base Activator remains the authority boundary. R0 sees only routes that
    the declared routing table already admitted and may only reorder them.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path = "state/activator",
        routing_path: str | Path = ".janus/activator/ROUTING_TABLE.json",
        policy_path: str | Path = "config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json",
        slime_state_dir: str | Path | None = None,
    ) -> None:
        super().__init__(state_dir=state_dir, routing_path=routing_path, policy_path=policy_path)
        self.slime_memory = JanusActivatorSlimeMemoryR0(
            slime_state_dir if slime_state_dir is not None else Path(state_dir) / "slime_memory"
        )
        self._slime_context: Dict[str, Any] = {}
        self.last_slime_advice: Optional[Dict[str, Any]] = None

    def _select_routes(self, classifications: Iterable[str]) -> list[Dict[str, Any]]:
        declared = super()._select_routes(classifications)
        advice = self.slime_memory.advise(declared, context=self._slime_context)
        self.last_slime_advice = {k: v for k, v in advice.items() if k != "routes"}
        return list(advice["routes"])

    def activate(self, event: ActivationEvent) -> Dict[str, Any]:
        if not isinstance(event, ActivationEvent):
            raise TypeError("ACTIVATION_EVENT_REQUIRED")
        self._slime_context = {
            "event_id": event.event_id,
            "source_kind": event.source_kind,
            "source_ref": event.source_ref,
            "source_digest": event.payload_sha256,
            "classifications": list(event.classifications),
        }
        self.last_slime_advice = None
        try:
            return super().activate(event)
        finally:
            self._slime_context = {}

    def learn_slime_receipt(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Explicit post-finalization learning entry point; never called by activate()."""
        return self.slime_memory.learn_from_finalized_receipt(receipt)


__all__ = ["SlimeAwareJanusActivatorR0"]
