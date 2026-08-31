from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.slime_memory import JanusActivatorSlimeMemoryR0


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS Activator Slime Memory R0 finalized-receipt learner")
    parser.add_argument("--receipt-file", required=True, help="Finalized verified route-outcome receipt JSON")
    parser.add_argument("--state-dir", default="state/activator/slime_memory")
    args = parser.parse_args()

    receipt = json.loads(Path(args.receipt_file).read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise SystemExit("SLIME_FINALIZED_RECEIPT_JSON_OBJECT_REQUIRED")
    memory = JanusActivatorSlimeMemoryR0(args.state_dir)
    result = memory.learn_from_finalized_receipt(receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
