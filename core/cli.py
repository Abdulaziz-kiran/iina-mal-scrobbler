"""Command-line interface for iina-mal-scrobbler."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Optional

from core import __version__
from core.auth import get_valid_access_token, login_flow, logout, refresh_tokens
from core.config import (
    CONFIG_DIR,
    DATABASE_PATH,
    KEYCHAIN_ACCOUNT_ACCESS,
    LOG_FILE,
    get_client_id,
    load_config,
    set_client_id,
)
from core.keychain import get_token
from core.logger import get_logger, setup_logging
from core.mal_api import MALAPIError, MALClient
from core.models import ScrobbleResult, ScrobbleStatus
from core.parser import parse_filename
from core.scrobbler import Scrobbler
from core.storage import Storage

logger = get_logger()


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="mal-scrobbler",
        description="Automatic MyAnimeList scrobbler for IINA and mpv on macOS",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # scrobble
    scrobble_cmd = subparsers.add_parser("scrobble", help="Scrobble a media file")
    scrobble_cmd.add_argument("--file", "-f", required=True, help="Path to video file")
    scrobble_cmd.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # parse (dry-run parser test)
    parse_cmd = subparsers.add_parser("parse", help="Parse a filename without contacting MAL")
    parse_cmd.add_argument("--file", "-f", required=True, help="Path or filename to parse")
    parse_cmd.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # auth
    auth_cmd = subparsers.add_parser("auth", help="Manage MyAnimeList authentication")
    auth_sub = auth_cmd.add_subparsers(dest="auth_action", help="Auth action")
    auth_sub.add_parser("login", help="Initiate OAuth PKCE login in browser")
    auth_sub.add_parser("status", help="Check current authentication status")
    auth_sub.add_parser("logout", help="Clear tokens from macOS Keychain")
    auth_sub.add_parser("refresh", help="Force refresh of access token")

    # config
    config_cmd = subparsers.add_parser("config", help="Manage configuration options")
    config_sub = config_cmd.add_subparsers(dest="config_action", help="Config action")
    set_id_cmd = config_sub.add_parser("set-client-id", help="Set custom MAL API Client ID")
    set_id_cmd.add_argument("client_id", help="MyAnimeList Client ID")
    config_sub.add_parser("show", help="Display current non-secret configuration")

    # retry-pending
    retry_cmd = subparsers.add_parser("retry-pending", help="Retry due offline pending scrobble jobs")
    retry_cmd.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # doctor
    subparsers.add_parser("doctor", help="Run diagnostic health checks")

    return parser


def handle_scrobble(file_path: str, as_json: bool) -> int:
    """Execute scrobble pipeline for a video file."""
    token_getter = get_valid_access_token
    token_refresher = refresh_tokens
    client = MALClient(token_getter=token_getter, token_refresher=token_refresher)
    storage = Storage()
    scrobbler = Scrobbler(api_client=client, storage=storage)

    result = scrobbler.scrobble_file(file_path)

    if as_json:
        print(json.dumps(result.to_dict()))
    else:
        if result.success:
            print(f"✓ [{result.status.value.upper()}] {result.anime_title} (Ep. {result.episode}): {result.reason}")
        else:
            print(f"✗ [{result.status.value.upper()}]: {result.reason}")

    return 0 if result.success else 1


def handle_parse(file_path: str, as_json: bool) -> int:
    """Parse filename and display extraction details."""
    parsed = parse_filename(file_path)
    if as_json:
        print(json.dumps(parsed.to_dict(), indent=2))
    else:
        print(f"Raw Input:   {parsed.raw_filename}")
        print(f"Title:       {parsed.title}")
        print(f"Episode:     {parsed.episode}")
        print(f"Season:      {parsed.season}")
        print(f"Numbering:   {parsed.numbering.value}")
        print(f"Confidence:  {parsed.confidence:.2f}")
        if parsed.warnings:
            print(f"Warnings:    {', '.join(parsed.warnings)}")
    return 0


def handle_retry_pending(as_json: bool) -> int:
    """Process due offline pending jobs."""
    token_getter = get_valid_access_token
    token_refresher = refresh_tokens
    client = MALClient(token_getter=token_getter, token_refresher=token_refresher)
    storage = Storage()
    scrobbler = Scrobbler(api_client=client, storage=storage)

    count = scrobbler.retry_pending_jobs()
    stats = storage.get_stats()

    if as_json:
        print(json.dumps({"processed_count": count, "remaining_pending": stats["pending_jobs"]}))
    else:
        print(f"Processed {count} pending scrobbles. ({stats['pending_jobs']} remaining in queue)")
    return 0


def handle_auth(action: Optional[str]) -> int:
    """Handle auth actions."""
    if action == "login":
        success = login_flow()
        return 0 if success else 1
    elif action == "status":
        token = get_valid_access_token()
        if token:
            print("✓ Authenticated: Access token present in macOS Keychain.")
            return 0
        else:
            print("✗ Not authenticated: No active token found. Run 'mal-scrobbler auth login'.")
            return 1
    elif action == "logout":
        logout()
        return 0
    elif action == "refresh":
        print("Refreshing token...")
        new_tok = refresh_tokens()
        if new_tok:
            print("✓ Token refreshed successfully.")
            return 0
        else:
            print("✗ Failed to refresh token.")
            return 1
    else:
        print("Invalid auth command. Use 'mal-scrobbler auth --help'.")
        return 1


def handle_config(action: Optional[str], args: argparse.Namespace) -> int:
    """Handle config actions."""
    if action == "set-client-id":
        set_client_id(args.client_id)
        print("✓ MAL Client ID updated.")
        return 0
    elif action == "show":
        cfg = load_config()
        cid = get_client_id()
        print("Current Configuration:")
        print(f"  Config Directory: {CONFIG_DIR}")
        print(f"  Database Path:    {DATABASE_PATH}")
        print(f"  Log File:         {LOG_FILE}")
        print(f"  Client ID:        {cid or '(none configured)'}")
        return 0
    else:
        print("Invalid config command. Use 'mal-scrobbler config --help'.")
        return 1


def handle_doctor() -> int:
    """Execute complete system diagnostic checks."""
    print("Running iina-mal-scrobbler doctor diagnostics...\n")
    all_ok = True

    # 1. Operating System
    os_name = platform.system()
    if os_name == "Darwin":
        print("  [OK] OS: macOS detected.")
    else:
        print(f"  [ERROR] OS: {os_name} detected. This utility requires macOS.")
        all_ok = False

    # 2. Python Version
    py_ver = sys.version.split()[0]
    if sys.version_info >= (3, 9):
        print(f"  [OK] Python: {py_ver} (>= 3.9).")
    else:
        print(f"  [ERROR] Python: {py_ver}. Version 3.9 or newer is required.")
        all_ok = False

    # 3. Config & Log Directories
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] Config Directory: {CONFIG_DIR} (writable).")
    except Exception as err:
        print(f"  [ERROR] Config Directory: Cannot write to {CONFIG_DIR}: {err}")
        all_ok = False

    # 4. SQLite Database
    try:
        storage = Storage()
        stats = storage.get_stats()
        print(f"  [OK] Database: SQLite accessible ({stats['cached_anime']} cached, {stats['recorded_scrobbles']} scrobbles, {stats['pending_jobs']} pending).")
    except Exception as err:
        print(f"  [ERROR] Database: SQLite error: {err}")
        all_ok = False

    # 5. macOS Keychain Access
    try:
        # Check security tool availability
        token = get_token(KEYCHAIN_ACCOUNT_ACCESS)
        print("  [OK] macOS Keychain: 'security' command accessible.")
        if token:
            print("  [OK] Authentication: Active token found in Keychain.")
        else:
            print("  [WARNING] Authentication: Not logged in. Run 'mal-scrobbler auth login'.")
    except Exception as err:
        print(f"  [ERROR] macOS Keychain: Error querying Keychain: {err}")
        all_ok = False

    # 6. mpv / IINA Scripts Directory
    mpv_scripts = Path.home() / ".config" / "mpv" / "scripts"
    lua_file = mpv_scripts / "mal_scrobbler.lua"
    if lua_file.exists():
        print(f"  [OK] IINA/mpv Integration: Lua script installed at {lua_file}.")
    else:
        print(f"  [WARNING] IINA/mpv Integration: Lua script not found at {lua_file}.")

    # 7. Client ID
    cid = get_client_id()
    if cid:
        print(f"  [OK] MAL Client ID: Configured.")
    else:
        print("  [WARNING] MAL Client ID: Not configured. Run 'mal-scrobbler config set-client-id <id>'.")

    # 8. Network reachability to MAL API
    try:
        import urllib.request
        req = urllib.request.Request("https://api.myanimelist.net/v2", headers={"User-Agent": "iina-mal-scrobbler/0.1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            pass
        print("  [OK] Network: MAL API is reachable.")
    except urllib.error.HTTPError:
        # 401/403 or similar still means network connects to MAL
        print("  [OK] Network: MAL API server reached.")
    except Exception as err:
        print(f"  [WARNING] Network: Could not connect to MAL API: {err}")

    print("\nDiagnostic complete.")
    return 0 if all_ok else 1


def main(argv: Optional[list[str]] = None) -> int:
    """Main entrypoint for CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(debug=args.debug)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "scrobble":
        return handle_scrobble(args.file, args.json)
    elif args.command == "parse":
        return handle_parse(args.file, args.json)
    elif args.command == "auth":
        return handle_auth(args.auth_action)
    elif args.command == "config":
        return handle_config(args.config_action, args)
    elif args.command == "retry-pending":
        return handle_retry_pending(args.json)
    elif args.command == "doctor":
        return handle_doctor()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
