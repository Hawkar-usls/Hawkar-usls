from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


class HabitatEventBus:
    """Read fresh events from a local checkout of Janus_Genesis/habitat.

    The bus is read-only with respect to inbox/journal sources. Dialogue output is
    handled separately by HabitatMirror, preventing the mirror directory from
    becoming its own input and creating a feedback loop.

    On first start, existing Habitat history is treated as baseline by default.
    Set replay_existing=True only for an explicit historical replay.

    Performance invariant: normal polls are incremental. The journal is consumed from
    a byte cursor and unchanged inbox files are skipped by stat metadata before any
    hashing/read. This prevents Habitat cost from growing linearly with total history.
    """

    SUPPORTED_INBOX_SUFFIXES = {".json", ".jsonl", ".md", ".txt"}

    def __init__(
        self,
        habitat_root: str | Path,
        state_path: str | Path,
        *,
        replay_existing: bool = False,
        max_inbox_bytes: int = 1_048_576,
    ) -> None:
        self.root = Path(habitat_root)
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_inbox_bytes = max(1, int(max_inbox_bytes))
        existed = self.state_path.exists()
        self._state_valid = True
        self.state = self._load_state()

        # A corrupt state file must never silently replay all historical Habitat input.
        # Treat current content as a fresh baseline unless replay was explicitly asked.
        if (not existed or not self._state_valid) and not replay_existing:
            self._bootstrap_current_boundary()
            self._save_state()

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "journal_lines": 0,
            "journal_offset_bytes": 0,
            "journal_file_identity": "",
            "inbox_files": {},
            "bootstrapped": False,
            "last_rejections": [],
        }

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self._state_valid = False
            return self._default_state()
        if not isinstance(value, dict):
            self._state_valid = False
            return self._default_state()
        return value

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _identity(path: Path) -> str:
        stat = path.stat()
        return f"{int(stat.st_dev)}:{int(stat.st_ino)}"

    @staticmethod
    def _stat_record(path: Path, *, digest: str | None = None) -> Dict[str, Any]:
        stat = path.stat()
        return {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns),
            "sha256": digest,
        }

    @staticmethod
    def _same_stat(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
        return all(previous.get(key) == current.get(key) for key in ("size", "mtime_ns", "ctime_ns"))

    def _snapshot_inbox(self) -> Dict[str, Dict[str, Any]]:
        root = self.root / "inbox"
        if not root.exists():
            return {}
        current: Dict[str, Dict[str, Any]] = {}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if path.suffix.lower() not in self.SUPPORTED_INBOX_SUFFIXES:
                continue
            rel = path.relative_to(self.root).as_posix()
            stat = path.stat()
            if stat.st_size > self.max_inbox_bytes:
                current[rel] = self._stat_record(path)
                continue
            data = path.read_bytes()
            current[rel] = self._stat_record(path, digest=self._hash(data))
        return current

    def _bootstrap_current_boundary(self) -> None:
        journal = self.root / "memory" / "journal.jsonl"
        if journal.exists():
            with journal.open("rb") as handle:
                journal_lines = sum(1 for _ in handle)
            journal_offset = journal.stat().st_size
            journal_identity = self._identity(journal)
        else:
            journal_lines = 0
            journal_offset = 0
            journal_identity = ""
        self.state = {
            "journal_lines": journal_lines,
            "journal_offset_bytes": journal_offset,
            "journal_file_identity": journal_identity,
            "inbox_files": self._snapshot_inbox(),
            "bootstrapped": True,
            "bootstrap_rule": "EXISTING_HISTORY_IS_BASELINE_NOT_FRESH_TRIGGER",
            "last_rejections": [],
        }

    def _save_state(self) -> None:
        text = json.dumps(self.state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.state_path)

    def _ensure_journal_cursor(self, path: Path) -> None:
        if "journal_offset_bytes" in self.state:
            return

        # One-time migration from the old line-count-only state format. It may scan
        # historical lines once, but all subsequent polls use the byte cursor.
        target_lines = max(0, int(self.state.get("journal_lines", 0)))
        line_count = 0
        offset = 0
        if path.exists():
            with path.open("rb") as handle:
                while line_count < target_lines:
                    line = handle.readline()
                    if not line:
                        break
                    line_count += 1
                offset = handle.tell()
            if target_lines > line_count:
                offset = path.stat().st_size
        self.state["journal_lines"] = line_count
        self.state["journal_offset_bytes"] = offset
        self.state["journal_file_identity"] = self._identity(path) if path.exists() else ""

    def _reset_journal_to_baseline(self, path: Path) -> None:
        if not path.exists():
            self.state["journal_lines"] = 0
            self.state["journal_offset_bytes"] = 0
            self.state["journal_file_identity"] = ""
            return
        with path.open("rb") as handle:
            lines = sum(1 for _ in handle)
        self.state["journal_lines"] = lines
        self.state["journal_offset_bytes"] = path.stat().st_size
        self.state["journal_file_identity"] = self._identity(path)

    def _journal_events(self) -> List[Dict[str, Any]]:
        path = self.root / "memory" / "journal.jsonl"
        self._ensure_journal_cursor(path)
        if not path.exists():
            self._reset_journal_to_baseline(path)
            return []

        stat = path.stat()
        identity = self._identity(path)
        previous_identity = str(self.state.get("journal_file_identity", ""))
        offset = max(0, int(self.state.get("journal_offset_bytes", 0)))

        if (previous_identity and previous_identity != identity) or stat.st_size < offset:
            # Replacement/truncation becomes a new baseline. Never replay old-looking
            # lines merely because the cursor became invalid.
            self._reset_journal_to_baseline(path)
            return []
        if stat.st_size <= offset:
            self.state["journal_file_identity"] = identity
            return []

        with path.open("rb") as handle:
            handle.seek(offset)
            appended = handle.read()

        # JSONL writers can briefly expose an incomplete tail. Consume only complete
        # newline-terminated records and leave the tail for the next poll.
        last_newline = appended.rfind(b"\n")
        if last_newline < 0:
            return []
        complete = appended[: last_newline + 1]
        new_offset = offset + last_newline + 1
        lines = complete.decode("utf-8", errors="replace").splitlines()

        line_number = max(0, int(self.state.get("journal_lines", 0)))
        events: List[Dict[str, Any]] = []
        for raw_line in lines:
            line_number += 1
            raw = raw_line.strip()
            if not raw:
                continue
            try:
                value = json.loads(raw)
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except json.JSONDecodeError:
                text = raw
            events.append({
                "text": text,
                "source_ref": f"HABITAT_JOURNAL_LINE:{line_number}",
                "public_content": False,
            })

        self.state["journal_lines"] = line_number
        self.state["journal_offset_bytes"] = new_offset
        self.state["journal_file_identity"] = identity
        return events

    def _inbox_events(self) -> List[Dict[str, Any]]:
        root = self.root / "inbox"
        if not root.exists():
            self.state["inbox_files"] = {}
            self.state.pop("inbox_hashes", None)
            return []

        previous_records = self.state.get("inbox_files")
        if not isinstance(previous_records, dict):
            previous_records = {}
        legacy_hashes = self.state.get("inbox_hashes")
        if not isinstance(legacy_hashes, dict):
            legacy_hashes = {}

        current: Dict[str, Dict[str, Any]] = {}
        events: List[Dict[str, Any]] = []
        rejections: List[Dict[str, Any]] = []

        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if path.suffix.lower() not in self.SUPPORTED_INBOX_SUFFIXES:
                continue
            rel = path.relative_to(self.root).as_posix()
            stat_only = self._stat_record(path)
            previous = previous_records.get(rel)

            if isinstance(previous, dict) and self._same_stat(previous, stat_only):
                current[rel] = previous
                continue

            if stat_only["size"] > self.max_inbox_bytes:
                current[rel] = stat_only
                rejections.append({
                    "source_ref": f"HABITAT_INBOX:{rel}",
                    "reason": "INBOX_FILE_EXCEEDS_MAX_BYTES",
                    "size": stat_only["size"],
                    "max_inbox_bytes": self.max_inbox_bytes,
                })
                continue

            data = path.read_bytes()
            digest = self._hash(data)
            record = self._stat_record(path, digest=digest)
            current[rel] = record

            previous_digest = previous.get("sha256") if isinstance(previous, dict) else legacy_hashes.get(rel)
            if previous_digest == digest:
                continue

            text = data.decode("utf-8", errors="replace")
            events.append({
                "text": text,
                "source_ref": f"HABITAT_INBOX:{rel}#{digest}",
                "public_content": False,
            })

        self.state["inbox_files"] = current
        self.state.pop("inbox_hashes", None)
        self.state["last_rejections"] = rejections
        return events

    def poll(self) -> List[Dict[str, Any]]:
        events = self._journal_events() + self._inbox_events()
        self.state["bootstrapped"] = True
        self._save_state()
        return events
