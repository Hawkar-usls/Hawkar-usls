from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.local_lineage import HardenedJanusAckReconciler


STRUCTURAL_SUCCESS_TERMINALS = {
    "ACK_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
    "ACK_REJECTION_STRUCTURALLY_BOUND_SOURCE_UNVERIFIED_NO_EXECUTION",
    "ACK_ALREADY_STRUCTURALLY_RECONCILED",
}


def load_object(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS Activator offline ACK structural reconciliation")
    parser.add_argument("--packet", required=True, help="Sealed dispatch packet JSON")
    parser.add_argument("--transport-receipt", required=True, help="Sealed v0.4 transport receipt JSON")
    parser.add_argument("--ack", required=True, help="Receiver ACK JSON")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--output", help="Optional reconciliation receipt output path")
    parser.add_argument(
        "--require-structural-bound",
        action="store_true",
        help="Exit non-zero unless ACK is structurally bound or already structurally reconciled",
    )
    args = parser.parse_args()

    reconciler = HardenedJanusAckReconciler(state_dir=args.state_dir)
    receipt = reconciler.reconcile(
        load_object(args.packet),
        load_object(args.transport_receipt),
        load_object(args.ack),
    )
    text = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")

    if args.require_structural_bound and receipt.get("terminal") not in STRUCTURAL_SUCCESS_TERMINALS:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
