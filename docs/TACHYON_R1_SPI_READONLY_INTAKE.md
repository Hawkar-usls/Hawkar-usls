# JANUS-SPI TACHYON-R1 read-only temporal evidence intake

JANUS-SPI remains the canonical semantic memory, forecast ledger and scoring/learning controller. Tachyon is a specialized external **physical-time research candidate**, not an alternate governor.

This additive Python module (src/janus_spi/tachyon_temporal_intake.py) requires the **exact source-pinned** Tachyon structural verifier under external/tachyon in the dedicated CI lane. It reads a bounded list of three-phase temporal records, passes each into the external cross-field time-order verifier, and produces a SHA-256-bound, read-only research receipt.

The SPI module does not call Ledger.append_event, Ledger.append_forecast, Ledger.resolve_forecast, sklearn partial_fit or a network request. It refuses duplicates of (source_family_id, target_id, kind), unverified model authority, future-feature leakage and tampering.

Recorded source hashes are asserted provenance, not a trusted independent timestamp or source-byte authentication. Source-independent scoring, calibration and cross-domain generalization remain future gates; these research-only receipts are not labels.

## Research smoke test

The workflow .github/workflows/tachyon-r1-spi-intake.yml pins a specific reviewed Demi_Head R1 source SHA, runs the 8 cross-repository anti-leakage/duplicate tests and validates a three-phase synthetic fixture batch. It emits a JSON artifact with may_train_model=false, may_append_to_production_sqlite=false, authority_delta=0. The job has read-only permissions and no schedule.

Nothing is merged or deployed automatically. The existing SPI SQLite schema, event loop, JANUS Ocean 009B precommit, source repository permissions, and TOPA/AIFC scientific verdict boundaries remain unchanged.

Use this interface only to assess candidates for **future** independently verified data ingestion, not to quietly train on retroactively published measurements.
