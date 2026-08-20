from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .core import JanusSPICore, SemanticEvent
from .github_observer import GitHubObserver


class RealtimeRepositoryActivityLoop:
    """Small real future-prediction benchmark for the JANUS-SPI runtime.

    At poll n, the current repository state is frozen as features. At poll n+1, the
    observed label is whether at least one new constellation commit appeared. Only then
    is the previous sample admitted to online learning. The model may then forecast the
    next interval. This is an engineering sanity benchmark, not a scientific claim.
    """

    TASK_ID = "constellation.any_new_commit_next_poll.v1"

    def __init__(
        self,
        core: JanusSPICore,
        observer: GitHubObserver,
        state_path: str | Path = "state/realtime_repository_activity.json",
    ) -> None:
        self.core = core
        self.observer = observer
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save(self, state: Dict[str, Any]) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    @staticmethod
    def _event_to_json(event: SemanticEvent) -> Dict[str, Any]:
        return {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "source": event.source,
            "source_ref": event.source_ref,
            "text": event.text,
            "metadata": event.metadata,
            "content_hash": event.content_hash,
        }

    @staticmethod
    def _event_from_json(data: Dict[str, Any]) -> SemanticEvent:
        return SemanticEvent(**data)

    def cycle(self, poll_seconds: int = 300) -> Dict[str, Any]:
        previous = self._load()
        poll = self.observer.poll_once(self.core)
        now = time.time()
        inserted = int(poll.get("inserted", 0))

        if previous.get("forecast_id"):
            try:
                self.core.resolve(previous["forecast_id"], 1.0 if inserted > 0 else 0.0)
            except ValueError:
                # If a manual cycle is called too early, preserve the frozen forecast.
                pass

        learned_version: Optional[str] = None
        if previous.get("feature_event"):
            prior_event = self._event_from_json(previous["feature_event"])
            learned_version = self.core.learn(
                task_id=self.TASK_ID,
                task_type="BINARY_PROBABILITY",
                event=prior_event,
                label=1.0 if inserted > 0 else 0.0,
                provenance={
                    "STRATEGY_OWNER": "JANUS_SPI_PROTOCOL",
                    "EXECUTION_ASSISTANCE": "REALTIME_REPOSITORY_ACTIVITY_LOOP",
                    "EVIDENCE_SOURCE": "NEXT_GITHUB_POLL_OBSERVATION",
                    "SCIENTIFIC_AUTHORITY": False,
                },
                extra_features={"poll_seconds": poll_seconds},
            )

        summary_text = json.dumps(
            {
                "poll_time": now,
                "inserted_new_events": inserted,
                "duplicates": int(poll.get("duplicates", 0)),
                "repositories": int(poll.get("repositories", 0)),
                "per_repository_new_events": {
                    k.removeprefix("repo:"): v for k, v in poll.items() if k.startswith("repo:")
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        current_event = SemanticEvent.build(
            source="janus-spi-realtime-poll",
            source_ref=f"poll@{int(now)}",
            text=summary_text,
            metadata={"engineering_benchmark": True, "command_authority": False},
        )
        self.core.observe(current_event)

        forecast_id = None
        probability = None
        try:
            forecast = self.core.predict(
                task_id=self.TASK_ID,
                event=current_event,
                target_definition={
                    "event": "at least one previously unseen constellation commit is observed at the next poll",
                    "resolution": "1 iff next poll inserted > 0 else 0",
                    "poll_seconds": poll_seconds,
                    "claim_ceiling": "ENGINEERING_SANITY_BENCHMARK",
                },
                target_time=now + max(60, int(poll_seconds)),
                evidence_refs=[current_event.event_id],
                extra_features={"poll_seconds": poll_seconds},
            )
            forecast_id = forecast.forecast_id
            probability = forecast.probability_or_value
        except ValueError:
            # Expected on the first cycle before any resolved-label training exists.
            pass

        self._save(
            {
                "last_cycle_at": now,
                "feature_event": self._event_to_json(current_event),
                "forecast_id": forecast_id,
                "forecast_probability": probability,
            }
        )

        return {
            "poll": poll,
            "learned_model_version": learned_version,
            "next_poll_forecast_id": forecast_id,
            "next_poll_probability": probability,
            "warning": "REPOSITORY_ACTIVITY_FORECAST_IS_AN_ENGINEERING_BENCHMARK_NOT_SCIENTIFIC_FORESIGHT",
        }
