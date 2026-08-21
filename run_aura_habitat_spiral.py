from __future__ import annotations

import argparse
import json
import os
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


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _file_identity(path: Path) -> str:
    stat = path.stat()
    return f"{int(stat.st_dev)}:{int(stat.st_ino)}"


def _load_cursor(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"offset_bytes": 0, "file_identity": ""}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {"offset_bytes": 0, "file_identity": "", "recovered_from_invalid_cursor": True}
    if not isinstance(value, dict):
        return {"offset_bytes": 0, "file_identity": "", "recovered_from_invalid_cursor": True}
    return value


def _incremental_records(inbox: Path, cursor: dict[str, Any], max_chunk_bytes: int = 4 * 1024 * 1024):
    """Yield newline-terminated inbox records without rereading historical content.

    Replacement or truncation becomes a new baseline rather than replaying stale-looking
    input as a fresh trigger. Partial final records remain pending until a newline arrives.
    """
    stat = inbox.stat()
    identity = _file_identity(inbox)
    previous_identity = str(cursor.get("file_identity") or "")
    offset = max(0, int(cursor.get("offset_bytes") or 0))

    if (previous_identity and previous_identity != identity) or stat.st_size < offset:
        cursor["offset_bytes"] = stat.st_size
        cursor["file_identity"] = identity
        cursor["reset_to_new_baseline"] = True
        return

    if stat.st_size <= offset:
        cursor["file_identity"] = identity
        return

    with inbox.open("rb") as handle:
        handle.seek(offset)
        while True:
            start = handle.tell()
            chunk = handle.read(max(1, int(max_chunk_bytes)))
            if not chunk:
                break
            last_newline = chunk.rfind(b"\n")
            if last_newline < 0:
                # Do not advance over an incomplete record. A very large line therefore
                # remains pending instead of being silently truncated into a command.
                break
            complete = chunk[: last_newline + 1]
            consumed = 0
            for raw in complete.splitlines(keepends=True):
                consumed += len(raw)
                yield start + consumed, raw.rstrip(b"\r\n")
            handle.seek(start + last_newline + 1)

    cursor["file_identity"] = identity


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
    parser.add_argument("--max-inbox-chunk-bytes", type=int, default=4 * 1024 * 1024)
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
    cursor_path = Path(args.state_dir) / "aura_spi_inbox.cursor.json"
    cursor = _load_cursor(cursor_path)

    print(json.dumps({
        "type": "AURA_SPI_SPIRAL_DAEMON",
        "status": "RUNNING_LOCAL_PROCESS",
        "inbox": str(inbox),
        "idle_behavior": "SILENT_NO_SELF_CHAT",
        "operation": "SPIRAL_STEP",
        "position_may_repeat_state_must_advance": True,
        "return_is_reset": False,
        "inbox_polling": "INCREMENTAL_BYTE_CURSOR",
        "rule": "CONTINUOUS != INFINITE_SELF_CHAT",
    }, ensure_ascii=False))

    while True:
        processed_any = False
        for next_offset, raw_bytes in _incremental_records(inbox, cursor, args.max_inbox_chunk_bytes) or ():
            processed_any = True
            raw = raw_bytes.decode("utf-8", errors="replace").strip()
            cursor["offset_bytes"] = int(next_offset)
            _atomic_json_write(cursor_path, cursor)
            if not raw:
                continue
            try:
                item = json.loads(raw)
                if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                    raise ValueError("INBOX_EVENT_REQUIRES_NONEMPTY_TEXT")
                receipt = process(engine, item, args)
                print(json.dumps(receipt, ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({
                    "type": "AURA_SPI_EVENT_REJECT",
                    "error": str(exc),
                    "offset_bytes": int(next_offset),
                }, ensure_ascii=False), file=sys.stderr)

        if not processed_any:
            _atomic_json_write(cursor_path, cursor)
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    main()
