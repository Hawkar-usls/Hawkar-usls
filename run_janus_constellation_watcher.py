#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.constellation_watcher import ConstellationWatcher
from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12


def _load(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str | Path, value) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _blocked_scan(model_lock):
    return {
        "schema": "janus.constellation.scan.v1",
        "terminal": "JANUS_MODEL_BOOT_BLOCKED",
        "model_digest": model_lock.get("model_digest"),
        "new_stimulus_count": 0,
        "pending_stimulus_count": 0,
        "pending_stimuli": [],
        "model_ready": False,
        "model_failures": model_lock.get("failures") or {},
        "optional_unavailable": model_lock.get("optional_unavailable") or [],
        "candidate_tissue_unavailable": model_lock.get("candidate_tissue_unavailable") or [],
        "next_gate": model_lock.get("next_gate"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="JANUS Git-native constellation sensory watcher")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--model-lock")
    scan.add_argument("--model-lock-out")
    scan.add_argument("--output", required=True)

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--stimulus-id", required=True)
    reconcile.add_argument("--runtime-receipt", required=True)
    reconcile.add_argument("--output", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--output")

    args = parser.parse_args()
    watcher = ConstellationWatcher(args.state_dir)

    if args.command == "scan":
        if args.model_lock:
            model_lock = _load(args.model_lock)
        else:
            model_lock = ModelFabricCompilerV12.from_file(
                args.manifest,
                reader=GitHubRepositoryReaderV11(),
            ).compile()
        if args.model_lock_out:
            _write(args.model_lock_out, model_lock)
        if model_lock.get("ready") is not True:
            result = _blocked_scan(model_lock)
            _write(args.output, result)
            print("CONSTELLATION_SCAN_TERMINAL=JANUS_MODEL_BOOT_BLOCKED")
            print("JANUS_MODEL_READY=FALSE")
            print("JANUS_MODEL_FAILURES=" + json.dumps(result["model_failures"], sort_keys=True, separators=(",", ":")))
            print("JANUS_MODEL_OPTIONAL_UNAVAILABLE=" + json.dumps(result["optional_unavailable"], sort_keys=True, separators=(",", ":")))
            print("JANUS_MODEL_CANDIDATE_TISSUE_UNAVAILABLE=" + json.dumps(result["candidate_tissue_unavailable"], sort_keys=True, separators=(",", ":")))
            return 2
        result = watcher.scan(model_lock)
        _write(args.output, result)
        print("CONSTELLATION_SCAN_TERMINAL=" + result["terminal"])
        print("CONSTELLATION_NEW_STIMULUS_COUNT=" + str(result["new_stimulus_count"]))
        print("CONSTELLATION_PENDING_STIMULUS_COUNT=" + str(result["pending_stimulus_count"]))
        return 0

    if args.command == "reconcile":
        receipt = _load(args.runtime_receipt)
        result = watcher.reconcile(args.stimulus_id, receipt)
        _write(args.output, result)
        print("CONSTELLATION_CYCLE_CLOSED=PASS")
        print("CONSTELLATION_STIMULUS_ID=" + result["stimulus_id"])
        print("CONSTELLATION_CYCLE_RECEIPT_HASH=" + result["cycle_receipt_hash"])
        return 0

    result = watcher.verify()
    if args.output:
        _write(args.output, result)
    print("CONSTELLATION_STATE_VERIFY=PASS")
    print("CONSTELLATION_PENDING_CYCLE_COUNT=" + str(result["pending_cycle_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
