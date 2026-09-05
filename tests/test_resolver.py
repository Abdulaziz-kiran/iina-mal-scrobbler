"""Tests for deterministic anime candidate resolution and ambiguity protection."""

from core.models import AnimeMatch, ParsedAnime
from core.resolver import AnimeResolver


def test_exact_match_resolution():
    parsed = ParsedAnime(title="Sousou no Frieren", episode=5, raw_filename="[SubsPlease] Sousou no Frieren - 05.mkv")
    cand1 = AnimeMatch(mal_id=52991, title="Sousou no Frieren", score=0.0, num_episodes=28)
    cand2 = AnimeMatch(mal_id=12345, title="Frieren Mini Anime", score=0.0, num_episodes=10)

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed, [cand1, cand2])

    assert outcome.match is not None
    assert outcome.match.mal_id == 52991
    assert outcome.is_ambiguous is False
    assert outcome.match.score >= 0.90


def test_synonym_english_match():
    parsed = ParsedAnime(title="Frieren Beyond Journey's End", episode=5, raw_filename="Frieren Beyond Journey's End - 05.mkv")
    cand = AnimeMatch(
        mal_id=52991,
        title="Sousou no Frieren",
        score=0.0,
        synonyms=["Frieren: Beyond Journey's End", "Frieren at the Funeral"],
    )

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed, [cand])

    assert outcome.match is not None
    assert outcome.match.mal_id == 52991
    assert outcome.is_ambiguous is False
    assert outcome.match.score >= 0.85


def test_ambiguous_candidates_rejection():
    # Two anime with nearly identical titles and similar scores
    cand_a = AnimeMatch(mal_id=1, title="Attack on Titan Part 1", score=0.0)
    cand_b = AnimeMatch(mal_id=2, title="Attack on Titan Part 2", score=0.0)
    parsed_tie = ParsedAnime(title="Attack on Titan", episode=1)

    resolver = AnimeResolver(min_confidence=0.70, ambiguity_threshold=0.10)
    tie_outcome = resolver.resolve(parsed_tie, [cand_a, cand_b])
    assert tie_outcome.match is None
    assert tie_outcome.is_ambiguous is True
    assert "Ambiguous match" in tie_outcome.reason


def test_low_confidence_rejection():
    parsed = ParsedAnime(title="Completely Unrelated Anime Name XYZ", episode=1)
    cand = AnimeMatch(mal_id=1, title="One Piece", score=0.0)

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed, [cand])

    assert outcome.match is None
    assert outcome.is_ambiguous is False
    assert "below threshold" in outcome.reason


def test_season_awareness():
    parsed_s2 = ParsedAnime(title="Jujutsu Kaisen 2nd Season", episode=14, season=2)
    cand_s1 = AnimeMatch(mal_id=40748, title="Jujutsu Kaisen", score=0.0, num_episodes=24)
    cand_s2 = AnimeMatch(mal_id=51009, title="Jujutsu Kaisen 2nd Season", score=0.0, num_episodes=23)

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed_s2, [cand_s1, cand_s2])

    assert outcome.match is not None
    assert outcome.match.mal_id == 51009
    assert outcome.is_ambiguous is False
