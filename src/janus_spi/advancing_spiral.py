from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Any, Dict, Optional

from .aura_habitat_spiral import (
    AURA_REFLECTION_SCHEMA,
    AuraPeerAdapter as _LegacyAuraPeerAdapter,
    SpiralDialogueEngine,
)


class AuraPeerAdapter(_LegacyAuraPeerAdapter):
    """Bounded subprocess adapter used by the preferred advancing runtime.

    The legacy adapter remains available for backwards compatibility inside
    ``aura_habitat_spiral``. New runtime entrypoints import this hardened adapter,
    which fails closed on timeout, oversized packets and oversized peer output.
    """

    def __init__(
        self,
        command: Optional[list[str]] = None,
        *,
        timeout_seconds: float = 60.0,
        max_input_bytes: int = 1_048_576,
        max_output_bytes: int = 2_097_152,
    ) -> None:
        super().__init__(command)
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.max_input_bytes = max(1, int(max_input_bytes))
        self.max_output_bytes = max(1, int(max_output_bytes))

    @staticmethod
    def _read_bounded(handle: Any, limit: int) -> bytes:
        handle.flush()
        handle.seek(0)
        data = handle.read(limit + 1)
        if len(data) > limit:
            raise ValueError("AURA_PEER_OUTPUT_EXCEEDS_LIMIT")
        return data

    def reflect(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        if not self.command:
            return super().reflect(packet)

        payload = json.dumps(packet, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.max_input_bytes:
            raise ValueError("AURA_PEER_INPUT_EXCEEDS_LIMIT")

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            try:
                proc.communicate(payload, timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                proc.kill()
                proc.wait()
                raise TimeoutError("AURA_PEER_TIMEOUT") from exc

            stdout = self._read_bounded(stdout_file, self.max_output_bytes)
            stderr = self._read_bounded(stderr_file, self.max_output_bytes)

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"AURA_PEER_FAILED:{stderr_text[:4096]}")

        try:
            value = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("AURA_PEER_INVALID_JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("AURA_PEER_JSON_OBJECT_REQUIRED")
        if value.get("schema") != AURA_REFLECTION_SCHEMA:
            raise ValueError("AURA_REFLECTION_SCHEMA_MISMATCH")
        if value.get("intent_id") != packet["intent_id"]:
            raise ValueError("AURA_INTENT_SPLIT_REJECT")
        if value.get("predictive_label_authority") is not False:
            raise ValueError("AURA_PREDICTIVE_LABEL_AUTHORITY_REJECT")
        if value.get("scientific_evidence_authority") is not False:
            raise ValueError("AURA_EVIDENCE_AUTHORITY_REJECT")
        return value


class AdvancingSpiralDialogueEngine(SpiralDialogueEngine):
    """Preferred cognitive API for the Aura/SPI/Habitat runtime.

    The inherited ``cycle`` name is retained only for backwards compatibility in
    older callers. New runtime surfaces call ``spiral_step`` to make the state
    semantics explicit: a fresh trigger creates generation n; a verified return
    may promote ORIGIN_PRIME_(n+1); HOLD/REJECT are preserved rather than reset.

    This adapter does not alter the fail-closed authority model of the underlying
    engine and does not turn technical event loops into epistemic promotion. A
    supplied DemiHead arbitration receipt is only forwarded to the existing base
    verifier; this wrapper grants no additional authority itself.
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
        demihead_arbitration_receipt: Optional[Dict[str, Any]] = None,
        public_content: bool = False,
    ) -> Dict[str, Any]:
        receipt = super().cycle(
            trigger_text=trigger_text,
            source_ref=source_ref,
            intent_id=intent_id,
            session_id=session_id,
            intent_authority=intent_authority,
            demihead_decision=demihead_decision,
            demihead_arbitration_receipt=demihead_arbitration_receipt,
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
        receipt["demihead_arbitration_receipt_forwarded"] = demihead_arbitration_receipt is not None
        return receipt


__all__ = ["AdvancingSpiralDialogueEngine", "AuraPeerAdapter"]
