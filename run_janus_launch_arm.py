#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from janus_spi.launch_arm_ledger import arm_status, consume_arm


def load(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("JSON_OBJECT_REQUIRED")
    return value


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--arm", required=True)
    s.add_argument("--state-dir", required=True)
    s.add_argument("--out")
    c = sub.add_parser("consume")
    c.add_argument("--arm", required=True)
    c.add_argument("--state-dir", required=True)
    c.add_argument("--result", required=True)
    c.add_argument("--out")
    args = p.parse_args()
    arm = load(args.arm)
    if args.cmd == "status":
        row = arm_status(arm, state_dir=args.state_dir)
    else:
        row = consume_arm(arm, state_dir=args.state_dir, launch_result=load(args.result))
    text = json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
