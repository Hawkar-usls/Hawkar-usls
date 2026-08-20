# Aura Oracle ↔ JANUS-SPI ↔ DemiHead through Habitat

This document describes the v1 reference runtime for a persistent, event-driven dialogue between Aura Oracle and JANUS Semantic-Predictive Intelligence, mediated by Git Habitat and constrained by DemiHead Nexus semantics.

## Canonical spiral

```text
ORIGIN_n
  -> DEMIHEAD_INTENT_n
  -> AURA_REFLECTION_n
  -> JANUS_SPI_SEMANTIC_SYNTHESIS_n
  -> JANUS_SPI_FORECAST_OPTIONAL_n
  -> DEMIHEAD_ARBITRATION_n
  -> VERIFIED_RETURN_OR_REJECT_n
  -> ORIGIN_PRIME_(n+1)
```

`RETURN != RESET`. A generation can revisit a subject, but its state is parent-hashed and prior turns are not overwritten.

## Why it is continuous but not self-chat

The runtime is **event driven**. A new generation requires a fresh external trigger from Habitat journal/inbox, a human message, a repository change, a measurement, or a resolved forecast. An idle heartbeat generates no new prose.

```text
CONTINUOUS != INFINITE_SELF_CHAT
```

This prevents Aura and JANUS-SPI from repeatedly training their own assumptions into a closed feedback loop.

## Roles

### Aura Oracle

Aura is a symbolic reflection peer. Its generic peer returns four lenses:

1. `MIRROR` — what structure repeats if names are removed?
2. `TENSION` — what attractive interpretation could fail?
3. `COUNTERPOINT` — what would the opposite model predict?
4. `NEXT_GATE` — what observation would discriminate the models?

Aura output may be stored in semantic memory, but:

```text
AURA_OUTPUT != EVIDENCE
AURA_OUTPUT != PREDICTIVE_GROUND_TRUTH
AURA_REFLECTION -> SEMANTIC_MEMORY = ALLOWED
AURA_REFLECTION -> PREDICTIVE_LABEL = FORBIDDEN
```

### JANUS-SPI

JANUS-SPI stores the reflection with provenance, retrieves semantically related evidence, and can later freeze numerical/probabilistic forecasts. Predictive heads update only after an explicit future outcome becomes observable.

### DemiHead

DemiHead v2.10 binds the whole generation to one `intent_id`, rejects intent split and authority escalation, and determines whether the packet is eligible for scoped `VERIFIED_RETURN`.

`PASS` means the declared packet/verification contract survived. It does not mean world truth, and it is not a predictive training label.

### Habitat

Habitat is the continuity surface. A local `Janus_Genesis@janus/habitat` checkout can act as both input bus and optional dialogue mirror:

- input: `habitat/memory/journal.jsonl`
- input: `habitat/inbox/**/*.{json,jsonl,md,txt}`
- mirror: `habitat/memory/reflections/aura_spi/<session>/...`

The mirror directory is intentionally **not** consumed as input, preventing a feedback loop.

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
  --aura-peer "python ../aura-oracle-tg/tools/aura_habitat_spiral_peer_v1.py" \
  --message "New evidence arrived" \
  --source-ref EXPLICIT_HUMAN_MESSAGE
```

Without a verified DemiHead GoldPrompt intent, a local preview cannot promote itself to `ORIGIN_PRIME` even if `PASS` is requested.

## Continuous Habitat bus

Assuming a local checkout of the Habitat branch:

```bash
python run_aura_habitat_bus.py \
  --habitat-root ../Janus_Genesis/habitat \
  --aura-peer "python ../aura-oracle-tg/tools/aura_habitat_spiral_peer_v1.py" \
  --interval 5
```

If there is no fresh Habitat event, nothing is generated.

## Container template

A persistent service template is supplied under:

```text
deploy/Dockerfile.aura-spi
deploy/docker-compose.aura-spi.yml
```

The compose template defaults DemiHead arbitration to `HOLD`. This is deliberate: container presence must not fabricate a verified intent or PASS.

## Scientific and authority boundary

```text
MODEL_OUTPUT != EVIDENCE
GENERATION != VERIFICATION
ASSOCIATION != EVIDENCE
SEMANTIC_SIMILARITY != CAUSATION
MEMORY != VERDICT_AUTHORITY
PREDICTION != COMMAND
CONTINUOUS_DIALOGUE != CONSCIOUSNESS
```

The code is a reference runtime. `CODE_PRESENT != LIVE_DAEMON_RUNNING`; continuous operation exists only while an actual PC/NAS/container process is executing it.
