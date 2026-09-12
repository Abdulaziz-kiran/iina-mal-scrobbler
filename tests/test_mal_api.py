"""Tests for the MyAnimeList API client using mocked HTTP interactions."""

import io
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from core.mal_api import (
    MALAuthError,
    MALClient,
    MALRateLimitError,
    MALServerError,
)


def _make_mock_response(status: int = 200, json_data: dict = None, headers: dict = None):
    data_bytes = json.dumps(json_data or {}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = data_bytes
    mock_resp.status = status
    mock_resp.headers = headers or {}
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def test_search_anime_success():
    sample_response = {
        "data": [
            {
                "node": {
                    "id": 52991,
                    "title": "Sousou no Frieren",
                    "alternative_titles": {
                        "en": "Frieren: Beyond Journey's End",
                        "ja": "葬送のフリーレン",
                        "synonyms": ["Frieren at the Funeral"],
                    },
                    "media_type": "tv",
                    "num_episodes": 28,
                    "my_list_status": {
                        "status": "watching",
                        "num_episodes_watched": 5,
                    },
                }
            }
        ]
    }

    client = MALClient(token_getter=lambda: "fake_token")

    with patch("urllib.request.urlopen", return_value=_make_mock_response(200, sample_response)):
        results = client.search_anime("Frieren")
        assert len(results) == 1
        match = results[0]
        assert match.mal_id == 52991
        assert match.title == "Sousou no Frieren"
        assert match.num_episodes == 28
        assert match.current_watched_episodes == 5
        assert match.current_status == "watching"
        assert "Frieren: Beyond Journey's End" in match.synonyms


def test_update_watch_status_success():
    sample_resp = {
        "status": "watching",
        "num_episodes_watched": 6,
        "score": 0,
        "is_rewatching": False,
    }

    client = MALClient(token_getter=lambda: "fake_token")

    with patch("urllib.request.urlopen", return_value=_make_mock_response(200, sample_resp)) as mock_urlopen:
        result = client.update_watch_status(52991, 6, status="watching")
        assert result["num_episodes_watched"] == 6

        # Verify PUT request details
        call_args = mock_urlopen.call_args[0]
        req = call_args[0]
        assert req.method == "PUT"
        assert "52991/my_list_status" in req.full_url
        assert req.data == b"num_watched_episodes=6&status=watching"
        assert req.headers["Authorization"] == "Bearer fake_token"
        assert req.get_header("Content-type") == "application/x-www-form-urlencoded"


def test_token_refresh_on_401():
    token_state = {"token": "expired_token", "refreshed": False}

    def token_getter():
        return token_state["token"]

    def token_refresher():
        token_state["token"] = "new_valid_token"
        token_state["refreshed"] = True
        return "new_valid_token"

    client = MALClient(token_getter=token_getter, token_refresher=token_refresher)

    # First call returns 401, second call returns 200
    err_401 = urllib.error.HTTPError(
        url="http://test", code=401, msg="Unauthorized", hdrs={}, fp=io.BytesIO(b'{"error":"invalid_token"}')
    )
    success_resp = _make_mock_response(200, {"data": []})

    with patch("urllib.request.urlopen", side_effect=[err_401, success_resp]):
        results = client.search_anime("Test")
        assert results == []
        assert token_state["refreshed"] is True
        assert token_state["token"] == "new_valid_token"


def test_401_without_refresher_raises_mal_auth_error():
    client = MALClient(token_getter=lambda: "expired_token", token_refresher=None)

    err_401 = urllib.error.HTTPError(
        url="http://test", code=401, msg="Unauthorized", hdrs={}, fp=io.BytesIO(b'{"error":"invalid_token"}')
    )

    with patch("urllib.request.urlopen", side_effect=err_401):
        with pytest.raises(MALAuthError):
            client.search_anime("Test")


def test_429_rate_limit_retry_and_exhaustion():
    client = MALClient(token_getter=lambda: "token")

    err_429 = urllib.error.HTTPError(
        url="http://test", code=429, msg="Too Many Requests", hdrs={"Retry-After": "0.01"}, fp=io.BytesIO(b"")
    )

    # 4 consecutive 429s -> exhausts max 3 retries, raises MALRateLimitError
    with patch("urllib.request.urlopen", side_effect=[err_429, err_429, err_429, err_429]):
        with patch("time.sleep", return_value=None):
            with pytest.raises(MALRateLimitError):
                client.search_anime("RateLimited")


def test_5xx_server_error_retry():
    client = MALClient(token_getter=lambda: "token")

    err_500 = urllib.error.HTTPError(
        url="http://test", code=500, msg="Internal Error", hdrs={}, fp=io.BytesIO(b"")
    )

    with patch("urllib.request.urlopen", side_effect=[err_500, err_500, err_500]):
        with patch("time.sleep", return_value=None):
            with pytest.raises(MALServerError):
                client.search_anime("ServerError")
