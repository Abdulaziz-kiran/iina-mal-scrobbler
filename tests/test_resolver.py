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


def test_resolver_tv_vs_movie_ep2():
    """When watching episode 2+, a TV series candidate must defeat a 1-episode movie candidate."""
    parsed = ParsedAnime(title="Jujutsu Kaisen", episode=2, raw_filename="[Group] Jujutsu Kaisen - 02.mkv")
    cand_tv = AnimeMatch(mal_id=40748, title="Jujutsu Kaisen", media_type="tv", num_episodes=24, score=0.0)
    cand_movie = AnimeMatch(mal_id=48561, title="Jujutsu Kaisen 0 the Movie", media_type="movie", num_episodes=1, score=0.0)

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed, [cand_tv, cand_movie])

    assert outcome.match is not None
    assert outcome.match.mal_id == cand_tv.mal_id
    assert outcome.is_ambiguous is False


def test_resolver_movie_ep1_allowed():
    """A standalone movie watched as episode 1 must be resolvable without blanket movie penalties."""
    parsed = ParsedAnime(title="Kimi no Na wa", episode=1, raw_filename="Kimi no Na wa - 01.mkv")
    cand_movie = AnimeMatch(
        mal_id=32281,
        title="Kimi no Na wa.",
        media_type="movie",
        num_episodes=1,
        score=0.0,
        synonyms=["Your Name."],
    )

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed, [cand_movie])

    assert outcome.match is not None
    assert outcome.match.mal_id == 32281
    assert outcome.match.score >= 0.85
    assert outcome.is_ambiguous is False


def test_resolver_season_in_synonyms():
    """Season indicator found in synonyms must satisfy season requirement and avoid penalties."""
    parsed = ParsedAnime(title="My Hero Academia", season=2, episode=1, raw_filename="My Hero Academia S02E01.mkv")
    cand_s2 = AnimeMatch(
        mal_id=33486,
        title="Boku no Hero Academia",
        media_type="tv",
        num_episodes=25,
        score=0.0,
        synonyms=["My Hero Academia Season 2", "Boku no Hero Academia 2nd Season"],
    )

    resolver = AnimeResolver()
    outcome = resolver.resolve(parsed, [cand_s2])

    assert outcome.match is not None
    assert outcome.match.mal_id == 33486
    assert outcome.match.score >= 0.85
    assert outcome.is_ambiguous is False

