#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from janus_spi.file_fabric import FileFabricCompiler, GitHubTreeReader


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the exact-SHA JANUS polyglot file fabric")
    parser.add_argument("--model-lock", default="runtime/janus-model-lock.json")
    parser.add_argument("--registry", default="config/JANUS_FILE_FORMAT_REGISTRY-v1.json")
    parser.add_argument("--out", default="runtime/janus-file-fabric-lock.json")
    args = parser.parse_args()

    model_lock = json.loads(Path(args.model_lock).read_text(encoding="utf-8"))
    compiler = FileFabricCompiler.from_file(args.registry, reader=GitHubTreeReader())
    result = compiler.compile(model_lock)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "terminal": result["terminal"],
        "ready": result["ready"],
        "coverage_complete": result["coverage_complete"],
        "model_digest": result["model_digest"],
        "file_fabric_digest": result["file_fabric_digest"],
        "member_count": result["member_count"],
        "scanned_member_count": result["scanned_member_count"],
        "families": result["family_totals"],
        "bounded_unknown": result["bounded_unknown"],
        "required_failures": result["required_failures"],
        "out": str(out),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
