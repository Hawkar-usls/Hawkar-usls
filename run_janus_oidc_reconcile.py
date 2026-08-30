from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from janus_spi.oidc_reconcile import BLOCKED_TERMINAL, reconcile_requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-dir", required=True)
    parser.add_argument("--output", default="runtime/oidc-reconcile/result.json")
    args = parser.parse_args()

    request_dir = Path(args.request_dir)
    rows = []
    if request_dir.is_dir():
        for path in sorted(request_dir.glob("*.oidc-packet.json")):
            rows.append(json.loads(path.read_text(encoding="utf-8")))

    result = reconcile_requests(rows)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    if result.get("terminal") == BLOCKED_TERMINAL:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
