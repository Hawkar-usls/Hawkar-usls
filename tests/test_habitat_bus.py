from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from janus_spi.habitat_bus import HabitatEventBus


def test_explicit_replay_reads_existing_journal_and_inbox_once(tmp_path: Path):
    habitat = tmp_path / "habitat"
    (habitat / "memory").mkdir(parents=True)
    (habitat / "inbox").mkdir(parents=True)
    (habitat / "memory" / "reflections" / "aura_spi").mkdir(parents=True)
    (habitat / "memory" / "journal.jsonl").write_text('{"event":"wake"}\n', encoding="utf-8")
    (habitat / "inbox" / "letter.txt").write_text("fresh question", encoding="utf-8")
    (habitat / "memory" / "reflections" / "aura_spi" / "self.txt").write_text("must never be input", encoding="utf-8")

    bus = HabitatEventBus(habitat, tmp_path / "state.json", replay_existing=True)
    first = bus.poll()
    assert len(first) == 2
    assert any(item["source_ref"].startswith("HABITAT_JOURNAL_LINE") for item in first)
    assert any(item["source_ref"].startswith("HABITAT_INBOX") for item in first)
    assert all("must never be input" not in item["text"] for item in first)
    assert bus.poll() == []


def test_default_bootstrap_treats_existing_history_as_baseline(tmp_path: Path):
    habitat = tmp_path / "habitat"
    (habitat / "memory").mkdir(parents=True)
    (habitat / "inbox").mkdir(parents=True)
    journal = habitat / "memory" / "journal.jsonl"
    inbox = habitat / "inbox" / "event.json"
    journal.write_text('{"old":1}\n', encoding="utf-8")
    inbox.write_text('{"v":1}', encoding="utf-8")

    bus = HabitatEventBus(habitat, tmp_path / "state.json")
    assert bus.poll() == []

    with journal.open("a", encoding="utf-8") as handle:
        handle.write('{"new":2}\n')
    inbox.write_text('{"v":2}', encoding="utf-8")
    events = bus.poll()
    assert len(events) == 2


def test_changed_inbox_file_is_new_external_trigger_after_bootstrap(tmp_path: Path):
    habitat = tmp_path / "habitat"
    (habitat / "inbox").mkdir(parents=True)
    target = habitat / "inbox" / "event.json"
    target.write_text('{"v":1}', encoding="utf-8")
    bus = HabitatEventBus(habitat, tmp_path / "state.json")
    assert bus.poll() == []
    target.write_text('{"v":2}', encoding="utf-8")
    assert len(bus.poll()) == 1
    assert bus.poll() == []
