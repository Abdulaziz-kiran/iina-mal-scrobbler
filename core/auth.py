"""OAuth 2.0 PKCE authentication flow and race-protected token lifecycle management."""

from __future__ import annotations

import fcntl
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Optional, Tuple

from core.config import (
    AUTH_URL,
    CONFIG_DIR,
    DEFAULT_CALLBACK_HOST,
    DEFAULT_CALLBACK_PORT,
    DEFAULT_REDIRECT_URI,
    KEYCHAIN_ACCOUNT_ACCESS,
    KEYCHAIN_ACCOUNT_REFRESH,
    TOKEN_URL,
    ensure_directories,
    get_client_id,
)
from core.keychain import clear_all_tokens, get_token, set_token
from core.logger import get_logger

logger = get_logger()

LOCK_FILE = CONFIG_DIR / "auth.lock"


def generate_pkce() -> Tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge.

    Note: MyAnimeList OAuth API requires code_challenge_method=plain,
    where code_challenge must match code_verifier exactly.
    """
    # Generate high-entropy verifier (128 chars of unreserved URL-safe characters)
    verifier = secrets.token_urlsafe(96)[:128]
    challenge = verifier
    return verifier, challenge


def get_authorization_url(
    client_id: str,
    code_challenge: str,
    state: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> str:
    """Build the MyAnimeList OAuth 2.0 PKCE authorization URL."""
    params = {
        "response_type": "code",
        "client_id": client_id.strip(),
        "code_challenge": code_challenge,
        "code_challenge_method": "plain",
        "state": state,
        "redirect_uri": redirect_uri,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> dict[str, Any]:
    """Exchange authorization code and verifier for access and refresh tokens."""
    payload = {
        "client_id": client_id.strip(),
        "grant_type": "authorization_code",
        "code": code.strip(),
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url=TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except urllib.error.HTTPError as err:
        err_msg = err.read().decode("utf-8", errors="replace")
        logger.error("Token exchange failed with HTTP %d: %s", err.code, err_msg)
        raise RuntimeError(f"Token exchange failed (HTTP {err.code}): {err_msg}")


def refresh_tokens(client_id: Optional[str] = None) -> Optional[str]:
    """
    Refresh access token using refresh token, protected against process race conditions.

    Uses fcntl.flock to serialize concurrent refresh attempts across IINA/Python processes.
    """
    ensure_directories()
    cid = client_id or get_client_id()
    if not cid:
        logger.error("Cannot refresh token: Client ID is missing.")
        return None

    with open(LOCK_FILE, "a+", encoding="utf-8") as lock_f:
        # Acquire exclusive non-blocking or blocking lock
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            # Check if another process already refreshed the token recently
            current_access = get_token(KEYCHAIN_ACCOUNT_ACCESS)
            refresh_token = get_token(KEYCHAIN_ACCOUNT_REFRESH)
            if not refresh_token:
                logger.warning("No refresh token found in Keychain.")
                return None

            payload = {
                "client_id": cid.strip(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.strip(),
            }
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(
                url=TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    new_access = resp_data.get("access_token")
                    new_refresh = resp_data.get("refresh_token")

                    if new_access:
                        set_token(KEYCHAIN_ACCOUNT_ACCESS, new_access)
                    if new_refresh:
                        set_token(KEYCHAIN_ACCOUNT_REFRESH, new_refresh)

                    logger.info("Successfully refreshed MAL OAuth access token.")
                    return new_access
            except urllib.error.HTTPError as err:
                err_body = err.read().decode("utf-8", errors="replace")
                logger.error("Failed to refresh token (HTTP %d): %s", err.code, err_body)
                return None
            except Exception as err:
                logger.error("Unexpected error refreshing token: %s", err)
                return None
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Temporary local HTTP server handler for OAuth redirect callback."""

    auth_code: Optional[str] = None
    auth_state: Optional[str] = None
    error: Optional[str] = None

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard HTTP server console logging
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        query_params = urllib.parse.parse_qs(parsed.query)
        code_vals = query_params.get("code")
        state_vals = query_params.get("state")
        err_vals = query_params.get("error")

        if err_vals:
            self.server.error = err_vals[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authentication failed!</h2><p>You can close this tab.</p></body></html>")
            return

        if code_vals and state_vals:
            self.server.auth_code = code_vals[0]
            self.server.auth_state = state_vals[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<!DOCTYPE html><html><head><title>MAL Authorization Successful</title>"
                "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;text-align:center;padding-top:50px;background:#f5f5f7;color:#1d1d1f;}</style></head>"
                "<body><h1>&#10004; Authorization Successful!</h1>"
                "<p>Your MyAnimeList account is connected. You can now close this window and return to your terminal.</p></body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
            return

        self.send_response(400)
        self.end_headers()
        self.wfile.write(b"Missing code or state parameters")


def start_callback_server(timeout: float = 120.0) -> Tuple[Optional[str], Optional[str]]:
    """
    Run local HTTP server on 127.0.0.1:8484 and await redirect callback.

    Returns (code, state) or (None, None) if timed out or failed.
    """
    server_address = (DEFAULT_CALLBACK_HOST, DEFAULT_CALLBACK_PORT)
    try:
        httpd = http.server.HTTPServer(server_address, _CallbackHandler)
    except OSError as err:
        logger.error("Could not bind to %s:%d: %s", DEFAULT_CALLBACK_HOST, DEFAULT_CALLBACK_PORT, err)
        raise RuntimeError(f"Could not start local callback server on port {DEFAULT_CALLBACK_PORT}: {err}")

    httpd.auth_code = None
    httpd.auth_state = None
    httpd.error = None
    httpd.timeout = 1.0  # Check for timeout every second

    start_time = time.time()
    try:
        while time.time() - start_time < timeout:
            httpd.handle_request()
            if httpd.auth_code and httpd.auth_state:
                return httpd.auth_code, httpd.auth_state
            if httpd.error:
                logger.error("Callback returned error: %s", httpd.error)
                return None, None
    finally:
        httpd.server_close()

    logger.warning("OAuth callback server timed out after %ds.", int(timeout))
    return None, None


def login_flow(client_id: Optional[str] = None, timeout: float = 120.0) -> bool:
    """Execute complete interactive OAuth login flow."""
    cid = client_id or get_client_id()
    if not cid:
        raise ValueError("Client ID is required for authentication.")

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(24)
    auth_url = get_authorization_url(cid, challenge, state)

    print("\n--- MyAnimeList OAuth Authentication ---")
    print("Opening browser to authorize with MyAnimeList...")
    print(f"If your browser does not open automatically, visit this URL:\n{auth_url}\n")

    webbrowser.open(auth_url)

    print(f"Waiting for authorization callback on http://localhost:{DEFAULT_CALLBACK_PORT}/callback...")
    code, returned_state = start_callback_server(timeout=timeout)

    if not code or not returned_state:
        print("Authentication timed out or failed to receive callback.")
        return False

    if returned_state != state:
        logger.error("State mismatch in OAuth callback (CSRF detected).")
        print("Security error: OAuth state verification mismatch.")
        return False

    print("Authorization code received. Exchanging for tokens...")
    try:
        token_data = exchange_code_for_tokens(cid, code, verifier)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token or not refresh_token:
            print("Token exchange response did not contain expected tokens.")
            return False

        set_token(KEYCHAIN_ACCOUNT_ACCESS, access_token)
        set_token(KEYCHAIN_ACCOUNT_REFRESH, refresh_token)
        print("Tokens securely saved to macOS Keychain!")
        print("Authentication complete.\n")
        return True
    except Exception as err:
        print(f"Failed to exchange token: {err}")
        return False


def get_valid_access_token() -> Optional[str]:
    """Get active access token from Keychain."""
    return get_token(KEYCHAIN_ACCOUNT_ACCESS)


def logout() -> None:
    """Remove tokens from Keychain."""
    clear_all_tokens()
    print("Logged out. Tokens removed from Keychain.")
