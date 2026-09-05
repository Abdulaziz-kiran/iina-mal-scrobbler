"""Tests for CLI arguments and subcommand execution."""

import json
from unittest.mock import patch

from core.cli import main
from core.models import ScrobbleResult, ScrobbleStatus


def test_cli_parse_json(capsys):
    ret = main(["parse", "--file", "[SubsPlease] Sousou no Frieren - 05.mkv", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["title"] == "Sousou no Frieren"
    assert data["episode"] == 5


def test_cli_config_show(capsys):
    ret = main(["config", "show"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Config Directory:" in captured.out
    assert "Database Path:" in captured.out


def test_cli_scrobble_json(capsys):
    mock_result = ScrobbleResult(
        success=True,
        status=ScrobbleStatus.SCROBBLED,
        reason="Updated episode 5",
        mal_id=52991,
        anime_title="Sousou no Frieren",
        episode=5,
    )
    with patch("core.scrobbler.Scrobbler.scrobble_file", return_value=mock_result):
        ret = main(["scrobble", "--file", "Frieren - 05.mkv", "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["status"] == "scrobbled"
        assert data["episode"] == 5


def test_cli_doctor(capsys):
    ret = main(["doctor"])
    assert ret in (0, 1)
    captured = capsys.readouterr()
    assert "doctor diagnostics" in captured.out
