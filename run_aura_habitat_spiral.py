from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.advancing_spiral import AdvancingSpiralDialogueEngine, AuraPeerAdapter


def process(engine: AdvancingSpiralDialogueEngine, item: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return engine.spiral_step(
        trigger_text=str(item["text"]),
        source_ref=str(item.get("source_ref", "LOCAL_INBOX")),
        intent_id=item.get("intent_id"),
        session_id=item.get("session_id"),
        intent_authority=str(item.get("intent_authority", args.intent_authority)),
        demihead_decision=str(item.get("demihead_decision", args.demihead_decision)).upper(),
        public_content=bool(item.get("public_content", args.public_content)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Aura Oracle <-> JANUS-SPI <-> DemiHead Habitat state-advancing spiral runtime")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--habitat-root", default=None, help="Local Janus_Genesis/habitat checkout; no Git push is performed")
    parser.add_argument("--aura-peer", default=None, help="Command reading one JSON packet on stdin and writing Aura reflection JSON on stdout")
    parser.add_argument("--message", default=None)
    parser.add_argument("--source-ref", default="EXPLICIT_HUMAN_MESSAGE")
    parser.add_argument("--intent-id", default=None)
    parser.add_argument("--intent-authority", default="LOCAL_PREVIEW", choices=["LOCAL_PREVIEW", "DEMIHEAD_GOLDPROMPT_VERIFIED"])
    parser.add_argument("--demihead-decision", default="HOLD", choices=["PASS", "HOLD", "REJECT"])
    parser.add_argument("--public-content", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--inbox", default="state/aura_spi_inbox.jsonl")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    command = shlex.split(args.aura_peer) if args.aura_peer else None
    engine = AdvancingSpiralDialogueEngine(
        state_dir=args.state_dir,
        habitat_root=args.habitat_root,
        aura_peer=AuraPeerAdapter(command),
    )

    if args.message:
        item = {
            "text": args.message,
            "source_ref": args.source_ref,
            "intent_id": args.intent_id,
            "intent_authority": args.intent_authority,
            "demihead_decision": args.demihead_decision,
            "public_content": args.public_content,
        }
        print(json.dumps(process(engine, item, args), ensure_ascii=False, indent=2))
        if not args.daemon:
            return

    if not args.daemon:
        raise SystemExit("Provide --message for one-shot mode or --daemon for event-driven continuous mode")

    inbox = Path(args.inbox)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.touch(exist_ok=True)
    offset_path = Path(args.state_dir) / "aura_spi_inbox.offset"
    offset = int(offset_path.read_text().strip()) if offset_path.exists() and offset_path.read_text().strip() else 0

    print(json.dumps({
        "type": "AURA_SPI_SPIRAL_DAEMON",
        "status": "RUNNING_LOCAL_PROCESS",
        "inbox": str(inbox),
        "idle_behavior": "SILENT_NO_SELF_CHAT",
        "operation": "SPIRAL_STEP",
        "position_may_repeat_state_must_advance": True,
        "return_is_reset": False,
        "rule": "CONTINUOUS != INFINITE_SELF_CHAT",
    }, ensure_ascii=False))

    while True:
        lines = inbox.read_text(encoding="utf-8").splitlines()
        while offset < len(lines):
            raw = lines[offset].strip()
            offset += 1
            offset_path.write_text(str(offset), encoding="utf-8")
            if not raw:
                continue
            try:
                item = json.loads(raw)
                if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                    raise ValueError("INBOX_EVENT_REQUIRES_NONEMPTY_TEXT")
                receipt = process(engine, item, args)
                print(json.dumps(receipt, ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({"type": "AURA_SPI_EVENT_REJECT", "error": str(exc), "offset": offset}, ensure_ascii=False), file=sys.stderr)
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    main()
