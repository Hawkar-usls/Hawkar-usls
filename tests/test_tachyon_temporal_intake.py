"""JANUS-SPI must never turn Tachyon R1 records into automatic gradients."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Only the dedicated GitHub Actions job checks out the immutable Tachyon source.
sys.path.insert(0, str(ROOT / "external" / "tachyon"))
from janus_spi.tachyon_temporal_intake import intake, IntakeHold
try:
    from tachyon.temporal_evidence import SCHEMA, seal, digest
except ImportError:
    SCHEMA, seal, digest = None, None, None

SRC = dict(repository="Hawkar-usls/Janus-Demiurge",commit_sha="a"*40,
           path="experiments/ocean_transformer/x.json",content_sha256="b"*64,
           source_family_id="OCEAN-009B-20261112",evidence_class="SYNTHETIC_CONTROL")
TS = dict(observed_at=None,available_at="2026-11-11T08:02:00Z",
          feature_cutoff_at="2026-11-11T07:50:00Z",forecast_frozen_at="2026-11-11T08:00:00Z",
          target_at="2026-11-12T08:00:00Z",resolved_at=None)

def fixture(kind="FORECAST", family="OCEAN-009B-20261112"):
    t=dict(TS)
    v=dict(probability_1=.49,observed_label=None,description="synthetic test only")
    if kind=="FEATURE":
        t.update(observed_at="2026-11-11T07:30:00Z",available_at="2026-11-11T07:40:00Z")
        v["probability_1"]=None
    elif kind=="RESOLUTION":
        t.update(observed_at="2026-11-12T08:01:00Z",available_at="2026-11-12T08:02:00Z",
                 resolved_at="2026-11-12T08:04:00Z")
        v.update(probability_1=None,observed_label=1)
    src=dict(SRC,source_family_id=family)
    c=dict(provenance_checked_externally=False,training_permitted=False,
           automatic_deployment=False,scientific_claim_promoted=False,
           forecast_link_sha256="c"*64 if kind=="RESOLUTION" else None)
    return seal(dict(schema=SCHEMA,record_id="R1-"+kind,target_id="TARGET001",
                     kind=kind,source=src,times=t,value=v,controls=c))

@unittest.skipUnless(SCHEMA is not None, "Pinned Tachyon verifier absent; dedicated R1 workflow checks it out")
class TemporalIntakeTests(unittest.TestCase):
    def test_three_phase_context_without_training(self):
        r=intake([fixture("FEATURE"),fixture(),fixture("RESOLUTION")])
        self.assertEqual(r["count"],3)
        self.assertFalse(r["may_train_model"])
        self.assertFalse(r["may_append_to_production_sqlite"])
        self.assertFalse(r["source_independence_proven"])

    def test_unverified_source_never_authenticated(self):
        r=intake([fixture()])
        self.assertFalse(r["records"][0]["measurement_source_authenticated"])

    def test_same_family_duplicate_is_not_two_independent_trials(self):
        with self.assertRaisesRegex(IntakeHold,"DUPLICATE_FAMILY"):
            intake([fixture(),fixture()])

    def test_same_family_different_record_types_remain_distinct(self):
        r=intake([fixture(),fixture("FEATURE")])
        self.assertEqual(r["count"],2)

    def test_edited_forecast_rejected_even_with_source_hash_intact(self):
        x=fixture();x["value"]["probability_1"]=0.01
        with self.assertRaisesRegex(IntakeHold,"TACHYON_REJECTED"):
            intake([x])

    def test_late_feature_rejected_even_if_hash_resigned(self):
        x=fixture("FEATURE");x["times"]["available_at"]="2026-11-12T10:00:00Z"
        x["content_sha256"]=digest({k:v for k,v in x.items() if k!="content_sha256"})
        with self.assertRaisesRegex(IntakeHold,"TACHYON_REJECTED"):
            intake([x])

    def test_unbounded_batch_rejected(self):
        with self.assertRaisesRegex(IntakeHold,"RECORD_BATCH_UNBOUNDED"):
            intake([fixture()]*65)

    def test_late_label_is_never_an_admitted_gradient(self):
        r=intake([fixture("RESOLUTION")])
        self.assertFalse(r["may_train_model"])
        self.assertFalse(r["records"][0]["label_training_admitted"])

if __name__=="__main__":
    unittest.main()
