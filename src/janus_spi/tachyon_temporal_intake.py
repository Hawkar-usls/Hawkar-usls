"""JANUS-SPI R1: read-only candidate intake for Tachyon temporal evidence.

Requires the pinned Tachyon verifier to be importable. No SQLite mutation, no
online fit, no permission to promote source claims or training labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "janus.spi.tachyon_temporal_intake.v1"
MAX_RECORDS = 64
MAX_BYTES = 2_000_000

class IntakeHold(ValueError):
    pass

def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def intake(records, *, verifier=None):
    if verifier is None:
        try:
            from tachyon.temporal_evidence import validate as verifier
        except ImportError as exc:
            raise IntakeHold("PINNED_TACHYON_VERIFIER_REQUIRED") from exc
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise IntakeHold("RECORD_BATCH_UNBOUNDED")
    accepted = []
    seen = set()
    for n, record in enumerate(records):
        try:
            vetted = verifier(record)
        except (ValueError, TypeError, KeyError) as exc:
            raise IntakeHold(f"TACHYON_REJECTED_RECORD_{n}:{type(exc).__name__}") from exc
        if (vetted.get("status") != "STRUCTURAL_TIME_ORDER_PASS"
                or vetted.get("source_bytes_authenticated") is not False
                or vetted.get("outcome_admitted_for_training") is not False
                or vetted.get("scientific_claim_promoted") is not False
                or vetted.get("authority_delta") != 0):
            raise IntakeHold("VERIFIER_AUTHORITY_RESULT_UNEXPECTED")
        key = (record["source"]["source_family_id"], record["target_id"], record["kind"])
        if key in seen:
            raise IntakeHold("DUPLICATE_FAMILY_TARGET_KIND_NOT_INDEPENDENT")
        seen.add(key)
        accepted.append({
            "record_id": record["record_id"],
            "source_reference": record["source"]["repository"] + "@" + record["source"]["commit_sha"] + ":" + record["source"]["path"],
            "source_family_id": record["source"]["source_family_id"],
            "target_id": record["target_id"],
            "kind": record["kind"],
            "source_content_sha256_asserted": record["source"]["content_sha256"],
            "record_sha256": vetted["record_sha256"],
            "temporal_status": vetted["status"],
            "measurement_source_authenticated": False,
            "label_training_admitted": False,
        })
    result = {
        "schema": SCHEMA, "status": "VERIFIED_STRUCTURE_ONLY_RESEARCH_SHADOW",
        "count": len(accepted), "records": accepted,
        "source_independence_proven": False,
        "record_provenance_is_authentication": False,
        "may_append_to_production_sqlite": False,
        "may_train_model": False, "may_change_forecast": False,
        "may_deploy_model": False, "scientific_claim_promoted": False,
        "authority_delta": 0,
    }
    result["receipt_sha256"] = hashlib.sha256(canonical(result)).hexdigest()
    return result

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    raw = a.records.read_bytes()
    if len(raw) > MAX_BYTES:
        raise IntakeHold("SOURCE_TOO_LARGE")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise IntakeHold("DUPLICATE_JSON_KEY")
            obj[key] = value
        return obj
    incoming = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(IntakeHold("NAN_FORBIDDEN")))
    result = intake(incoming)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print(json.dumps({"count": result["count"], "status": result["status"],
                      "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
