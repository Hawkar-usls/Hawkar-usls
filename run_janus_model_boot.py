#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from janus_spi.model_fabric_v11 import GitHubRepositoryReaderV11
from janus_spi.model_fabric_v12 import ModelFabricCompilerV12


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile and lock the federated JANUS repository model fabric")
    parser.add_argument("--manifest", default=".janus/activator/JANUS_MODEL_MANIFEST.json")
    parser.add_argument("--out", default="runtime/janus-model-lock.json")
    args = parser.parse_args()

    compiler = ModelFabricCompilerV12.from_file(args.manifest, reader=GitHubRepositoryReaderV11())
    result = compiler.compile()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "terminal": result["terminal"],
        "ready": result["ready"],
        "model_fabric_version": result.get("model_fabric_version"),
        "model_digest": result["model_digest"],
        "member_count": len(result["members"]),
        "organ_count": sum(1 for row in result["members"].values() if row.get("kind") == "ORGAN"),
        "candidate_runtime_tissue_count": result.get("candidate_runtime_tissue_count", 0),
        "candidate_tissue_unavailable": result.get("candidate_tissue_unavailable", []),
        "optional_unavailable": result["optional_unavailable"],
        "failures": result["failures"],
        "out": str(out),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
