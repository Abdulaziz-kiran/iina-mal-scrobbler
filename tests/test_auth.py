"""Tests for OAuth 2.0 PKCE generation, exchange, and token lifecycle."""

import json
import urllib.parse
from unittest.mock import MagicMock, patch

from core.auth import (
    exchange_code_for_tokens,
    generate_pkce,
    get_authorization_url,
    refresh_tokens,
)


def test_pkce_generation():
    verifier, challenge = generate_pkce()
    # MAL plain method requires verifier == challenge
    assert verifier == challenge
    assert 48 <= len(verifier) <= 128
    # Ensure URL safe characters
    assert all(c.isalnum() or c in "-._~" for c in verifier)


def test_authorization_url_builder():
    client_id = "test_client_id_123"
    verifier, challenge = generate_pkce()
    state = "secure_random_state"

    url = get_authorization_url(client_id, challenge, state, "http://localhost:8484/callback")
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "myanimelist.net"
    assert parsed.path == "/v1/oauth2/authorize"
    assert qs["client_id"] == [client_id]
    assert qs["code_challenge"] == [challenge]
    assert qs["code_challenge_method"] == ["plain"]
    assert qs["state"] == [state]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == ["http://localhost:8484/callback"]


def test_exchange_code_for_tokens_success():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "token_type": "Bearer",
        "expires_in": 2678400,
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        tokens = exchange_code_for_tokens(
            client_id="my_id",
            code="auth_code_xyz",
            code_verifier="verifier_abc",
        )
        assert tokens["access_token"] == "mock_access_token"
        assert tokens["refresh_token"] == "mock_refresh_token"

        call_req = mock_urlopen.call_args[0][0]
        assert call_req.method == "POST"
        post_data = urllib.parse.parse_qs(call_req.data.decode("utf-8"))
        assert post_data["client_id"] == ["my_id"]
        assert post_data["code"] == ["auth_code_xyz"]
        assert post_data["code_verifier"] == ["verifier_abc"]


def test_refresh_tokens_flow():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "token_type": "Bearer",
        "expires_in": 2678400,
        "access_token": "refreshed_access_token",
        "refresh_token": "refreshed_refresh_token",
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    with patch("core.auth.get_token", return_value="current_refresh_token"), \
         patch("core.auth.set_token") as mock_set_token, \
         patch("urllib.request.urlopen", return_value=mock_resp):

        new_token = refresh_tokens(client_id="my_id")
        assert new_token == "refreshed_access_token"
        assert mock_set_token.call_count == 2
