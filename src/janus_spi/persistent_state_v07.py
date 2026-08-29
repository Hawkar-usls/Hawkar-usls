from __future__ import annotations

import json

from .execution_grant import ExecutionGrantLedger
from .persistent_state import JanusPersistentState as LegacyJanusPersistentState


class HardenedJanusPersistentState(LegacyJanusPersistentState):
    """v0.7 HOME health adds execution-grant lineage to the hearth boundary."""

    def _component_health(self) -> dict[str, bool]:
        health = super()._component_health()
        try:
            health["execution_grant"] = bool(
                ExecutionGrantLedger(self.state_dir / "execution_grant_ledger.jsonl").verify()
            )
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            health["execution_grant"] = False
        return health


__all__ = ["HardenedJanusPersistentState", "LegacyJanusPersistentState"]
