<div align="center">

# Hawkar
### JANUS Semantic-Predictive Intelligence · Research · Reproducible Systems · Embedded Engineering

[![JANUS-SPI](https://img.shields.io/badge/JANUS--SPI-semantic%20%2B%20predictive-8250df)](spec/JANUS_SEMANTIC_PREDICTIVE_INTELLIGENCE-v1.0.json)
[![Portfolio](https://img.shields.io/badge/portfolio-machine--readable-2f81f7)](https://github.com/Hawkar-usls/Janus/blob/main/portfolio-index.json)
[![Review](https://img.shields.io/badge/external%20review-welcome-2ea043)](https://github.com/Hawkar-usls/Janus-Fundamentum/issues/173)
[![Claims](https://img.shields.io/badge/claims-scoped%20to%20evidence-6e7681)](https://github.com/Hawkar-usls/Janus/blob/main/public-metadata-coverage.json)

`observe → freeze → predict → resolve → learn` · `proof before promotion` · `negative results stay visible`

</div>

I build inspectable research and engineering systems with explicit claim boundaries, machine-readable artifacts, reproducible checks, and preserved negative results.

## JANUS Semantic-Predictive Intelligence

This repository is now the **home/cognitive gateway** for `JANUS-SPI`: a semantic and predictive AI layer intended to learn from time-ordered evidence across the JANUS repository constellation and Habitat.

The target is not an oracle. The target is a system that can:

- ingest current evidence into provenance-aware semantic memory;
- find hidden semantic relations without treating similarity as causation;
- freeze explicit future targets before their outcomes exist;
- emit numerical forecasts or probabilities;
- score forecasts after the future becomes observable;
- learn incrementally from resolved outcomes;
- preserve wrong predictions, uncertainty, `UNKNOWN`, and `REJECT`;
- carry verified experience forward through an `ORIGIN_PRIME` continual-learning cycle.

Canonical loop:

```text
OBSERVE
  -> SEMANTIC_LINK
  -> DEFINE_FUTURE_TARGET
  -> FREEZE
  -> PREDICT
  -> WAIT_FOR_CAUSAL_OUTCOME
  -> SCORE
  -> ATTACK
  -> LEARN
  -> VERIFIED_RETURN_OR_REJECT
  -> ORIGIN_PRIME
```

Scientific and authority boundaries:

```text
PREDICTION != TRUTH
CORRELATION != CAUSATION
SEMANTIC_SIMILARITY != SCIENTIFIC_VERDICT
PREDICTION != COMMAND
MEMORY != VERDICT_AUTHORITY
MYTHOLOGY != PHYSICS
```

### Current implementation

The v1 scaffold includes:

- persistent SQLite event / forecast / resolution ledger;
- local semantic memory with deterministic hashing-vector retrieval;
- online binary probability learning with `SGDClassifier.partial_fit`;
- online numeric forecasting with `SGDRegressor.partial_fit`;
- future-target freeze and post-target scoring;
- read-only GitHub constellation observer;
- `Janus_Genesis@janus/habitat` continuity source;
- a real-time repository-activity future-learning sanity benchmark;
- tests and CI.

Install and run one read pass:

```bash
python -m pip install -r requirements.txt
python run_janus_spi.py poll
```

Run the continuous read-only learning loop:

```bash
python run_janus_realtime.py --interval 300
```

For authenticated GitHub reads, provide `GITHUB_TOKEN` through the environment. JANUS-SPI does not intentionally persist it.

**Important:** committing the runtime does not mean a long-running process is currently active. `LIVE_REAL_TIME_LEARNING` requires an executing PC/NAS/cloud runner.

→ **[Architecture](docs/JANUS_SPI_ARCHITECTURE.md)**  
→ **[Machine-readable specification](spec/JANUS_SEMANTIC_PREDICTIVE_INTELLIGENCE-v1.0.json)**  
→ **[Repository constellation](config/constellation.json)**

### JANUS Horizon — Hawking continuation domain

The first flagship scientific domain is black-hole learning: gravitational-wave observations, Event Horizon Telescope products, simulations, and scope-limited physics constraints feed the same forecast-and-verification machinery.

The creative project identity `Hawkar / Son of Osiris / Bird-Headed Man` is retained as narrative continuity only. It has no scientific verdict authority.

```text
BLACK_HOLE_CONNECTED_AI
= OBSERVATION
+ SIMULATION
+ PHYSICS_CONSTRAINTS
+ BLIND_VALIDATION
+ CONTINUAL_VERIFIED_LEARNING
```

Hawking radiation is treated as theory / analogue-laboratory training context unless and until direct astrophysical evidence exists. Model agreement is never promoted automatically into new black-hole physics.

## Start here

### [Janus-Fundamentum](https://github.com/Hawkar-usls/Janus-Fundamentum) — mathematics & proof-carrying verification
Finite-field subspace arrangements, endpoint compression, and computational-complexity proof search.

**Current boundary:** A3 is frozen for external mathematical review. `P vs NP` remains open. World novelty and independent replication are not established. → [Review gate #173](https://github.com/Hawkar-usls/Janus-Fundamentum/issues/173)

### [AIFC](https://github.com/Hawkar-usls/AIFC) — auditable experimental protocol
Pre-target commitments, causal ordering, entropy evidence, replay, statistics, and fail-closed verification.

**Current boundary:** internal assurance is not external validation. The next meaningful gates are an independently authored Implementation B and an external public-randomness bench. → [Validation gate #66](https://github.com/Hawkar-usls/AIFC/issues/66)

### [janus-io-public](https://github.com/Hawkar-usls/janus-io-public) — systems measurement
Controlled Proof-of-Work measurement, work accounting, and admission-wave experiments.

**Current boundary:** the published wave-segmentation behavior is documented in the tested setup. Energy savings, profitability, SHA-256 predictability, and hardware-life extension are not established.

### [janus-distributed-ai-swarm](https://github.com/Hawkar-usls/janus-distributed-ai-swarm) — embedded systems
ESP32/M5Stack firmware, telemetry, protocol boundaries, observer semantics, and recovery behavior.

**Current boundary:** this is an embedded/distributed engineering project. It does not claim AGI, precognition, or mining superiority.

## Creative technology

### [Janus_Genesis](https://github.com/Hawkar-usls/Janus_Genesis)
A local-first interactive world / AI-assisted game with portable saves, optional local models, and character-agency rules.

Its moral, mythological, and theological vocabulary belongs to the fictional system and is separate from the evidence-bearing research tracks above.

## Repository maturity

Public repositories are explicitly classified as **Featured**, **Active Prototype**, **Work in Progress**, **Legacy**, **Archive**, or **Upstream-derived**. An unfinished project should say so on its first screen rather than look accidentally abandoned or complete.

→ **[Human-readable Repository Catalog](https://github.com/Hawkar-usls/Janus/blob/main/docs/REPOSITORY_CATALOG.md)**  
→ **[Machine-readable maturity & visibility catalog](https://github.com/Hawkar-usls/Janus/blob/main/portfolio-visibility.json)**

## Review rules

- **CI shows that software checks ran; it is not peer review.**
- **A verifier checks a stated contract; it does not establish world novelty.**
- **Finite machine evidence is not automatically an asymptotic theorem.**
- **Negative, null, obstruction, and fail-closed outcomes remain visible.**
- **Historical metaphors are not promoted into physical claims.**
- **Upstream-derived repositories are marked explicitly; base-code authorship is not claimed.**

## External review wanted

Counterexamples, prior art, clean-room implementations, independent replication, and verifier defects are especially useful. Additional internal PASS layers are not treated as substitutes for external validation.

## Machine-readable entry points

- **[JANUS-SPI specification](spec/JANUS_SEMANTIC_PREDICTIVE_INTELLIGENCE-v1.0.json)** — semantic/predictive AI contract, repository constellation, learning law and claim boundaries.
- **[Public portfolio index](https://github.com/Hawkar-usls/Janus/blob/main/portfolio-index.json)** — repository classification, preferred review order, and claim boundaries.
- **[Repository maturity & visibility](https://github.com/Hawkar-usls/Janus/blob/main/portfolio-visibility.json)** — featured/WIP/legacy/archive/upstream recommendations.
- **[Metadata coverage audit](https://github.com/Hawkar-usls/Janus/blob/main/public-metadata-coverage.json)** — public metadata coverage and intentional exceptions.
- **[Schema registry](https://github.com/Hawkar-usls/Janus/blob/main/schemas/registry.json)** — stable `schema_id` → JSON Schema / vocabulary mapping.
- **[Presentation standard](https://github.com/Hawkar-usls/Janus/blob/main/docs/PUBLIC_REPOSITORY_PRESENTATION_STANDARD.md)** — academic/minimalist README and claim-boundary rules.

The presentation standard is MIT-inspired academic minimalism only; **no affiliation with MIT is implied**. Schema validity describes metadata structure; it does **not** establish scientific truth, novelty, replication, or peer review.

---

<div align="center">

**Oleksandr Ahapov (Hawkar)** · Ukraine

</div>
