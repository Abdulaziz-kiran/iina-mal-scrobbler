"""SQLite persistent state, idempotency tracker, title cache, and offline retry queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import DATABASE_PATH, ensure_directories
from core.logger import get_logger

logger = get_logger()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS anime_cache (
    normalized_title TEXT PRIMARY KEY,
    mal_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    num_episodes INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrobbles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    source_identity TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT,
    UNIQUE(anime_id, episode)
);

CREATE TABLE IF NOT EXISTS pending_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_identity TEXT UNIQUE NOT NULL,
    payload TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT
);
"""


class Storage:
    """Encapsulates SQLite persistent storage."""

    def __init__(self, db_path: Path = DATABASE_PATH) -> None:
        self.db_path = db_path
        if self.db_path != Path(":memory:"):
            ensure_directories()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    # --- Title Cache Operations ---

    def get_cached_anime(self, normalized_title: str) -> Optional[dict[str, Any]]:
        """Look up cached MAL ID and metadata for a normalized title."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT mal_id, title, num_episodes, updated_at FROM anime_cache WHERE normalized_title = ?",
                (normalized_title,),
            ).fetchone()
            if row:
                return {
                    "mal_id": row["mal_id"],
                    "title": row["title"],
                    "num_episodes": row["num_episodes"],
                    "updated_at": row["updated_at"],
                }
        return None

    def set_cached_anime(self, normalized_title: str, mal_id: int, title: str, num_episodes: int = 0) -> None:
        """Cache MAL resolution result."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO anime_cache (normalized_title, mal_id, title, num_episodes, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(normalized_title) DO UPDATE SET
                    mal_id = excluded.mal_id,
                    title = excluded.title,
                    num_episodes = excluded.num_episodes,
                    updated_at = excluded.updated_at
                """,
                (normalized_title, mal_id, title, num_episodes, now),
            )
            conn.commit()

    # --- Scrobble History / Idempotency Operations ---

    def is_already_scrobbled(self, anime_id: int, episode: int) -> bool:
        """Check if an anime episode has already been recorded in local history as scrobbled or synced."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM scrobbles WHERE anime_id = ? AND episode = ? AND status IN ('scrobbled', 'already_synced')",
                (anime_id, episode),
            ).fetchone()
            return bool(row)

    def record_scrobble(
        self,
        anime_id: int,
        episode: int,
        source_identity: str,
        status: str,
        last_error: Optional[str] = None,
    ) -> None:
        """Record or update a scrobble state idempotently."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scrobbles (anime_id, episode, source_identity, status, created_at, updated_at, last_error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(anime_id, episode) DO UPDATE SET
                    source_identity = excluded.source_identity,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    last_error = excluded.last_error
                """,
                (anime_id, episode, source_identity, status, now, now, last_error),
            )
            conn.commit()

    # --- Offline Pending Queue Operations ---

    def enqueue_job(self, source_identity: str, payload: dict[str, Any], last_error: Optional[str] = None) -> None:
        """Enqueue or update an offline pending scrobble job."""
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO pending_jobs (source_identity, payload, attempts, next_attempt_at, last_error)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(source_identity) DO UPDATE SET
                    payload = excluded.payload,
                    last_error = excluded.last_error
                """,
                (source_identity, payload_json, now, last_error),
            )
            conn.commit()

    def get_due_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch pending jobs that are due for execution."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, source_identity, payload, attempts, last_error
                FROM pending_jobs
                WHERE next_attempt_at <= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()

            jobs = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except Exception:
                    payload = {}
                jobs.append({
                    "id": row["id"],
                    "source_identity": row["source_identity"],
                    "payload": payload,
                    "attempts": row["attempts"],
                    "last_error": row["last_error"],
                })
            return jobs

    def mark_job_failed(self, job_id: int, error_message: str, backoff_seconds: float = 60.0) -> None:
        """Increment attempt counter and schedule next retry with backoff."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT attempts FROM pending_jobs WHERE id = ?", (job_id,)).fetchone()
            attempts = (row["attempts"] + 1) if row else 1
            # Exponential backoff calculation
            delay = backoff_seconds * (2 ** min(attempts - 1, 5))
            next_attempt = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + delay, tz=timezone.utc
            ).isoformat()

            conn.execute(
                "UPDATE pending_jobs SET attempts = ?, next_attempt_at = ?, last_error = ? WHERE id = ?",
                (attempts, next_attempt, error_message, job_id),
            )
            conn.commit()

    def delete_job(self, job_id: int) -> None:
        """Remove a successfully completed job from queue."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM pending_jobs WHERE id = ?", (job_id,))
            conn.commit()

    def get_stats(self) -> dict[str, int]:
        """Return counts of cached anime, scrobbles, and pending jobs."""
        with self._get_connection() as conn:
            cached_count = conn.execute("SELECT COUNT(*) FROM anime_cache").fetchone()[0]
            scrobble_count = conn.execute("SELECT COUNT(*) FROM scrobbles").fetchone()[0]
            pending_count = conn.execute("SELECT COUNT(*) FROM pending_jobs").fetchone()[0]
            return {
                "cached_anime": cached_count,
                "recorded_scrobbles": scrobble_count,
                "pending_jobs": pending_count,
            }
