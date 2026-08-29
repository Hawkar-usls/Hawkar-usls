from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.transport import JanusTransportBroker


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME GitHub-internal Activator transport")
    parser.add_argument("--packet", required=True, help="Sealed dispatch packet JSON file")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--credential-env", default="JANUS_DEMIURGE_DISPATCH_TOKEN")
    parser.add_argument("--output", help="Optional transport receipt output path")
    parser.add_argument("--require-sent", action="store_true", help="Exit non-zero unless transport reaches SENT_AWAITING_ACK")
    args = parser.parse_args()

    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise SystemExit("DISPATCH_PACKET_JSON_OBJECT_REQUIRED")

    token = os.environ.get(args.credential_env, "")
    broker = JanusTransportBroker(state_dir=args.state_dir)
    receipt = broker.send(packet, token=token)
    text = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")

    if args.require_sent and receipt.get("terminal") != "TRANSPORT_SENT_AWAITING_ACK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
