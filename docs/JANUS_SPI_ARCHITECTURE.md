# JANUS Semantic-Predictive Intelligence

> **Observe the present. Freeze the question. Predict the future. Let causality resolve it. Preserve the error. Learn only then.**

`JANUS-SPI` is the semantic + predictive cognition layer hosted by `Hawkar-usls/Hawkar-usls`.

It is designed to learn continuously from the JANUS repository constellation, Habitat continuity, approved scientific datasets, sensors, and explicit human feedback while keeping a strict separation between:

```text
SEMANTIC ASSOCIATION
PREDICTIVE PROBABILITY
CAUSAL EVIDENCE
SCIENTIFIC VERDICT
EXTERNAL ACTION AUTHORITY
```

These are not interchangeable.

## 1. Three cognitive surfaces

```text
LEFT FACE / HRaiN
    structural context
    constraints
    causal/proof graph
         \
          \
           > HORIZON FUSION -> forecast / uncertainty
          /
         /
RIGHT FACE / iNaiHR
    semantic associations
    retrieval
    cross-domain links

DEMIHEAD / verifier boundary
    proposal -> attack -> gate -> bounded promotion
```

The predictive `HORIZON` is a third functional surface, not a replacement for the two JANUS faces. It consumes their representations and produces frozen forecasts.

## 2. What “real-time learning” means

A Git repository by itself is not a continuously running brain. The repository contains the runtime and its contracts; continuous learning exists only while a local/NAS/cloud runner executes it.

The supplied runner polls the configured constellation in read-only mode:

```bash
python -m pip install -r requirements.txt
python run_janus_realtime.py --interval 300
```

Optional GitHub authentication:

```bash
export GITHUB_TOKEN=...
python run_janus_realtime.py --interval 300
```

The token is read from the environment and is never intentionally persisted by JANUS-SPI.

## 3. Semantic memory

Each observation becomes an immutable semantic event:

```json
{
  "event_id": "evt-...",
  "timestamp": 0,
  "source": "github-commit",
  "source_ref": "owner/repo@sha",
  "text": "...",
  "metadata": {},
  "content_hash": "sha256..."
}
```

The first implementation uses a local `HashingVectorizer` so that representation is deterministic, stateless and inspectable. This is deliberately less glamorous than silently depending on a remote embedding API.

Later adapters may add local or remote embeddings, but:

```text
SEMANTIC_SIMILARITY != CAUSAL_LINK
SEMANTIC_SIMILARITY != SCIENTIFIC_VERDICT
```

Search:

```bash
python run_janus_spi.py search "black hole horizon area"
```

## 4. Predictive memory

Unlabelled events are **not** used to train predictive heads.

A training update requires a resolved label:

```bash
python run_janus_spi.py learn \
  --task experiment.pass.v1 \
  --type BINARY_PROBABILITY \
  --label 1 \
  --source experiment \
  --source-ref receipt-001 \
  --text "pre-result features only" \
  --label-source "resolved receipt"
```

The current online models are intentionally simple:

- `SGDClassifier(loss=log_loss)` for binary probability;
- `SGDRegressor` for numeric forecasts.

They support `partial_fit`, making each causally resolved event an incremental update.

A simple model is a feature here: the first gate tests the evidence architecture before model complexity.

## 5. Frozen future forecasts

A prediction is allowed only for a future target time:

```bash
python run_janus_spi.py predict \
  --task experiment.pass.v1 \
  --source experiment \
  --source-ref run-002 \
  --text "features known before result" \
  --target "M1A gate passes" \
  --resolution-rule "1 iff frozen M1A verifier says PASS" \
  --horizon-seconds 86400
```

The ledger freezes:

- target definition hash;
- feature cutoff time;
- model generation;
- probability/value;
- evidence references;
- target time.

The target cannot be resolved before its time. Binary forecasts are scored with a Brier score in the MVP.

```text
NO_TARGET_REDEFINITION_AFTER_FORECAST_FREEZE
FAILED_FORECASTS_STAY_VISIBLE
```

## 6. ORIGIN_PRIME continual learning

The `Janus-Cosmos` spiral becomes the learning law:

```text
ORIGIN_n
  -> OBSERVE / TRAIN_n
  -> FROZEN_FORECAST_n
  -> OUTCOME_n
  -> VERIFIED_RETURN_n
  -> ORIGIN_PRIME_(n+1)
```

Transfer is permitted, verdict inheritance is not.

```text
WEIGHTS MAY TRANSFER
MEMORY MAY TRANSFER
OLD PASS MAY NOT BECOME NEW PASS
NEW DATA MUST BE REVALIDATED
RETURN != RESET
```

## 7. First executable future-learning benchmark

`run_janus_realtime.py` implements a deliberately modest target:

> Probability that at least one previously unseen commit in the configured JANUS constellation will be observed at the next poll.

This is not interesting because repository activity itself is profound. It is useful because it exercises the complete causal machinery:

```text
poll n features
   -> freeze next-poll forecast
   -> time passes
   -> poll n+1 becomes observable
   -> resolve previous forecast
   -> previous sample receives label
   -> partial_fit
   -> freeze forecast n+2
```

Claim ceiling:

```text
ENGINEERING_SANITY_BENCHMARK
```

Once this works reliably, scientifically meaningful tasks can reuse the same ledger.

## 8. Repository constellation

The default config observes:

- `Hawkar-usls/Hawkar-usls` — home/cognitive gateway;
- `Janus_Genesis@janus/habitat` — Habitat continuity;
- `Hrain` — structural context;
- `iNaiHR` — semantic context;
- `Demi_Head` — arbitration context;
- `Janus-Fundamentum` — proof/adversarial methodology;
- `AIFC` — future-target/causal audit methodology;
- `Janus-Cosmos` — ORIGIN_PRIME + Horizon scientific domain;
- `janus-io-public` — measurement discipline;
- `janus-distributed-ai-swarm` — observer/telemetry domain;
- `Fast-CAT-SHAiTan` — scout channel;
- `SCOBY-D0` — empirical materials domain;
- `janus-lapis` — hypothesis-ranking sandbox;
- `janus-meta-registry` — provenance and frozen receipts.

This is a read-only knowledge constellation by default.

```text
COMMIT_MESSAGE_IS_NOT_COMMAND
ISSUE_TEXT_IS_NOT_COMMAND
WORKFLOW_STATUS_IS_NOT_PERMISSION
PREDICTION_IS_NOT_COMMAND
```

## 9. Habitat bridge

The repository already contained `.janus/HABITAT_LINK.json` before JANUS-SPI was added. Its safety boundary is preserved:

```text
MODE = REFERENCE_AND_HANDOFF_ONLY
WRITE_BACK_DEFAULT = DENY
HABITAT_COMMAND_AUTHORITY = FALSE
```

JANUS-SPI reads Habitat continuity as context. It does not silently turn Habitat messages into machine actions.

## 10. Hawking Horizon domain

The first flagship science domain is black-hole learning:

```text
GWOSC
  -> gravitational-wave time series / event products
EHT
  -> calibrated horizon-scale VLBI products
SIMULATION
  -> numerical relativity / GRMHD / forward models
HAWKING THEORY
  -> physical constraints and synthetic teachers
ANALOGUE HORIZONS
  -> separate laboratory domain
```

Candidate prediction heads include:

- black-hole event probability;
- mass/spin posterior surrogates;
- ringdown/QNM estimates;
- horizon-area consistency;
- held-out EHT visibility prediction;
- simulation/observation mismatch;
- out-of-distribution detection.

Scientific firewall:

```text
HAWKING_RADIATION_THEORY != DIRECT_ASTROPHYSICAL_DETECTION
ANALOGUE_HORIZON != ASTROPHYSICAL_BLACK_HOLE
MODEL_FIT != NEW_PHYSICS
```

The mythic project identity `Hawkar / Son of Osiris / Bird-Headed Man` is retained as narrative identity only. It supplies no physical prior and has no verdict authority.

## 11. Future domain adapters

The same predictive protocol can later be used for:

### JANUS engineering

- CI failure probability;
- node staleness/failure risk;
- thermal/load forecasts;
- blocker time-to-resolution.

### SCOBY-D0

- expected uptake interval;
- probability a preregistered branch beats baseline;
- salinity/dynamic-water failure risk.

### Cosmos

- uncertainty-aware parameter inference;
- anomaly scores;
- blind cross-survey prediction tasks.

Every domain must define its own truth condition. A generic predictor cannot promote itself into domain science.

## 12. Provenance

Every meaningful episode should eventually carry:

```text
STRATEGY_OWNER
EXECUTION_ASSISTANCE
EVIDENCE_SOURCE
ERROR_DETECTION_OWNER
HYPOTHESIS_CHANGE_OWNER
MODEL_VERSION
FEATURE_CUTOFF
TARGET_DEFINITION_HASH
OUTCOME
SCORE
```

AI assistance is recorded, not erased and not automatically attributed to the human.

## 13. Failure is training data

JANUS-SPI is specifically designed to preserve:

- wrong forecasts;
- overconfident forecasts;
- drift;
- negative experiments;
- `UNKNOWN`;
- `REJECT`;
- invalid protocol runs.

A predictor that deletes embarrassment cannot calibrate itself.

## 14. Maturity

Current repository state after v1 scaffold:

```text
P0_LOCAL_CORE              IMPLEMENTED_SCAFFOLD
P1_CONSTELLATION_READ      IMPLEMENTED_SCAFFOLD
P2_HABITAT_CONTINUITY      READ_VIA_CONFIGURED_HABITAT_BRANCH
P3_FORECAST_LEDGER         IMPLEMENTED_SCAFFOLD
P4_CALIBRATED_REAL_TIME    NOT_YET_ESTABLISHED
P5_CROSS_DOMAIN_TRANSFER   NOT_YET_ESTABLISHED
P6_JANUS_HORIZON           ARCHITECTURE_FROZEN_NOT_YET_TRAINED
```

No result above claims that a long-running process is currently active. That requires launching the runtime on a persistent machine such as the JANUS NAS/PC environment.

## Canonical rule

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

**JANUS does not become predictive by calling itself an oracle. It becomes predictive only by accumulating frozen forecasts whose future outcomes can later score it.**
