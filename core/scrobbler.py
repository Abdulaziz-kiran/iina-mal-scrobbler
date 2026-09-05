"""Scrobbler engine orchestrating parsing, resolution, storage, and MAL synchronization."""

from __future__ import annotations

import os
from typing import Optional

from core.logging import get_logger
from core.mal_api import (
    MALAPIError,
    MALAuthError,
    MALClient,
    MALRateLimitError,
    MALServerError,
)
from core.models import (
    AnimeMatch,
    ParsedAnime,
    ScrobbleResult,
    ScrobbleStatus,
)
from core.parser import parse_filename
from core.resolver import AnimeResolver, normalize_title
from core.storage import Storage

logger = get_logger()


class Scrobbler:
    """Core synchronization engine."""

    def __init__(
        self,
        api_client: MALClient,
        storage: Optional[Storage] = None,
        resolver: Optional[AnimeResolver] = None,
    ) -> None:
        self.api_client = api_client
        self.storage = storage or Storage()
        self.resolver = resolver or AnimeResolver()

    def scrobble_file(self, file_path: str) -> ScrobbleResult:
        """
        Process a media file and synchronize progress to MyAnimeList.

        Never blocks player or raises unhandled exceptions. Always returns explicit ScrobbleResult.
        """
        # Step 1: Parse filename
        parsed: ParsedAnime = parse_filename(file_path)

        if parsed.episode is None:
            reason = "Could not reliably extract episode number."
            if parsed.warnings:
                reason += f" ({'; '.join(parsed.warnings)})"
            return ScrobbleResult(
                success=False,
                status=ScrobbleStatus.PARSE_FAILED,
                reason=reason,
            )

        if parsed.confidence < 0.70:
            return ScrobbleResult(
                success=False,
                status=ScrobbleStatus.PARSE_FAILED,
                reason=f"Parser confidence too low ({parsed.confidence:.2f} < 0.70). Warnings: {parsed.warnings}",
            )

        norm_title = normalize_title(parsed.title)

        # Step 2: Resolve Anime to MAL ID (Cache-first)
        cached = self.storage.get_cached_anime(norm_title)
        mal_id: Optional[int] = None
        anime_title: str = parsed.title
        total_episodes: int = 0
        current_watched: int = 0
        current_status: Optional[str] = None

        if cached:
            mal_id = cached["mal_id"]
            anime_title = cached["title"]
            total_episodes = cached.get("num_episodes", 0)
            logger.debug("Cache hit for '%s' -> MAL ID %d ('%s')", norm_title, mal_id, anime_title)
        else:
            # Query MAL Search
            try:
                candidates = self.api_client.search_anime(parsed.title, limit=10)
            except MALAuthError as err:
                return ScrobbleResult(
                    success=False,
                    status=ScrobbleStatus.AUTH_REQUIRED,
                    reason=str(err),
                )
            except (MALAPIError, OSError) as err:
                # Network or API error during search -> Queue job
                logger.warning("Network failure searching for '%s': %s. Queuing job.", parsed.title, err)
                payload = {"file_path": file_path, "parsed": parsed.to_dict()}
                self.storage.enqueue_job(source_identity=file_path, payload=payload, last_error=str(err))
                return ScrobbleResult(
                    success=False,
                    status=ScrobbleStatus.PENDING,
                    reason=f"Network error during search; queued for offline retry. ({err})",
                )

            outcome = self.resolver.resolve(parsed, candidates)
            if outcome.is_ambiguous:
                return ScrobbleResult(
                    success=False,
                    status=ScrobbleStatus.AMBIGUOUS,
                    reason=outcome.reason,
                )

            if outcome.match is None:
                return ScrobbleResult(
                    success=False,
                    status=ScrobbleStatus.NO_MATCH,
                    reason=outcome.reason,
                )

            matched = outcome.match
            mal_id = matched.mal_id
            anime_title = matched.title
            total_episodes = matched.num_episodes
            current_watched = matched.current_watched_episodes
            current_status = matched.current_status

            # Cache the verified title mapping
            self.storage.set_cached_anime(
                normalized_title=norm_title,
                mal_id=mal_id,
                title=anime_title,
                num_episodes=total_episodes,
            )

        # Step 3: Local idempotency check
        if self.storage.is_already_scrobbled(mal_id, parsed.episode):
            return ScrobbleResult(
                success=True,
                status=ScrobbleStatus.ALREADY_SYNCED,
                reason=f"Episode {parsed.episode} of '{anime_title}' was already recorded.",
                mal_id=mal_id,
                anime_title=anime_title,
                episode=parsed.episode,
            )

        # Step 4: Verify current remote progress if not fetched during search
        if cached:
            try:
                details = self.api_client.get_anime_details(mal_id)
                if details:
                    current_watched = details.current_watched_episodes
                    current_status = details.current_status
                    total_episodes = details.num_episodes
            except MALAuthError as err:
                return ScrobbleResult(
                    success=False,
                    status=ScrobbleStatus.AUTH_REQUIRED,
                    reason=str(err),
                )
            except (MALAPIError, OSError) as err:
                logger.warning("Could not fetch remote details for MAL %d: %s. Queuing job.", mal_id, err)
                payload = {"file_path": file_path, "parsed": parsed.to_dict(), "mal_id": mal_id, "title": anime_title}
                self.storage.enqueue_job(source_identity=file_path, payload=payload, last_error=str(err))
                return ScrobbleResult(
                    success=False,
                    status=ScrobbleStatus.PENDING,
                    reason=f"Network error verifying progress; queued for offline retry. ({err})",
                    mal_id=mal_id,
                    anime_title=anime_title,
                    episode=parsed.episode,
                )

        # Step 5: Monotonic progress policy check
        if current_watched >= parsed.episode:
            self.storage.record_scrobble(mal_id, parsed.episode, file_path, ScrobbleStatus.ALREADY_SYNCED.value)
            return ScrobbleResult(
                success=True,
                status=ScrobbleStatus.ALREADY_SYNCED,
                reason=f"MAL already reflects progress at or beyond episode {parsed.episode} (currently {current_watched}).",
                mal_id=mal_id,
                anime_title=anime_title,
                episode=parsed.episode,
            )

        # Step 6: Determine target list status
        target_status = "watching"
        if total_episodes > 0 and parsed.episode >= total_episodes:
            target_status = "completed"
        elif current_status in ("watching", "plan_to_watch", None):
            target_status = "watching"
        else:
            # User had it on_hold or dropped -> keep status unless watching requested
            target_status = current_status

        # Step 7: Update MAL
        try:
            self.api_client.update_watch_status(
                anime_id=mal_id,
                num_episodes_watched=parsed.episode,
                status=target_status,
            )
        except MALAuthError as err:
            return ScrobbleResult(
                success=False,
                status=ScrobbleStatus.AUTH_REQUIRED,
                reason=str(err),
                mal_id=mal_id,
                anime_title=anime_title,
                episode=parsed.episode,
            )
        except (MALAPIError, OSError) as err:
            logger.warning("Failed updating MAL status for %d: %s. Enqueuing for retry.", mal_id, err)
            payload = {
                "file_path": file_path,
                "parsed": parsed.to_dict(),
                "mal_id": mal_id,
                "title": anime_title,
                "target_status": target_status,
            }
            self.storage.enqueue_job(source_identity=file_path, payload=payload, last_error=str(err))
            return ScrobbleResult(
                success=False,
                status=ScrobbleStatus.PENDING,
                reason=f"Network error during update; queued for offline retry. ({err})",
                mal_id=mal_id,
                anime_title=anime_title,
                episode=parsed.episode,
            )

        # Step 8: Success recording
        self.storage.record_scrobble(mal_id, parsed.episode, file_path, ScrobbleStatus.SCROBBLED.value)

        return ScrobbleResult(
            success=True,
            status=ScrobbleStatus.SCROBBLED,
            reason=f"Updated progress to episode {parsed.episode} ({target_status}).",
            mal_id=mal_id,
            anime_title=anime_title,
            episode=parsed.episode,
        )

    def retry_pending_jobs(self) -> int:
        """Retry all due offline pending jobs. Returns number of successfully processed jobs."""
        due_jobs = self.storage.get_due_jobs(limit=20)
        if not due_jobs:
            return 0

        successful_count = 0
        for job in due_jobs:
            payload = job.get("payload", {})
            file_path = payload.get("file_path") or job.get("source_identity")
            if not file_path:
                self.storage.delete_job(job["id"])
                continue

            try:
                res = self.scrobble_file(file_path)
                if res.status in (ScrobbleStatus.SCROBBLED, ScrobbleStatus.ALREADY_SYNCED):
                    self.storage.delete_job(job["id"])
                    successful_count += 1
                elif res.status in (ScrobbleStatus.AUTH_REQUIRED, ScrobbleStatus.NO_MATCH, ScrobbleStatus.AMBIGUOUS):
                    # Unrecoverable without user action
                    self.storage.mark_job_failed(job["id"], res.reason, backoff_seconds=300.0)
                else:
                    self.storage.mark_job_failed(job["id"], res.reason, backoff_seconds=60.0)
            except Exception as err:
                self.storage.mark_job_failed(job["id"], str(err), backoff_seconds=60.0)

        return successful_count
