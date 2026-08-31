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


def main() -> int:
    parser = argparse.ArgumentParser(description="JANUS Git-native constellation sensory watcher")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--model-lock")
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
