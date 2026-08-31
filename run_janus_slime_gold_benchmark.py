from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.slime_gold_benchmark import run_frozen_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen JANUS Gold-vs-Ideal Slime Activator benchmark")
    parser.add_argument(
        "--spec",
        default=".janus/activator/SLIME_GOLD_VS_IDEAL_FROZEN_BENCH_V1.json",
    )
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    report = run_frozen_benchmark(args.spec)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_pass and report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
