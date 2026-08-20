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
    """

    def __init__(self, habitat_root: str | Path, state_path: str | Path) -> None:
        self.root = Path(habitat_root)
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        return {"journal_lines": 0, "inbox_hashes": {}}

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _journal_events(self) -> List[Dict[str, Any]]:
        path = self.root / "memory" / "journal.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = int(self.state.get("journal_lines", 0))
        events: List[Dict[str, Any]] = []
        for idx in range(start, len(lines)):
            raw = lines[idx].strip()
            if not raw:
                continue
            try:
                value = json.loads(raw)
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except json.JSONDecodeError:
                text = raw
            events.append({
                "text": text,
                "source_ref": f"HABITAT_JOURNAL_LINE:{idx + 1}",
                "public_content": False,
            })
        self.state["journal_lines"] = len(lines)
        return events

    def _inbox_events(self) -> List[Dict[str, Any]]:
        root = self.root / "inbox"
        if not root.exists():
            return []
        previous = dict(self.state.get("inbox_hashes", {}))
        current: Dict[str, str] = {}
        events: List[Dict[str, Any]] = []
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(self.root).as_posix()
            data = path.read_bytes()
            digest = self._hash(data)
            current[rel] = digest
            if previous.get(rel) == digest:
                continue
            if path.suffix.lower() not in {".json", ".jsonl", ".md", ".txt"}:
                continue
            text = data.decode("utf-8", errors="replace")
            events.append({
                "text": text,
                "source_ref": f"HABITAT_INBOX:{rel}#{digest}",
                "public_content": False,
            })
        self.state["inbox_hashes"] = current
        return events

    def poll(self) -> List[Dict[str, Any]]:
        events = self._journal_events() + self._inbox_events()
        self._save_state()
        return events
