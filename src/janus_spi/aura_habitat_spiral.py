from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .core import JanusSPICore, SemanticEvent

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TURN_SCHEMA = "janus.aura_spi.spiral_turn.v1"
AURA_PACKET_SCHEMA = "janus.aura_spi.spiral_event.v1"
AURA_REFLECTION_SCHEMA = "janus.aura_spi.aura_reflection.v1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def local_preview_intent(text: str, source_ref: str) -> str:
    """Create a stable preview intent id.

    This is useful for local prototyping only. A preview id is not a DemiHead
    GoldPrompt intent anchor and therefore cannot authorize VERIFIED_RETURN.
    """
    return sha256({"kind": "LOCAL_PREVIEW_INTENT", "text": text, "source_ref": source_ref})


@dataclass(frozen=True)
class SpiralTurn:
    schema: str
    turn_id: str
    session_id: str
    generation: int
    stage: str
    speaker: str
    recipient: str
    intent_id: str
    created_at: float
    text: str
    payload: Dict[str, Any]
    parent_hash: str
    turn_hash: str


class DialogueLedger:
    """Append-preserving, parent-hashed dialogue ledger."""

    def __init__(self, path: str | Path = "state/aura_spi_dialogue.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              created_at REAL NOT NULL,
              current_generation INTEGER NOT NULL,
              status TEXT NOT NULL,
              last_turn_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
              turn_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              generation INTEGER NOT NULL,
              stage TEXT NOT NULL,
              speaker TEXT NOT NULL,
              recipient TEXT NOT NULL,
              intent_id TEXT NOT NULL,
              created_at REAL NOT NULL,
              text TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              parent_hash TEXT NOT NULL,
              turn_hash TEXT NOT NULL UNIQUE,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session_generation
              ON turns(session_id, generation, created_at);
            """
        )
        self.db.commit()

    def ensure_session(self, session_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO sessions VALUES (?, ?, 0, 'OPEN', '')",
            (session_id, time.time()),
        )
        self.db.commit()

    def session_state(self, session_id: str) -> Dict[str, Any]:
        self.ensure_session(session_id)
        row = self.db.execute(
            "SELECT session_id,created_at,current_generation,status,last_turn_hash FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        assert row is not None
        return dict(zip(["session_id", "created_at", "current_generation", "status", "last_turn_hash"], row))

    def append(
        self,
        *,
        session_id: str,
        generation: int,
        stage: str,
        speaker: str,
        recipient: str,
        intent_id: str,
        text: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SpiralTurn:
        if HEX64.fullmatch(intent_id) is None:
            raise ValueError("INTENT_ID_MUST_BE_LOWERCASE_HEX64")
        state = self.session_state(session_id)
        created_at = time.time()
        parent_hash = str(state["last_turn_hash"] or "")
        core = {
            "schema": TURN_SCHEMA,
            "turn_id": f"turn-{uuid.uuid4().hex}",
            "session_id": session_id,
            "generation": int(generation),
            "stage": stage,
            "speaker": speaker,
            "recipient": recipient,
            "intent_id": intent_id,
            "created_at": created_at,
            "text": text,
            "payload": payload or {},
            "parent_hash": parent_hash,
        }
        turn_hash = sha256(core)
        turn = SpiralTurn(**core, turn_hash=turn_hash)
        self.db.execute(
            "INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn.turn_id, turn.session_id, turn.generation, turn.stage, turn.speaker,
                turn.recipient, turn.intent_id, turn.created_at, turn.text,
                json.dumps(turn.payload, ensure_ascii=False, sort_keys=True),
                turn.parent_hash, turn.turn_hash,
            ),
        )
        self.db.execute(
            "UPDATE sessions SET current_generation=?, last_turn_hash=? WHERE session_id=?",
            (int(generation), turn_hash, session_id),
        )
        self.db.commit()
        return turn

    def iter_turns(self, session_id: str) -> Iterable[SpiralTurn]:
        rows = self.db.execute(
            "SELECT turn_id,session_id,generation,stage,speaker,recipient,intent_id,created_at,text,payload_json,parent_hash,turn_hash "
            "FROM turns WHERE session_id=? ORDER BY created_at, turn_id",
            (session_id,),
        ).fetchall()
        for row in rows:
            yield SpiralTurn(
                schema=TURN_SCHEMA,
                turn_id=row[0], session_id=row[1], generation=row[2], stage=row[3],
                speaker=row[4], recipient=row[5], intent_id=row[6], created_at=row[7],
                text=row[8], payload=json.loads(row[9]), parent_hash=row[10], turn_hash=row[11],
            )

    def verify_chain(self, session_id: str) -> bool:
        parent = ""
        for turn in self.iter_turns(session_id):
            if turn.parent_hash != parent:
                return False
            core = asdict(turn)
            claimed = core.pop("turn_hash")
            if sha256(core) != claimed:
                return False
            parent = claimed
        return True

    def close_generation(self, session_id: str, generation: int, status: str) -> None:
        self.db.execute(
            "UPDATE sessions SET current_generation=?, status=? WHERE session_id=?",
            (generation, status, session_id),
        )
        self.db.commit()


class HabitatMirror:
    """Optional mirror into a local checkout of Janus_Genesis@janus/habitat.

    The mirror is not authoritative and never pushes to GitHub by itself.
    """

    def __init__(self, habitat_root: str | Path | None) -> None:
        self.root = Path(habitat_root) if habitat_root else None

    def write_turn(self, turn: SpiralTurn, *, public_content: bool = False) -> Optional[Path]:
        if self.root is None or not public_content:
            return None
        target_dir = self.root / "memory" / "reflections" / "aura_spi" / turn.session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"g{turn.generation:06d}-{turn.stage.lower()}-{turn.turn_hash[:16]}.json"
        target.write_text(json.dumps(asdict(turn), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        latest = target_dir / "LATEST.json"
        latest.write_text(json.dumps(asdict(turn), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target


class AuraPeerAdapter:
    """Subprocess adapter for the generic Aura spiral peer."""

    def __init__(self, command: Optional[list[str]] = None) -> None:
        self.command = command

    def reflect(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        if not self.command:
            return {
                "schema": AURA_REFLECTION_SCHEMA,
                "status": "AURA_UNAVAILABLE",
                "session_id": packet["session_id"],
                "generation": packet["generation"],
                "intent_id": packet["intent_id"],
                "reflection_text": "Aura peer is not configured; generation is held without synthetic substitution.",
                "cards": [],
                "predictive_label_authority": False,
                "scientific_evidence_authority": False,
                "may_train_semantic_memory": True,
                "may_train_predictive_head": False,
                "claim_ceiling": "AURA_UNAVAILABLE_NO_ORACLE_SUBSTITUTION",
            }
        proc = subprocess.run(
            self.command,
            input=json.dumps(packet, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"AURA_PEER_FAILED:{proc.stderr.strip()}")
        value = json.loads(proc.stdout)
        if value.get("schema") != AURA_REFLECTION_SCHEMA:
            raise ValueError("AURA_REFLECTION_SCHEMA_MISMATCH")
        if value.get("intent_id") != packet["intent_id"]:
            raise ValueError("AURA_INTENT_SPLIT_REJECT")
        if value.get("predictive_label_authority") is not False:
            raise ValueError("AURA_PREDICTIVE_LABEL_AUTHORITY_REJECT")
        if value.get("scientific_evidence_authority") is not False:
            raise ValueError("AURA_EVIDENCE_AUTHORITY_REJECT")
        return value


class SpiralDialogueEngine:
    """Event-driven Aura <-> JANUS-SPI spiral with DemiHead-compatible arbitration.

    It deliberately does not create new generations without fresh external input.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path = "state",
        habitat_root: str | Path | None = None,
        aura_peer: Optional[AuraPeerAdapter] = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.core = JanusSPICore(self.state_dir)
        self.dialogue = DialogueLedger(self.state_dir / "aura_spi_dialogue.sqlite3")
        self.mirror = HabitatMirror(habitat_root)
        self.aura = aura_peer or AuraPeerAdapter()

    def _append_and_mirror(self, *, public_content: bool, **kwargs: Any) -> SpiralTurn:
        turn = self.dialogue.append(**kwargs)
        self.mirror.write_turn(turn, public_content=public_content)
        return turn

    def cycle(
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
        if not trigger_text.strip():
            raise ValueError("FRESH_EXTERNAL_TRIGGER_REQUIRED")
        if demihead_decision not in {"PASS", "HOLD", "REJECT"}:
            raise ValueError("DEMIHEAD_DECISION_INVALID")
        session_id = session_id or f"spiral-{uuid.uuid4().hex[:16]}"
        if intent_id is None:
            intent_id = local_preview_intent(trigger_text, source_ref)
            intent_authority = "LOCAL_PREVIEW"
        if HEX64.fullmatch(intent_id) is None:
            raise ValueError("INTENT_ID_MUST_BE_LOWERCASE_HEX64")

        state = self.dialogue.session_state(session_id)
        generation = int(state["current_generation"]) + 1
        turns: list[SpiralTurn] = []

        turns.append(self._append_and_mirror(
            public_content=public_content, session_id=session_id, generation=generation,
            stage="ORIGIN", speaker="EXTERNAL_TRIGGER", recipient="DEMIHEAD",
            intent_id=intent_id, text=trigger_text,
            payload={"source_ref": source_ref, "fresh_external_trigger": True},
        ))
        turns.append(self._append_and_mirror(
            public_content=public_content, session_id=session_id, generation=generation,
            stage="DEMIHEAD_INTENT", speaker="DEMIHEAD", recipient="AURA_AND_JANUS_SPI",
            intent_id=intent_id, text="Preserve this intent across the complete spiral generation.",
            payload={"intent_authority": intent_authority, "authority_delta": 0},
        ))

        aura_packet = {
            "schema": AURA_PACKET_SCHEMA,
            "session_id": session_id,
            "generation": generation,
            "intent_id": intent_id,
            "source_ref": source_ref,
            "trigger_text": trigger_text,
            "constraints": {
                "symbolic_reflection_only": True,
                "prediction_authority": False,
                "evidence_authority": False,
                "may_not_replace_intent": True,
            },
        }
        aura = self.aura.reflect(aura_packet)
        aura_text = str(aura.get("reflection_text", ""))
        turns.append(self._append_and_mirror(
            public_content=public_content, session_id=session_id, generation=generation,
            stage="AURA_REFLECTION", speaker="AURA_ORACLE", recipient="JANUS_SPI",
            intent_id=intent_id, text=aura_text, payload=aura,
        ))
        self.core.observe(SemanticEvent.build(
            source="AURA_ORACLE",
            source_ref=f"{source_ref}#g{generation}",
            text=aura_text,
            metadata={
                "session_id": session_id,
                "generation": generation,
                "intent_id": intent_id,
                "predictive_label_authority": False,
                "scientific_evidence_authority": False,
            },
        ))

        retrieved = self.core.semantic_search(trigger_text, limit=5)
        evidence = [
            {
                "score": round(float(item["score"]), 6),
                "event_id": item["event"]["event_id"],
                "source": item["event"]["source"],
                "source_ref": item["event"]["source_ref"],
            }
            for item in retrieved
        ]
        synthesis_text = (
            f"Semantic synthesis for generation {generation}: {len(evidence)} retrieval references. "
            "Similarity is context, not causal evidence; Aura reflection remains proposal-only."
        )
        turns.append(self._append_and_mirror(
            public_content=public_content, session_id=session_id, generation=generation,
            stage="SPI_SEMANTIC_SYNTHESIS", speaker="JANUS_SPI", recipient="DEMIHEAD",
            intent_id=intent_id, text=synthesis_text,
            payload={
                "retrieval_refs": evidence,
                "semantic_similarity_is_evidence": False,
                "prediction_is_truth": False,
                "aura_is_predictive_label": False,
            },
        ))

        # A bare PASS parameter is never sufficient for promotion.  The active
        # positive path must consume a hash-valid DemiHead arbitration receipt.
        verified_eligible = False
        verified_return_payload: Optional[Dict[str, Any]] = None
        arbitration_sha256: Optional[str] = None
        effective_decision = "REJECT" if demihead_decision == "REJECT" else "HOLD"
        arbitration_payload: Dict[str, Any] = {
            "decision": effective_decision,
            "requested_legacy_decision": demihead_decision,
            "intent_authority": intent_authority,
            "verified_return_eligible": False,
            "external_effect_authorized": False,
            "authority_delta": 0,
            "source": "NO_DEMIHEAD_ARBITRATION_RECEIPT_FAIL_CLOSED",
        }
        if demihead_arbitration_receipt is not None:
            arb = dict(demihead_arbitration_receipt)
            if arb.get("schema") != "janus.aura_spi.demihead_arbitration.v1":
                raise ValueError("DEMIHEAD_ARBITRATION_SCHEMA_REJECT")
            if arb.get("session_id") != session_id:
                raise ValueError("DEMIHEAD_ARBITRATION_SESSION_SPLIT")
            if arb.get("generation") != generation:
                raise ValueError("DEMIHEAD_ARBITRATION_GENERATION_SPLIT")
            if arb.get("intent_id") != intent_id:
                raise ValueError("DEMIHEAD_ARBITRATION_INTENT_SPLIT")
            arbitration_sha256 = str(arb.get("arbitration_sha256") or "")
            unsigned = dict(arb)
            unsigned.pop("arbitration_sha256", None)
            unsigned.pop("verified_return", None)
            if HEX64.fullmatch(arbitration_sha256) is None or sha256(unsigned) != arbitration_sha256:
                raise ValueError("DEMIHEAD_ARBITRATION_HASH_MISMATCH")
            if arb.get("external_effect_authorized") is not False or arb.get("authority_delta") != 0:
                raise ValueError("DEMIHEAD_ARBITRATION_AUTHORITY_ESCALATION_REJECT")
            effective_decision = str(arb.get("decision") or "HOLD").upper()
            gate = arb.get("state_advance_gate") or {}
            verified_eligible = (
                effective_decision == "PASS"
                and arb.get("intent_authority") == "DEMIHEAD_GOLDPROMPT_VERIFIED"
                and intent_authority == "DEMIHEAD_GOLDPROMPT_VERIFIED"
                and arb.get("verified_return_eligible") is True
                and gate.get("candidate_valid") is True
            )
            if verified_eligible:
                vr = arb.get("verified_return")
                if not isinstance(vr, dict) or vr.get("schema") != "janus.aura_spi.verified_return.v1":
                    raise ValueError("VERIFIED_RETURN_RECEIPT_REQUIRED")
                if vr.get("session_id") != session_id or vr.get("generation") != generation or vr.get("intent_id") != intent_id:
                    raise ValueError("VERIFIED_RETURN_BINDING_SPLIT")
                origin_hash = str(vr.get("origin_state_hash") or "")
                candidate_hash = str(vr.get("candidate_state_hash") or "")
                delta_hash = str(vr.get("state_delta_sha256") or "")
                if any(HEX64.fullmatch(x) is None for x in (origin_hash, candidate_hash, delta_hash)):
                    raise ValueError("VERIFIED_RETURN_STATE_HASH_REQUIRED")
                if candidate_hash == origin_hash:
                    raise ValueError("ZERO_STATE_DELTA_HOLD")
                if vr.get("parent_origin_state_hash") != origin_hash:
                    raise ValueError("VERIFIED_RETURN_PARENT_HASH_MISMATCH")
                verified_return_payload = dict(vr)
            arbitration_payload = {
                "decision": effective_decision,
                "intent_authority": arb.get("intent_authority"),
                "verified_return_eligible": verified_eligible,
                "arbitration_sha256": arbitration_sha256,
                "state_advance_gate": gate,
                "external_effect_authorized": False,
                "authority_delta": 0,
                "source": "BOUND_DEMIHEAD_ARBITRATION_RECEIPT",
            }

        turns.append(self._append_and_mirror(
            public_content=public_content, session_id=session_id, generation=generation,
            stage="DEMIHEAD_ARBITRATION", speaker="DEMIHEAD", recipient="HABITAT",
            intent_id=intent_id,
            text=f"DemiHead arbitration: {effective_decision}.",
            payload=arbitration_payload,
        ))

        if verified_eligible:
            terminal = "VERIFIED_RETURN"
            turns.append(self._append_and_mirror(
                public_content=public_content, session_id=session_id, generation=generation,
                stage="VERIFIED_RETURN", speaker="DEMIHEAD", recipient="ORIGIN_PRIME",
                intent_id=intent_id,
                text="Generation survived the declared packet/intent gate; this is not world-truth authority.",
                payload={
                    **(verified_return_payload or {}),
                    "arbitration_sha256": arbitration_sha256,
                    "world_truth": False,
                    "predictive_training_label": False,
                },
            ))
            turns.append(self._append_and_mirror(
                public_content=public_content, session_id=session_id, generation=generation,
                stage="ORIGIN_PRIME", speaker="HABITAT", recipient="JANUS_SPI_AURA_DEMIHEAD",
                intent_id=intent_id,
                text=f"ORIGIN_PRIME_{generation + 1}: verified experience retained without verdict authority.",
                payload={
                    "state_advanced": True,
                    "return_is_reset": False,
                    "origin_state_hash": (verified_return_payload or {}).get("origin_state_hash"),
                    "state_delta_sha256": (verified_return_payload or {}).get("state_delta_sha256"),
                    "candidate_state_hash": (verified_return_payload or {}).get("candidate_state_hash"),
                    "arbitration_sha256": arbitration_sha256,
                    "promotion_source": "VERIFIED_DEMIHEAD_RECEIPT_ONLY",
                },
            ))
        else:
            terminal = "REJECT" if effective_decision == "REJECT" else "HOLD"
            turns.append(self._append_and_mirror(
                public_content=public_content, session_id=session_id, generation=generation,
                stage=terminal, speaker="DEMIHEAD", recipient="HABITAT",
                intent_id=intent_id,
                text=(
                    "Generation preserved without ORIGIN_PRIME promotion."
                    if terminal == "HOLD"
                    else "Generation rejected and preserved as a negative result."
                ),
                payload={"state_advanced": False, "negative_result_preserved": True},
            ))

        self.dialogue.close_generation(session_id, generation, terminal)
        return {
            "schema": "janus.aura_spi.spiral_step_receipt.v2",
            "session_id": session_id,
            "generation": generation,
            "intent_id": intent_id,
            "intent_authority": intent_authority,
            "terminal": terminal,
            "turn_hashes": [t.turn_hash for t in turns],
            "last_turn_hash": turns[-1].turn_hash,
            "chain_valid": self.dialogue.verify_chain(session_id),
            "predictive_model_updated": False,
            "fresh_external_trigger_consumed": True,
            "continuous_is_infinite_self_chat": False,
        }
