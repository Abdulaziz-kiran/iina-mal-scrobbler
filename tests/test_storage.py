"""Tests for SQLite persistent storage, idempotency tracking, and offline queue."""

from pathlib import Path
from core.storage import Storage


def test_storage_anime_cache(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    storage = Storage(db_path=db_path)

    assert storage.get_cached_anime("frieren") is None

    storage.set_cached_anime("frieren", mal_id=52991, title="Sousou no Frieren", num_episodes=28)
    cached = storage.get_cached_anime("frieren")
    assert cached is not None
    assert cached["mal_id"] == 52991
    assert cached["title"] == "Sousou no Frieren"
    assert cached["num_episodes"] == 28


def test_storage_scrobble_idempotency(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    storage = Storage(db_path=db_path)

    assert not storage.is_already_scrobbled(52991, 5)

    storage.record_scrobble(52991, 5, "/path/to/ep5.mkv", "scrobbled")
    assert storage.is_already_scrobbled(52991, 5)

    # Upsert with same anime_id and episode doesn't crash
    storage.record_scrobble(52991, 5, "/path/to/ep5.mkv", "scrobbled")
    assert storage.is_already_scrobbled(52991, 5)


def test_storage_offline_pending_queue(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    storage = Storage(db_path=db_path)

    assert len(storage.get_due_jobs()) == 0

    storage.enqueue_job("/path/to/ep1.mkv", {"title": "Test", "episode": 1}, "Network timeout")
    jobs = storage.get_due_jobs()
    assert len(jobs) == 1
    assert jobs[0]["source_identity"] == "/path/to/ep1.mkv"
    assert jobs[0]["attempts"] == 0

    job_id = jobs[0]["id"]
    storage.mark_job_failed(job_id, "Still no network", backoff_seconds=10.0)

    # After backoff, the job is not immediately due
    assert len(storage.get_due_jobs()) == 0

    storage.delete_job(job_id)
    stats = storage.get_stats()
    assert stats["pending_jobs"] == 0
