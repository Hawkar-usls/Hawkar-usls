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
        demihead_arbitration_receipt=item.get("demihead_arbitration_receipt"),
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


def _discard_to_record_boundary(handle: Any) -> tuple[int, bool]:
    """Discard the rest of an oversized JSONL record without interpreting fragments."""
    while True:
        chunk = handle.readline(64 * 1024)
        if not chunk:
            return handle.tell(), False
        if chunk.endswith(b"\n"):
            return handle.tell(), True


def _incremental_records(inbox: Path, cursor: dict[str, Any], max_record_bytes: int = 4 * 1024 * 1024):
    """Yield newline-terminated inbox records without rereading historical content.

    Replacement or truncation becomes a new baseline rather than replaying stale-looking
    input as a fresh trigger. A partial normal-sized tail waits for a newline. An oversized
    record is rejected as one unit and discarded through its boundary so it cannot pin the
    daemon forever or be interpreted later as command fragments.
    """
    stat = inbox.stat()
    identity = _file_identity(inbox)
    previous_identity = str(cursor.get("file_identity") or "")
    offset = max(0, int(cursor.get("offset_bytes") or 0))
    limit = max(1, int(max_record_bytes))

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
            raw = handle.readline(limit + 1)
            if not raw:
                break

            newline_terminated = raw.endswith(b"\n")
            payload_length = len(raw.rstrip(b"\r\n"))
            if payload_length > limit:
                if not newline_terminated:
                    end_offset, found_boundary = _discard_to_record_boundary(handle)
                else:
                    end_offset, found_boundary = handle.tell(), True
                cursor["offset_bytes"] = int(end_offset)
                cursor["last_rejection"] = {
                    "reason": "INBOX_RECORD_EXCEEDS_MAX_BYTES",
                    "start_offset_bytes": int(start),
                    "end_offset_bytes": int(end_offset),
                    "max_record_bytes": limit,
                    "newline_boundary_found": found_boundary,
                }
                continue

            if not newline_terminated:
                # Small incomplete tail: preserve it for the next poll instead of
                # interpreting an incomplete JSON command.
                handle.seek(start)
                break

            yield handle.tell(), raw.rstrip(b"\r\n")

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
    parser.add_argument(
        "--max-inbox-record-bytes",
        "--max-inbox-chunk-bytes",
        dest="max_inbox_record_bytes",
        type=int,
        default=4 * 1024 * 1024,
        help="Maximum accepted JSONL record size. The old --max-inbox-chunk-bytes name remains as a compatibility alias.",
    )
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
        "max_inbox_record_bytes": max(1, int(args.max_inbox_record_bytes)),
        "rule": "CONTINUOUS != INFINITE_SELF_CHAT",
    }, ensure_ascii=False))

    while True:
        processed_any = False
        for next_offset, raw_bytes in _incremental_records(inbox, cursor, args.max_inbox_record_bytes) or ():
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

        # Persist cursor changes caused by replacement/truncation or oversized record
        # rejection even when no valid event was yielded.
        if not processed_any:
            _atomic_json_write(cursor_path, cursor)
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    main()
