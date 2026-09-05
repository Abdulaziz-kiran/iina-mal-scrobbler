"""MyAnimeList API v2 client with error handling, rate limiting, and token refresh."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from core.config import API_BASE_URL
from core.logger import get_logger
from core.models import AnimeMatch

logger = get_logger()


class MALAPIError(Exception):
    """Base exception for MyAnimeList API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_text: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class MALAuthError(MALAPIError):
    """Raised when request is unauthorized (HTTP 401)."""
    pass


class MALRateLimitError(MALAPIError):
    """Raised when rate limit is exceeded (HTTP 429)."""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class MALServerError(MALAPIError):
    """Raised on MAL server errors (HTTP 5xx)."""
    pass


class MALClient:
    """Client for MyAnimeList API v2."""

    def __init__(
        self,
        token_getter: Callable[[], Optional[str]],
        token_refresher: Optional[Callable[[], Optional[str]]] = None,
        base_url: str = API_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self.token_getter = token_getter
        self.token_refresher = token_refresher
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "User-Agent": "iina-mal-scrobbler/0.1.0",
        }

    def _execute_request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[dict[str, Any]] = None,
        attempt: int = 1,
        refreshed_auth: bool = False,
    ) -> dict[str, Any]:
        token = self.token_getter()
        if not token:
            raise MALAuthError("No access token available. Authentication required.", status_code=401)

        headers = self._get_headers(token)
        encoded_data: Optional[bytes] = None

        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")

        req = urllib.request.Request(url=url, data=encoded_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                content = response.read().decode("utf-8")
                if not content.strip():
                    return {}
                return json.loads(content)

        except urllib.error.HTTPError as err:
            status_code = err.code
            err_body = ""
            try:
                err_body = err.read().decode("utf-8")
            except Exception:
                pass

            logger.debug("HTTP %s error from %s: %s", status_code, url, err_body)

            # 401 Unauthorized -> Refresh token and retry once
            if status_code == 401:
                if not refreshed_auth and self.token_refresher:
                    logger.info("Access token expired (401). Attempting automatic refresh...")
                    new_token = self.token_refresher()
                    if new_token:
                        return self._execute_request(
                            url=url,
                            method=method,
                            data=data,
                            attempt=attempt,
                            refreshed_auth=True,
                        )
                raise MALAuthError("Authentication expired or invalid. Please re-authenticate.", status_code=401, response_text=err_body)

            # 429 Rate Limit -> Backoff with Retry-After or exponential backoff
            if status_code == 429:
                retry_after_hdr = err.headers.get("Retry-After")
                retry_after = 2.0
                if retry_after_hdr:
                    try:
                        retry_after = float(retry_after_hdr)
                    except ValueError:
                        retry_after = 2.0
                else:
                    retry_after = (2.0 ** attempt) + random.uniform(0.1, 0.5)

                if attempt <= 3:
                    logger.warning("MAL rate limit (429) hit. Waiting %.2fs before attempt %d...", retry_after, attempt + 1)
                    time.sleep(retry_after)
                    return self._execute_request(
                        url=url,
                        method=method,
                        data=data,
                        attempt=attempt + 1,
                        refreshed_auth=refreshed_auth,
                    )
                raise MALRateLimitError("Rate limit exceeded repeatedly.", retry_after=retry_after)

            # 5xx Server Error -> Retry with backoff
            if 500 <= status_code < 600:
                if attempt <= 2:
                    backoff = (1.5 ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning("MAL server error (%d). Retrying in %.2fs...", status_code, backoff)
                    time.sleep(backoff)
                    return self._execute_request(
                        url=url,
                        method=method,
                        data=data,
                        attempt=attempt + 1,
                        refreshed_auth=refreshed_auth,
                    )
                raise MALServerError(f"MAL server error {status_code}", status_code=status_code, response_text=err_body)

            raise MALAPIError(f"HTTP error {status_code}: {err.reason}", status_code=status_code, response_text=err_body)

        except urllib.error.URLError as err:
            logger.debug("Network error connecting to %s: %s", url, err.reason)
            raise MALAPIError(f"Network error: {err.reason}")

    def search_anime(self, query: str, limit: int = 10) -> list[AnimeMatch]:
        """Search for anime by title query."""
        clean_query = query.strip()
        if not clean_query:
            return []

        params = {
            "q": clean_query,
            "limit": max(1, min(limit, 20)),
            "fields": "id,title,alternative_titles,media_type,num_episodes,my_list_status,status",
        }
        url = f"{self.base_url}/anime?{urllib.parse.urlencode(params)}"
        response_data = self._execute_request(url, method="GET")

        matches: list[AnimeMatch] = []
        for item in response_data.get("data", []):
            node = item.get("node", {})
            mal_id = node.get("id")
            title = node.get("title", "")
            if not mal_id or not title:
                continue

            alt_titles = node.get("alternative_titles", {})
            synonyms: list[str] = []
            if alt_titles.get("en"):
                synonyms.append(alt_titles["en"])
            if alt_titles.get("ja"):
                synonyms.append(alt_titles["ja"])
            synonyms.extend(alt_titles.get("synonyms", []))

            list_status = node.get("my_list_status") or {}
            watched = list_status.get("num_episodes_watched", 0)
            user_status = list_status.get("status")

            matches.append(
                AnimeMatch(
                    mal_id=int(mal_id),
                    title=title,
                    score=0.0,
                    media_type=node.get("media_type", "tv"),
                    num_episodes=int(node.get("num_episodes", 0)),
                    current_watched_episodes=int(watched),
                    current_status=user_status,
                    synonyms=synonyms,
                )
            )

        return matches

    def get_anime_details(self, anime_id: int) -> Optional[AnimeMatch]:
        """Get details and current user list status for a specific anime ID."""
        fields = "id,title,alternative_titles,media_type,num_episodes,my_list_status,status"
        url = f"{self.base_url}/anime/{anime_id}?fields={fields}"
        try:
            node = self._execute_request(url, method="GET")
        except MALAPIError as err:
            if err.status_code == 404:
                return None
            raise

        mal_id = node.get("id")
        title = node.get("title")
        if not mal_id or not title:
            return None

        alt_titles = node.get("alternative_titles", {})
        synonyms: list[str] = []
        if alt_titles.get("en"):
            synonyms.append(alt_titles["en"])
        if alt_titles.get("ja"):
            synonyms.append(alt_titles["ja"])
        synonyms.extend(alt_titles.get("synonyms", []))

        list_status = node.get("my_list_status") or {}
        watched = list_status.get("num_episodes_watched", 0)
        user_status = list_status.get("status")

        return AnimeMatch(
            mal_id=int(mal_id),
            title=title,
            score=1.0,
            media_type=node.get("media_type", "tv"),
            num_episodes=int(node.get("num_episodes", 0)),
            current_watched_episodes=int(watched),
            current_status=user_status,
            synonyms=synonyms,
        )

    def update_watch_status(
        self,
        anime_id: int,
        num_episodes_watched: int,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Update anime list status for a user.

        Method: PATCH /v2/anime/{anime_id}/my_list_status
        """
        payload: dict[str, Any] = {
            "num_watched_episodes": num_episodes_watched,
        }
        if status:
            payload["status"] = status

        url = f"{self.base_url}/anime/{anime_id}/my_list_status"
        return self._execute_request(url, method="PATCH", data=payload)
