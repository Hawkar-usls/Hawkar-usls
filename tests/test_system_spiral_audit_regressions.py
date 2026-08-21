from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from janus_spi.advancing_spiral import AuraPeerAdapter
from janus_spi.core import JanusSPICore, SemanticEvent
from janus_spi.habitat_bus import HabitatEventBus
from janus_spi.realtime import RealtimeRepositoryActivityLoop


def test_corrupt_habitat_cursor_baselines_history_instead_of_replaying(tmp_path: Path):
    habitat = tmp_path / "habitat"
    (habitat / "memory").mkdir(parents=True)
    journal = habitat / "memory" / "journal.jsonl"
    journal.write_text('{"old":1}\n', encoding="utf-8")
    state = tmp_path / "bus-state.json"
    state.write_text("{broken", encoding="utf-8")

    bus = HabitatEventBus(habitat, state)
    assert bus.poll() == []

    with journal.open("a", encoding="utf-8") as handle:
        handle.write('{"new":2}\n')
    events = bus.poll()
    assert len(events) == 1
    assert '"new": 2' in events[0]["text"]


def test_habitat_partial_jsonl_tail_waits_for_newline(tmp_path: Path):
    habitat = tmp_path / "habitat"
    (habitat / "memory").mkdir(parents=True)
    journal = habitat / "memory" / "journal.jsonl"
    journal.write_text("", encoding="utf-8")
    bus = HabitatEventBus(habitat, tmp_path / "state.json", replay_existing=True)

    journal.write_text('{"event":"partial"}', encoding="utf-8")
    assert bus.poll() == []
    with journal.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    events = bus.poll()
    assert len(events) == 1
    assert events[0]["source_ref"] == "HABITAT_JOURNAL_LINE:1"


def test_habitat_oversize_inbox_is_rejected_without_becoming_trigger(tmp_path: Path):
    habitat = tmp_path / "habitat"
    (habitat / "inbox").mkdir(parents=True)
    bus = HabitatEventBus(habitat, tmp_path / "state.json", max_inbox_bytes=32)
    (habitat / "inbox" / "large.txt").write_text("x" * 128, encoding="utf-8")

    assert bus.poll() == []
    assert bus.state["last_rejections"]
    assert bus.state["last_rejections"][0]["reason"] == "INBOX_FILE_EXCEEDS_MAX_BYTES"


def test_semantic_cache_updates_incrementally_after_first_search(tmp_path: Path):
    core = JanusSPICore(tmp_path / "state")
    old = SemanticEvent.build("test", "old", "black hole horizon ringdown")
    new = SemanticEvent.build("test", "new", "cellulose marine oil sorbent")
    assert core.observe(old) is True
    assert core.semantic_search("horizon", limit=1)[0]["event"]["event_id"] == old.event_id

    assert core.observe(new) is True
    hit = core.semantic_search("cellulose sorbent", limit=1)[0]
    assert hit["event"]["event_id"] == new.event_id


def test_batch_observe_preserves_per_event_deduplication(tmp_path: Path):
    core = JanusSPICore(tmp_path / "state")
    a = SemanticEvent.build("test", "a", "alpha")
    b = SemanticEvent.build("test", "b", "beta")
    assert core.observe_many([a, b, a]) == [True, True, False]


class _FakeObserver:
    def __init__(self) -> None:
        self.calls = 0

    def poll_once(self, core: JanusSPICore):
        self.calls += 1
        return {"inserted": 0, "duplicates": 0, "repositories": 1, "unchanged_head_shortcuts": 1}


def test_realtime_fast_reentry_holds_without_poll_or_label(tmp_path: Path):
    core = JanusSPICore(tmp_path / "state")
    observer = _FakeObserver()
    state_path = tmp_path / "realtime.json"
    loop = RealtimeRepositoryActivityLoop(core, observer, state_path)

    first = loop.cycle(poll_seconds=60)
    assert first["status"] == "POLL_COMPLETED"
    assert observer.calls == 1

    second = loop.cycle(poll_seconds=60)
    assert second["status"] == "HOLD_TOO_EARLY_NO_LABEL_NO_POLL"
    assert observer.calls == 1
    assert second["learned_model_version"] is None

    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_cycle_at"] -= 61
    state_path.write_text(json.dumps(state), encoding="utf-8")
    third = loop.cycle(poll_seconds=60)
    assert third["status"] == "POLL_COMPLETED"
    assert observer.calls == 2
    assert third["prior_label_admitted"] is True
    assert third["learned_model_version"] is not None


def _aura_packet() -> dict:
    return {
        "session_id": "s",
        "generation": 1,
        "intent_id": "a" * 64,
        "trigger_text": "test",
    }


def test_hardened_aura_peer_times_out_fail_closed():
    peer = AuraPeerAdapter(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        timeout_seconds=0.05,
    )
    try:
        peer.reflect(_aura_packet())
    except TimeoutError as exc:
        assert "AURA_PEER_TIMEOUT" in str(exc)
    else:
        raise AssertionError("hung Aura peer must time out")


def test_hardened_aura_peer_rejects_oversized_output():
    peer = AuraPeerAdapter(
        [sys.executable, "-c", "print('x' * 4096)"],
        max_output_bytes=64,
    )
    try:
        peer.reflect(_aura_packet())
    except ValueError as exc:
        assert "AURA_PEER_OUTPUT_EXCEEDS_LIMIT" in str(exc)
    else:
        raise AssertionError("oversized Aura output must fail closed")
