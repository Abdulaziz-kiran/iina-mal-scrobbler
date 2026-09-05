"""Tests for logging and secret redaction."""

from core.logging import redact_secrets


def test_redact_secrets() -> None:
    secret_token = "Bearer 1234567890abcdef1234567890"
    message = f"Sending request with {secret_token} to MAL API"
    redacted = redact_secrets(message)
    assert "1234567890abcdef1234567890" not in redacted
    assert "Bearer <REDACTED>" in redacted

    code_msg = 'Received code: "abcdef1234567890abcdef" for exchange'
    redacted_code = redact_secrets(code_msg)
    assert "abcdef1234567890abcdef" not in redacted_code
    assert "<REDACTED>" in redacted_code
