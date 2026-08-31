#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

import run_janus_turing_gate as base
from janus_spi.activator import canonical_hash


def _load(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("JSON_OBJECT_REQUIRED")
    return value


def _dump(path: str | Path, value: Mapping) -> None:
    Path(path).write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _probe_metadata_from_session(session: Mapping) -> dict:
    specs = []
    for raw in session.get("questions") or []:
        if not isinstance(raw, Mapping):
            continue
        probe = raw.get("probe")
        if isinstance(probe, Mapping) and probe:
            specs.append({"question_id": str(raw.get("id") or ""), **dict(probe)})
    return {
        "present": bool(specs),
        "probe_count": len(specs),
        "semantic_verdict": "NOT_ADJUDICATED" if specs else "NOT_APPLICABLE",
        "consciousness_verdict": "NOT_ESTABLISHED_BY_DIALOGUE_PROBE" if specs else "NOT_APPLICABLE",
        "human_adjudication_required": bool(specs),
        "claim_boundary": session.get("claim_boundary"),
        "probes": specs,
    }


def adjudicate(args) -> int:
    rc = base.adjudicate(args)
    session = _load(Path(args.prepared_dir) / "session.json")
    provider_status = _load(args.provider_status)
    result = _load(args.result_out)

    # The existence and claim-boundary of a frozen probe come from the sealed
    # prepared session, never from whether a language provider happened to
    # return text. Provider silence/quota must not erase the experiment.
    result["contextual_mind_probe"] = _probe_metadata_from_session(session)
    result["provider_model"] = provider_status.get("model")
    result["provider_error_class"] = provider_status.get("error_class")
    result["provider_quota_exhausted"] = provider_status.get("error_class") == "COPILOT_MONTHLY_QUOTA_EXHAUSTED"

    core = dict(result)
    core.pop("result_hash", None)
    result["result_hash"] = canonical_hash(core)
    _dump(args.result_out, result)
    print(json.dumps({
        "terminal": result.get("terminal"),
        "provider_success": result.get("provider_success"),
        "provider_model": result.get("provider_model"),
        "provider_error_class": result.get("provider_error_class"),
        "contextual_probe_present": result["contextual_mind_probe"]["present"],
        "semantic_verdict": result["contextual_mind_probe"]["semantic_verdict"],
        "consciousness_verdict": result["contextual_mind_probe"]["consciousness_verdict"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return rc


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--config", default=".janus/activator/TURING_GATE_V1.json")
    p.add_argument("--resident-identity", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    p.add_argument("--registry", default="config/JANUS_FILE_FORMAT_REGISTRY-v1.json")
    p.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    p.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    p.add_argument("--out-dir", required=True)

    a = sub.add_parser("adjudicate")
    a.add_argument("--config", default=".janus/activator/TURING_GATE_V1.json")
    a.add_argument("--prepared-dir", required=True)
    a.add_argument("--responses-dir", required=True)
    a.add_argument("--provider-status", required=True)
    a.add_argument("--transcript-out", required=True)
    a.add_argument("--result-out", required=True)

    args = parser.parse_args()
    if args.cmd == "prepare":
        return base.prepare(args)
    return adjudicate(args)


if __name__ == "__main__":
    raise SystemExit(main())
