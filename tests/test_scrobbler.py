"""Tests for Scrobbler orchestration, monotonic progress, and error policies."""

from pathlib import Path
from unittest.mock import MagicMock

from core.mal_api import MALAPIError, MALAuthError, MALClient
from core.models import AnimeMatch, ScrobbleStatus
from core.scrobbler import Scrobbler
from core.storage import Storage


def _make_mock_client():
    client = MagicMock(spec=MALClient)
    return client


def test_scrobble_happy_path(tmp_path: Path):
    storage = Storage(db_path=tmp_path / "test.sqlite3")
    client = _make_mock_client()

    client.search_anime.return_value = [
        AnimeMatch(
            mal_id=52991,
            title="Sousou no Frieren",
            score=0.95,
            num_episodes=28,
            current_watched_episodes=4,
            current_status="watching",
        )
    ]
    client.update_watch_status.return_value = {"num_episodes_watched": 5}

    scrobbler = Scrobbler(api_client=client, storage=storage)
    res = scrobbler.scrobble_file("/Anime/[SubsPlease] Sousou no Frieren - 05 (1080p).mkv")

    assert res.success is True
    assert res.status == ScrobbleStatus.SCROBBLED
    assert res.mal_id == 52991
    assert res.episode == 5
    client.update_watch_status.assert_called_once_with(anime_id=52991, num_episodes_watched=5, status="watching")

    # Second invocation should be immediately recognized as already synced (idempotent)
    res2 = scrobbler.scrobble_file("/Anime/[SubsPlease] Sousou no Frieren - 05 (1080p).mkv")
    assert res2.status == ScrobbleStatus.ALREADY_SYNCED
    # update_watch_status should NOT have been called a second time
    assert client.update_watch_status.call_count == 1


def test_monotonic_progress_prevents_downgrade(tmp_path: Path):
    storage = Storage(db_path=tmp_path / "test.sqlite3")
    client = _make_mock_client()

    # User already watched episode 10 on MAL, but opened episode 5
    client.search_anime.return_value = [
        AnimeMatch(
            mal_id=52991,
            title="Sousou no Frieren",
            score=0.95,
            num_episodes=28,
            current_watched_episodes=10,
            current_status="watching",
        )
    ]

    scrobbler = Scrobbler(api_client=client, storage=storage)
    res = scrobbler.scrobble_file("[SubsPlease] Sousou no Frieren - 05.mkv")

    assert res.success is True
    assert res.status == ScrobbleStatus.ALREADY_SYNCED
    assert "already reflects progress" in res.reason
    client.update_watch_status.assert_not_called()


def test_parse_failed_rejection(tmp_path: Path):
    storage = Storage(db_path=tmp_path / "test.sqlite3")
    client = _make_mock_client()

    scrobbler = Scrobbler(api_client=client, storage=storage)
    res = scrobbler.scrobble_file("movie_without_episode.mkv")

    assert res.success is False
    assert res.status == ScrobbleStatus.PARSE_FAILED
    client.search_anime.assert_not_called()


def test_network_failure_enqueues_pending_job(tmp_path: Path):
    storage = Storage(db_path=tmp_path / "test.sqlite3")
    client = _make_mock_client()
    client.search_anime.side_effect = MALAPIError("Connection refused")

    scrobbler = Scrobbler(api_client=client, storage=storage)
    res = scrobbler.scrobble_file("[SubsPlease] Frieren - 05.mkv")

    assert res.success is False
    assert res.status == ScrobbleStatus.PENDING
    assert "queued for offline retry" in res.reason
    assert len(storage.get_due_jobs()) == 1


def test_offline_retry_success(tmp_path: Path):
    storage = Storage(db_path=tmp_path / "test.sqlite3")
    client = _make_mock_client()
    scrobbler = Scrobbler(api_client=client, storage=storage)

    # First attempt: network error -> enqueued
    client.search_anime.side_effect = MALAPIError("Offline")
    res1 = scrobbler.scrobble_file("[SubsPlease] Frieren - 05.mkv")
    assert res1.status == ScrobbleStatus.PENDING

    # Network comes back online
    client.search_anime.side_effect = None
    client.search_anime.return_value = [
        AnimeMatch(mal_id=52991, title="Frieren", score=0.95, num_episodes=28, current_watched_episodes=4)
    ]
    client.update_watch_status.return_value = {"num_episodes_watched": 5}

    # Run retry_pending_jobs()
    retried_count = scrobbler.retry_pending_jobs()
    assert retried_count == 1
    assert len(storage.get_due_jobs()) == 0
