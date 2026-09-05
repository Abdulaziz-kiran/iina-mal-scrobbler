"""Tests for core data models."""

from core.models import AnimeMatch, NumberingType, ParsedAnime, ScrobbleResult, ScrobbleStatus


def test_parsed_anime_serialization() -> None:
    anime = ParsedAnime(
        title="Frieren: Beyond Journey's End",
        episode=5,
        season=1,
        numbering=NumberingType.EPISODE,
        confidence=0.95,
        raw_filename="[SubsPlease] Sousou no Frieren - 05.mkv",
        warnings=[],
    )
    data = anime.to_dict()
    assert data["title"] == "Frieren: Beyond Journey's End"
    assert data["episode"] == 5
    assert data["numbering"] == "episode"
    assert data["confidence"] == 0.95

    restored = ParsedAnime.from_dict(data)
    assert restored.title == anime.title
    assert restored.episode == anime.episode
    assert restored.numbering == NumberingType.EPISODE


def test_scrobble_result_serialization() -> None:
    res = ScrobbleResult(
        success=True,
        status=ScrobbleStatus.SCROBBLED,
        reason="Updated to episode 5",
        mal_id=52991,
        anime_title="Sousou no Frieren",
        episode=5,
    )
    data = res.to_dict()
    assert data["success"] is True
    assert data["status"] == "scrobbled"
    assert data["mal_id"] == 52991
    assert data["episode"] == 5


def test_anime_match_model() -> None:
    match = AnimeMatch(
        mal_id=52991,
        title="Sousou no Frieren",
        score=0.98,
        media_type="tv",
        num_episodes=28,
        current_watched_episodes=4,
        current_status="watching",
        synonyms=["Frieren at the Funeral"],
    )
    data = match.to_dict()
    assert data["mal_id"] == 52991
    assert data["synonyms"] == ["Frieren at the Funeral"]
