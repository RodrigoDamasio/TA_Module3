"""SQLite adapters: jobs + events (atomic), episodes, LLM response cache.
The only module with SQL; every value is a bound parameter."""

import json
import threading
from dataclasses import asdict

from app.domain.errors import JobNotFound
from app.domain.job import JobEvent, MigrationJob, job_from_dict, job_to_dict
from app.domain.ports import Episode

from . import database

_UPSERT_JOB = (
    "INSERT INTO jobs (id, pair, phase, state_json, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET phase = excluded.phase, state_json = excluded.state_json, "
    "updated_at = excluded.updated_at"
)
_INSERT_EVENT = "INSERT INTO events (job_id, type, data_json) VALUES (?, ?, ?)"
_GET_JOB = "SELECT state_json FROM jobs WHERE id = ?"
_EVENTS_SINCE = "SELECT id, type, data_json FROM events WHERE job_id = ? AND id > ? ORDER BY id"
_JOBS_IN_PHASE = "SELECT state_json FROM jobs WHERE phase = ?"
_INSERT_EPISODE = "INSERT INTO episodes (pair, episode_json) VALUES (?, ?)"
_RECENT_EPISODES = "SELECT episode_json FROM episodes WHERE pair = ? ORDER BY id DESC LIMIT ?"
_GET_CACHE = "SELECT response_json FROM llm_cache WHERE key = ?"
_PUT_CACHE = "INSERT OR REPLACE INTO llm_cache (key, response_json) VALUES (?, ?)"


class SqliteJobRepository:
    def __init__(self, path: str) -> None:
        self._path = path
        self._write_lock = threading.Lock()
        database.init(path)

    def create(self, job: MigrationJob) -> None:
        self.save(job)

    def save(self, job: MigrationJob) -> None:
        """Job state and its pending events in ONE transaction: the SSE stream and the
        stored state never disagree."""
        with self._write_lock, database.connect(self._path) as conn:
            events = job.pop_events()
            conn.execute(
                _UPSERT_JOB,
                (
                    job.id,
                    job.pair,
                    job.phase.value,
                    json.dumps(job_to_dict(job)),
                    job.created_at,
                    job.updated_at,
                ),
            )
            for event in events:
                cursor = conn.execute(_INSERT_EVENT, (job.id, event.type, json.dumps(event.data)))
                event.id = cursor.lastrowid

    def get(self, job_id: str) -> MigrationJob:
        with database.connect(self._path) as conn:
            row = conn.execute(_GET_JOB, (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return job_from_dict(json.loads(row["state_json"]))

    def events_since(self, job_id: str, after_id: int) -> list[JobEvent]:
        with database.connect(self._path) as conn:
            rows = conn.execute(_EVENTS_SINCE, (job_id, after_id)).fetchall()
        return [JobEvent(r["type"], json.loads(r["data_json"]), r["id"]) for r in rows]

    def jobs_in_phases(self, phases: set[str]) -> list[MigrationJob]:
        with database.connect(self._path) as conn:
            rows = [r for p in sorted(phases) for r in conn.execute(_JOBS_IN_PHASE, (p,))]
        return [job_from_dict(json.loads(r["state_json"])) for r in rows]


class SqliteEpisodeStore:
    """Episodic memory (course §1.5): one record per finished migration."""

    def __init__(self, path: str) -> None:
        self._path = path
        database.init(path)

    def record(self, episode: Episode) -> None:
        with database.connect(self._path) as conn:
            conn.execute(_INSERT_EPISODE, (episode.pair, json.dumps(asdict(episode))))

    def recent(self, pair: str, limit: int) -> list[Episode]:
        with database.connect(self._path) as conn:
            rows = conn.execute(_RECENT_EPISODES, (pair, limit)).fetchall()
        return [Episode(**json.loads(r["episode_json"])) for r in rows]


class SqliteResponseCache:
    def __init__(self, path: str) -> None:
        self._path = path
        database.init(path)

    def get(self, key: str) -> dict | None:
        with database.connect(self._path) as conn:
            row = conn.execute(_GET_CACHE, (key,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def put(self, key: str, value: dict) -> None:
        with database.connect(self._path) as conn:
            conn.execute(_PUT_CACHE, (key, json.dumps(value)))
