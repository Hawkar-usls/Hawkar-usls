from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.dispatch import JanusDispatchBroker


def selected_targets(receipt: dict) -> list[str]:
    targets: list[str] = []
    for route in receipt.get("routes_selected") or []:
        if not isinstance(route, dict):
            continue
        for organ in route.get("organs") or []:
            text = str(organ).strip()
            if text and text not in targets:
                targets.append(text)
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME bounded internal dispatch broker")
    parser.add_argument("--activation-receipt", required=True, help="Sealed Activator receipt JSON file")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--target", action="append", default=[], help="Specific selected organ; may be repeated")
    args = parser.parse_args()

    receipt = json.loads(Path(args.activation_receipt).read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise SystemExit("ACTIVATION_RECEIPT_JSON_OBJECT_REQUIRED")

    targets = [str(x).strip() for x in args.target if str(x).strip()] or selected_targets(receipt)
    broker = JanusDispatchBroker(state_dir=args.state_dir)
    decisions = [broker.dispatch(receipt, target_organ=target) for target in targets]
    print(json.dumps({
        "schema": "janus.activator.dispatch_batch.v0.3",
        "activation_id": receipt.get("activation_id"),
        "targets_considered": targets,
        "decisions": decisions,
        "external_effect_authorized": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
