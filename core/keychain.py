"""macOS Keychain interface for secure token storage without plaintext secrets."""

from __future__ import annotations

import subprocess
from typing import Optional

from core.config import KEYCHAIN_ACCOUNT_ACCESS, KEYCHAIN_ACCOUNT_REFRESH, KEYCHAIN_SERVICE
from core.logging import get_logger

logger = get_logger()


def set_token(account: str, token: str, service: str = KEYCHAIN_SERVICE) -> bool:
    """
    Store token in macOS Keychain.

    Pipes the secret directly via stdin to prevent command-line argument exposure in process lists.
    """
    if not token.strip():
        return False

    cmd = [
        "security",
        "add-generic-password",
        "-U",
        "-s",
        service,
        "-a",
        account,
        "-w",
    ]
    # security CLI with -w prompts for password twice on stdin
    stdin_data = f"{token}\n{token}\n".encode("utf-8")

    try:
        proc = subprocess.run(
            cmd,
            input=stdin_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            logger.error("Failed to save token to Keychain: %s", proc.stderr.decode("utf-8", errors="replace"))
            return False
        return True
    except Exception as err:
        logger.error("Exception invoking security CLI: %s", err)
        return False


def get_token(account: str, service: str = KEYCHAIN_SERVICE) -> Optional[str]:
    """Retrieve token from macOS Keychain."""
    cmd = [
        "security",
        "find-generic-password",
        "-s",
        service,
        "-a",
        account,
        "-w",
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8").strip()
    except Exception as err:
        logger.error("Exception retrieving token from Keychain: %s", err)
        return None


def delete_token(account: str, service: str = KEYCHAIN_SERVICE) -> bool:
    """Delete token from macOS Keychain."""
    cmd = [
        "security",
        "delete-generic-password",
        "-s",
        service,
        "-a",
        account,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return proc.returncode == 0
    except Exception as err:
        logger.error("Exception deleting token from Keychain: %s", err)
        return False


def clear_all_tokens(service: str = KEYCHAIN_SERVICE) -> None:
    """Remove access and refresh tokens from Keychain."""
    delete_token(KEYCHAIN_ACCOUNT_ACCESS, service)
    delete_token(KEYCHAIN_ACCOUNT_REFRESH, service)
