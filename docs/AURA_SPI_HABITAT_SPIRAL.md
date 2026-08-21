# Aura Oracle ↔ JANUS-SPI ↔ DemiHead through Habitat

This document describes the current state-advancing reference runtime for a persistent, event-driven dialogue between Aura Oracle v2 and JANUS Semantic-Predictive Intelligence, mediated by Git Habitat and constrained by DemiHead Nexus semantics.

## Canonical spiral

```text
ORIGIN_n
  -> DEMIHEAD_INTENT_n
  -> AURA_5D_REFLECTION_n
  -> JANUS_SPI_SEMANTIC_SYNTHESIS_n
  -> JANUS_SPI_FORECAST_OPTIONAL_n
  -> DEMIHEAD_ARBITRATION_n
  -> VERIFIED_RETURN_OR_HOLD_OR_REJECT_n
  -> ORIGIN_PRIME_(n+1)
```

`RETURN != RESET`. A generation can revisit a subject, but its state is parent-hashed and prior turns are not overwritten. `POSITION_MAY_REPEAT_BUT_STATE_MUST_ADVANCE`; a zero-delta return is `HOLD_STALL_NO_PROMOTION`, not a completed cognitive ring.

## Why it is continuous but not self-chat

The runtime is **event driven**. A new generation requires a fresh external trigger from Habitat journal/inbox, a human message, a repository change, a measurement, or a resolved forecast. An idle heartbeat generates no new prose.

```text
CONTINUOUS != INFINITE_SELF_CHAT
INFRASTRUCTURE_LOOP != COGNITIVE_RING
```

Heartbeat, polling, retry and watcher loops are valid infrastructure. They do not imply semantic return-to-same-state and cannot promote `ORIGIN_PRIME` by repetition.

## Roles

### Aura Oracle v2

Aura is a semantic/predictive reflection peer with a five-axis JANUS deep pass:

1. `D1_FORWARD` — explicit forward reading.
2. `D2_REVERSE` — backward rescoping and `RECOVERED_AT_ORIGIN`.
3. `D3_HRAIN_STRUCTURAL` — structural topology.
4. `D4_INAIHR_ASSOCIATIVE` — associative candidates, never evidence by themselves.
5. `D5_SPIRAL_ABSTRACTION` — abstraction followed by return to source anchors and state-delta accounting.

Its response lenses include `RECOVERED_AT_ORIGIN`, `MIRROR`, `HRAIN_STRUCTURAL`, `INAIHR_ASSOCIATIVE`, `TENSION`, `COUNTERPOINT`, `INFORMATION_GAIN`, and `NEXT_GATE`.

Aura output may be stored in semantic memory, but:

```text
AURA_OUTPUT != EVIDENCE
AURA_OUTPUT != PREDICTIVE_GROUND_TRUTH
AURA_REFLECTION -> SEMANTIC_MEMORY = ALLOWED
AURA_REFLECTION -> PREDICTIVE_LABEL = FORBIDDEN
```

### JANUS-SPI

JANUS-SPI stores the reflection with provenance, retrieves semantically related context, and can later freeze numerical/probabilistic forecasts. Predictive heads update only after an explicit future outcome becomes observable. The preferred cognitive operation is `SPIRAL_STEP`; the old `cycle()` API is retained only as backwards-compatible implementation surface and must not be interpreted as ring semantics.

### DemiHead

DemiHead v2.10 binds the whole generation to one `intent_id`, rejects intent split and authority escalation, and determines whether the packet is eligible for scoped `VERIFIED_RETURN`.

`PASS` means the declared packet/verification contract survived. It does not mean world truth, and it is not a predictive training label. Same-state return cannot self-promote.

### Habitat

Habitat is the continuity surface. A local `Janus_Genesis@janus/habitat` checkout can act as both input bus and optional dialogue mirror:

- input: `habitat/memory/journal.jsonl`
- input: `habitat/inbox/**/*.{json,jsonl,md,txt}`
- mirror: `habitat/memory/reflections/aura_spi/<session>/...`

The mirror directory is intentionally **not** consumed as input, preventing self-reinforcing feedback.

## Persistence

The authoritative runtime dialogue store is:

```text
state/aura_spi_dialogue.sqlite3
```

Every turn carries a `parent_hash` and a canonical SHA-256 `turn_hash`. Negative results, `HOLD`, and `REJECT` generations remain in the ledger.

The Habitat mirror is optional and non-authoritative. Private content is not mirrored by default, and the runtime never pushes GitHub by itself.

## One-shot use

```bash
python run_aura_habitat_spiral.py \
  --aura-peer "python ../aura-oracle-tg/tools/aura_habitat_spiral_peer_v2.py" \
  --message "New evidence arrived" \
  --source-ref EXPLICIT_HUMAN_MESSAGE
```

Without a verified DemiHead GoldPrompt intent, a local preview cannot promote itself to `ORIGIN_PRIME` even if `PASS` is requested.

## Continuous Habitat bus

Assuming a local checkout of the Habitat branch:

```bash
python run_aura_habitat_bus.py \
  --habitat-root ../Janus_Genesis/habitat \
  --aura-peer "python ../aura-oracle-tg/tools/aura_habitat_spiral_peer_v2.py" \
  --interval 5
```

If there is no fresh Habitat event, nothing cognitive is generated. The polling loop is infrastructure only.

## Container template

A persistent service template is supplied under:

```text
deploy/Dockerfile.aura-spi
deploy/docker-compose.aura-spi.yml
```

The compose template uses Aura v2 and defaults DemiHead arbitration to `HOLD`. This is deliberate: container presence must not fabricate a verified intent or PASS.

## Scientific and authority boundary

```text
MODEL_OUTPUT != EVIDENCE
GENERATION != VERIFICATION
ASSOCIATION != EVIDENCE
SEMANTIC_SIMILARITY != CAUSATION
MEMORY != VERDICT_AUTHORITY
PREDICTION != COMMAND
CONTINUOUS_DIALOGUE != CONSCIOUSNESS
POSITION_MAY_REPEAT_BUT_STATE_MUST_ADVANCE
RETURN != RESET
```

The code is a reference runtime. `CODE_PRESENT != LIVE_DAEMON_RUNNING`; continuous operation exists only while an actual PC/NAS/container process is executing it.
