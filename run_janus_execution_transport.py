from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.execution_transport import JanusExecutionTransportBroker


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME bounded execution-grant transport")
    parser.add_argument("--grant", required=True)
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--token-env", default="JANUS_DEMIURGE_DISPATCH_TOKEN")
    parser.add_argument("--output")
    parser.add_argument("--require-submitted", action="store_true")
    args = parser.parse_args()

    grant = json.loads(Path(args.grant).read_text(encoding="utf-8"))
    if not isinstance(grant, dict):
        raise SystemExit("EXECUTION_GRANT_JSON_OBJECT_REQUIRED")
    receipt = JanusExecutionTransportBroker(state_dir=args.state_dir).send(
        grant,
        token=os.environ.get(args.token_env, ""),
    )
    text = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_submitted and receipt.get("terminal") != "EXECUTION_TRANSPORT_SENT_AWAITING_RESULT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
