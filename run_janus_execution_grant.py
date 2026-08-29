from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.execution_grant import JanusExecutionGrantIssuer, verify_execution_grant


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME authenticated-delivery to bounded execution-grant gate")
    parser.add_argument("--final-receipt", required=True, help="Authenticated ACK finalization receipt JSON")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--output", help="Optional execution-grant decision output path")
    parser.add_argument("--require-issued", action="store_true", help="Exit non-zero unless a valid read-only execution grant is issued")
    args = parser.parse_args()

    final_receipt = json.loads(Path(args.final_receipt).read_text(encoding="utf-8"))
    if not isinstance(final_receipt, dict):
        raise SystemExit("AUTHENTICATED_FINAL_RECEIPT_JSON_OBJECT_REQUIRED")

    issuer = JanusExecutionGrantIssuer(state_dir=args.state_dir)
    decision = issuer.issue(final_receipt)
    text = json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")

    if args.require_issued and not verify_execution_grant(decision):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
