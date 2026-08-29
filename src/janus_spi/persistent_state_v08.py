from __future__ import annotations

import json

from .ack_provenance import HashLedger
from .execution_transport import ExecutionTransportLedger
from .persistent_state_v07 import HardenedJanusPersistentState as V07JanusPersistentState


class HardenedJanusPersistentStateV08(V07JanusPersistentState):
    """v0.8 HOME health includes execution transport/provenance/result lineage."""

    def _component_health(self) -> dict[str, bool]:
        health = super()._component_health()
        components = {
            "execution_transport": ExecutionTransportLedger(self.state_dir / "execution_transport_ledger.jsonl"),
            "execution_provenance": HashLedger(self.state_dir / "execution_provenance_ledger.jsonl", "parent_execution_provenance_hash"),
            "execution_result_finalization": HashLedger(self.state_dir / "execution_result_finalization_ledger.jsonl", "parent_execution_result_hash"),
        }
        for name, ledger in components.items():
            try:
                health[name] = bool(ledger.verify())
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                health[name] = False
        return health


__all__ = ["HardenedJanusPersistentStateV08", "V07JanusPersistentState"]
