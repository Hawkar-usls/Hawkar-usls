from __future__ import annotations

from typing import Any, Dict, Optional

from .aura_habitat_spiral import AuraPeerAdapter, SpiralDialogueEngine


class AdvancingSpiralDialogueEngine(SpiralDialogueEngine):
    """Preferred cognitive API for the Aura/SPI/Habitat runtime.

    The inherited ``cycle`` name is retained only for backwards compatibility in
    older callers. New runtime surfaces call ``spiral_step`` to make the state
    semantics explicit: a fresh trigger creates generation n; a verified return
    may promote ORIGIN_PRIME_(n+1); HOLD/REJECT are preserved rather than reset.

    This adapter does not alter the fail-closed authority model of the underlying
    engine and does not turn technical event loops into epistemic promotion.
    """

    def spiral_step(
        self,
        *,
        trigger_text: str,
        source_ref: str,
        intent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        intent_authority: str = "LOCAL_PREVIEW",
        demihead_decision: str = "HOLD",
        public_content: bool = False,
    ) -> Dict[str, Any]:
        receipt = super().cycle(
            trigger_text=trigger_text,
            source_ref=source_ref,
            intent_id=intent_id,
            session_id=session_id,
            intent_authority=intent_authority,
            demihead_decision=demihead_decision,
            public_content=public_content,
        )
        legacy_schema = receipt.get("schema")
        receipt["schema"] = "janus.aura_spi.spiral_step_receipt.v2"
        receipt["legacy_base_schema"] = legacy_schema
        receipt["preferred_operation"] = "SPIRAL_STEP"
        receipt["legacy_cycle_api_used_internally"] = True
        receipt["legacy_cycle_api_semantics"] = "BACKWARD_COMPATIBILITY_ONLY_NOT_RING_MODEL"
        receipt["position_may_repeat_state_must_advance"] = True
        receipt["return_is_reset"] = False
        return receipt


__all__ = ["AdvancingSpiralDialogueEngine", "AuraPeerAdapter"]
