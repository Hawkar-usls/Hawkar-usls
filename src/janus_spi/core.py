from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib
import numpy as np
from scipy.sparse import vstack as sparse_vstack
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier, SGDRegressor
from sklearn.metrics.pairwise import cosine_similarity


@dataclass(frozen=True)
class SemanticEvent:
    event_id: str
    timestamp: float
    source: str
    source_ref: str
    text: str
    metadata: Dict[str, Any]
    content_hash: str

    @staticmethod
    def build(source: str, source_ref: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> "SemanticEvent":
        metadata = metadata or {}
        canonical = json.dumps(
            {"source": source, "source_ref": source_ref, "text": text, "metadata": metadata},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return SemanticEvent(
            event_id=f"evt-{digest[:20]}",
            timestamp=time.time(),
            source=source,
            source_ref=source_ref,
            text=text,
            metadata=metadata,
            content_hash=digest,
        )


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    task_id: str
    created_at: float
    target_time: float
    feature_cutoff_time: float
    model_version: str
    prediction_type: str
    probability_or_value: float
    uncertainty: Optional[float]
    evidence_refs: List[str]
    target_definition_hash: str
    status: str = "FROZEN"


class Ledger:
    """Append-preserving SQLite ledger for events, forecasts and resolved outcomes."""

    def __init__(self, path: str | Path = "state/janus_spi.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY,
              timestamp REAL NOT NULL,
              source TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              text TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              content_hash TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS forecasts (
              forecast_id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              created_at REAL NOT NULL,
              target_time REAL NOT NULL,
              feature_cutoff_time REAL NOT NULL,
              model_version TEXT NOT NULL,
              prediction_type TEXT NOT NULL,
              probability_or_value REAL NOT NULL,
              uncertainty REAL,
              evidence_refs_json TEXT NOT NULL,
              target_definition_hash TEXT NOT NULL,
              status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resolutions (
              forecast_id TEXT PRIMARY KEY,
              resolved_at REAL NOT NULL,
              observed_outcome REAL NOT NULL,
              scoring_rule TEXT NOT NULL,
              score REAL NOT NULL,
              status TEXT NOT NULL,
              FOREIGN KEY(forecast_id) REFERENCES forecasts(forecast_id)
            );

            CREATE TABLE IF NOT EXISTS model_updates (
              update_id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              created_at REAL NOT NULL,
              label REAL NOT NULL,
              feature_hash TEXT NOT NULL,
              model_version TEXT NOT NULL,
              provenance_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_model_updates_task_feature
              ON model_updates(task_id, feature_hash);
            """
        )
        self.db.commit()

    @staticmethod
    def _event_values(event: SemanticEvent) -> tuple[Any, ...]:
        return (
            event.event_id,
            event.timestamp,
            event.source,
            event.source_ref,
            event.text,
            json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
            event.content_hash,
        )

    def append_event(self, event: SemanticEvent) -> bool:
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            self._event_values(event),
        )
        self.db.commit()
        return cursor.rowcount == 1

    def append_events(self, events: Iterable[SemanticEvent]) -> List[bool]:
        """Insert many observations in one SQLite transaction.

        The boolean result preserves per-event deduplication semantics while avoiding
        one fsync/commit for every commit observed during a repository poll.
        """
        results: List[bool] = []
        with self.db:
            for event in events:
                cursor = self.db.execute(
                    "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                    self._event_values(event),
                )
                results.append(cursor.rowcount == 1)
        return results

    def append_forecast(self, forecast: Forecast) -> None:
        self.db.execute(
            "INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                forecast.forecast_id,
                forecast.task_id,
                forecast.created_at,
                forecast.target_time,
                forecast.feature_cutoff_time,
                forecast.model_version,
                forecast.prediction_type,
                forecast.probability_or_value,
                forecast.uncertainty,
                json.dumps(forecast.evidence_refs),
                forecast.target_definition_hash,
                forecast.status,
            ),
        )
        self.db.commit()

    def get_forecast(self, forecast_id: str) -> Optional[Dict[str, Any]]:
        row = self.db.execute(
            "SELECT * FROM forecasts WHERE forecast_id = ?", (forecast_id,)
        ).fetchone()
        if row is None:
            return None
        keys = [
            "forecast_id", "task_id", "created_at", "target_time", "feature_cutoff_time",
            "model_version", "prediction_type", "probability_or_value", "uncertainty",
            "evidence_refs_json", "target_definition_hash", "status"
        ]
        return dict(zip(keys, row))

    def resolve_forecast(self, forecast_id: str, observed_outcome: float) -> Dict[str, Any]:
        forecast = self.get_forecast(forecast_id)
        if forecast is None:
            raise KeyError(f"Unknown forecast: {forecast_id}")
        if forecast["status"] != "FROZEN":
            raise ValueError(f"Forecast is not resolvable from status={forecast['status']}")
        if time.time() < forecast["target_time"]:
            raise ValueError("Target time has not arrived; outcome cannot be resolved yet")

        pred = float(forecast["probability_or_value"])
        if forecast["prediction_type"] == "BINARY_PROBABILITY":
            y = 1.0 if observed_outcome >= 0.5 else 0.0
            score = (pred - y) ** 2
            scoring_rule = "BRIER"
        else:
            score = abs(pred - float(observed_outcome))
            scoring_rule = "ABSOLUTE_ERROR"

        with self.db:
            self.db.execute(
                "INSERT INTO resolutions VALUES (?, ?, ?, ?, ?, ?)",
                (forecast_id, time.time(), float(observed_outcome), scoring_rule, score, "RESOLVED"),
            )
            self.db.execute(
                "UPDATE forecasts SET status='RESOLVED' WHERE forecast_id=?", (forecast_id,)
            )
        return {"forecast_id": forecast_id, "scoring_rule": scoring_rule, "score": score}

    def append_model_update(
        self,
        task_id: str,
        label: float,
        feature_hash: str,
        model_version: str,
        provenance: Dict[str, Any],
    ) -> None:
        self.db.execute(
            "INSERT INTO model_updates VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"upd-{uuid.uuid4().hex}", task_id, time.time(), float(label), feature_hash,
                model_version, json.dumps(provenance, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.db.commit()

    def iter_events(self, limit: int = 1000) -> Iterable[SemanticEvent]:
        rows = self.db.execute(
            "SELECT event_id,timestamp,source,source_ref,text,metadata_json,content_hash "
            "FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        for row in rows:
            yield SemanticEvent(
                event_id=row[0], timestamp=row[1], source=row[2], source_ref=row[3],
                text=row[4], metadata=json.loads(row[5]), content_hash=row[6]
            )


class SemanticMemory:
    """Lightweight semantic layer using a stateless hashing vectorizer.

    The recent corpus is cached as a sparse matrix and updated incrementally after
    successful ingest. Similarity never receives verdict authority.
    """

    def __init__(self, ledger: Ledger, n_features: int = 2**15) -> None:
        self.ledger = ledger
        self.vectorizer = HashingVectorizer(
            n_features=n_features,
            alternate_sign=False,
            norm="l2",
            ngram_range=(1, 2),
            lowercase=True,
        )
        self._cache_events: List[SemanticEvent] = []
        self._cache_matrix = None
        self._cache_limit: Optional[int] = None

    def _cache_prepend(self, event: SemanticEvent) -> None:
        if self._cache_matrix is None or self._cache_limit is None:
            return
        row = self.vectorizer.transform([event.text])
        self._cache_events.insert(0, event)
        self._cache_matrix = sparse_vstack([row, self._cache_matrix], format="csr")
        if len(self._cache_events) > self._cache_limit:
            self._cache_events = self._cache_events[: self._cache_limit]
            self._cache_matrix = self._cache_matrix[: self._cache_limit]

    def _ensure_cache(self, corpus_limit: int) -> None:
        corpus_limit = max(1, int(corpus_limit))
        if self._cache_matrix is not None and self._cache_limit == corpus_limit:
            return
        self._cache_events = list(self.ledger.iter_events(limit=corpus_limit))
        self._cache_limit = corpus_limit
        if self._cache_events:
            self._cache_matrix = self.vectorizer.transform([event.text for event in self._cache_events])
        else:
            self._cache_matrix = None

    def ingest(self, event: SemanticEvent) -> bool:
        inserted = self.ledger.append_event(event)
        if inserted:
            self._cache_prepend(event)
        return inserted

    def ingest_many(self, events: Iterable[SemanticEvent]) -> List[bool]:
        batch = list(events)
        inserted = self.ledger.append_events(batch)
        for event, was_inserted in zip(batch, inserted):
            if was_inserted:
                self._cache_prepend(event)
        return inserted

    def search(self, query: str, limit: int = 10, corpus_limit: int = 5000) -> List[Dict[str, Any]]:
        self._ensure_cache(corpus_limit)
        if self._cache_matrix is None or not self._cache_events:
            return []
        q = self.vectorizer.transform([query])
        scores = cosine_similarity(q, self._cache_matrix).ravel()
        order = np.argsort(scores)[::-1][: max(0, int(limit))]
        return [
            {
                "score": float(scores[i]),
                "event": asdict(self._cache_events[i]),
                "warning": "SEMANTIC_SIMILARITY_IS_NOT_CAUSAL_OR_VERDICT_AUTHORITY",
            }
            for i in order
        ]


class OnlineTask:
    def __init__(self, task_id: str, task_type: str) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.version = 0
        self.fitted = False
        if task_type == "BINARY_PROBABILITY":
            self.model = SGDClassifier(loss="log_loss", random_state=117)
        elif task_type == "NUMERIC_FORECAST":
            self.model = SGDRegressor(random_state=117)
        else:
            raise ValueError(f"Unsupported task_type: {task_type}")

    @property
    def model_version(self) -> str:
        return f"{self.task_id}:origin-prime-{self.version}"


class JanusSPICore:
    """JANUS Semantic-Predictive Intelligence MVP.

    Key invariant: unlabelled observations enrich semantic memory but do not silently
    train predictive heads. Predictive updates require an explicit resolved label.

    Security boundary: ``online_tasks.joblib`` is trusted local runtime state. Joblib
    persistence is not safe for attacker-controlled files and must never be loaded from
    an untrusted or publicly writable state directory.
    """

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.state_dir / "janus_spi.sqlite3")
        self.semantic = SemanticMemory(self.ledger)
        self.featureizer = HashingVectorizer(
            n_features=2**14,
            alternate_sign=False,
            norm="l2",
            ngram_range=(1, 2),
            lowercase=True,
        )
        self.tasks: Dict[str, OnlineTask] = {}
        self._load_tasks()

    def _task_path(self) -> Path:
        return self.state_dir / "online_tasks.joblib"

    def _load_tasks(self) -> None:
        path = self._task_path()
        if path.exists():
            self.tasks = joblib.load(path)

    def _save_tasks(self) -> None:
        path = self._task_path()
        tmp = path.with_name(path.name + ".tmp")
        joblib.dump(self.tasks, tmp)
        tmp.replace(path)

    @staticmethod
    def _feature_text(event: SemanticEvent, extra: Optional[Dict[str, Any]] = None) -> str:
        extra = extra or {}
        return "\n".join(
            [
                f"source={event.source}",
                f"source_ref={event.source_ref}",
                event.text,
                json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                json.dumps(extra, ensure_ascii=False, sort_keys=True),
            ]
        )

    def observe(self, event: SemanticEvent) -> bool:
        return self.semantic.ingest(event)

    def observe_many(self, events: Iterable[SemanticEvent]) -> List[bool]:
        return self.semantic.ingest_many(events)

    def ensure_task(self, task_id: str, task_type: str, *, persist: bool = True) -> OnlineTask:
        task = self.tasks.get(task_id)
        if task is None:
            task = OnlineTask(task_id, task_type)
            self.tasks[task_id] = task
            if persist:
                self._save_tasks()
        elif task.task_type != task_type:
            raise ValueError(f"Task {task_id} already exists as {task.task_type}")
        return task

    def learn(
        self,
        task_id: str,
        task_type: str,
        event: SemanticEvent,
        label: float,
        provenance: Optional[Dict[str, Any]] = None,
        extra_features: Optional[Dict[str, Any]] = None,
    ) -> str:
        task = self.ensure_task(task_id, task_type, persist=False)
        feature_text = self._feature_text(event, extra_features)
        X = self.featureizer.transform([feature_text])
        if task_type == "BINARY_PROBABILITY":
            y = np.array([1 if float(label) >= 0.5 else 0])
            if not task.fitted:
                task.model.partial_fit(X, y, classes=np.array([0, 1]))
            else:
                task.model.partial_fit(X, y)
        else:
            task.model.partial_fit(X, np.array([float(label)]))
        task.fitted = True
        task.version += 1
        self._save_tasks()

        feature_hash = hashlib.sha256(feature_text.encode("utf-8")).hexdigest()
        self.ledger.append_model_update(
            task_id=task_id,
            label=float(label),
            feature_hash=feature_hash,
            model_version=task.model_version,
            provenance=provenance or {},
        )
        return task.model_version

    def predict(
        self,
        task_id: str,
        event: SemanticEvent,
        target_definition: Dict[str, Any],
        target_time: float,
        evidence_refs: Optional[List[str]] = None,
        extra_features: Optional[Dict[str, Any]] = None,
    ) -> Forecast:
        if task_id not in self.tasks or not self.tasks[task_id].fitted:
            raise ValueError(f"Task {task_id} has no resolved-label training history")
        now = time.time()
        if target_time <= now:
            raise ValueError("target_time must be in the future when the forecast is frozen")

        task = self.tasks[task_id]
        feature_text = self._feature_text(event, extra_features)
        X = self.featureizer.transform([feature_text])
        if task.task_type == "BINARY_PROBABILITY":
            value = float(task.model.predict_proba(X)[0, 1])
            value = min(1.0, max(0.0, value))
            uncertainty = None
        else:
            value = float(task.model.predict(X)[0])
            uncertainty = None

        target_json = json.dumps(target_definition, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        target_hash = hashlib.sha256(target_json.encode("utf-8")).hexdigest()
        forecast = Forecast(
            forecast_id=f"fc-{uuid.uuid4().hex}",
            task_id=task_id,
            created_at=now,
            target_time=float(target_time),
            feature_cutoff_time=now,
            model_version=task.model_version,
            prediction_type=task.task_type,
            probability_or_value=value,
            uncertainty=uncertainty,
            evidence_refs=evidence_refs or [event.event_id],
            target_definition_hash=target_hash,
        )
        self.ledger.append_forecast(forecast)
        return forecast

    def resolve(self, forecast_id: str, observed_outcome: float) -> Dict[str, Any]:
        return self.ledger.resolve_forecast(forecast_id, observed_outcome)

    def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.semantic.search(query=query, limit=limit)
