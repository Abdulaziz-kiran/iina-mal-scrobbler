"""Comprehensive test suite for anime filename parsing."""

import pytest
from core.models import NumberingType
from core.parser import parse_filename

# 50+ Representative test cases: (filename, expected_title, expected_episode, expected_season, min_confidence)
TEST_CASES = [
    # 1. Standard Fansub dash format
    ("[SubsPlease] Sousou no Frieren - 28 (1080p) [B65BD86D].mkv", "Sousou no Frieren", 28, None, 0.90),
    ("[SubsPlease] Frieren - 05 (1080p) [ABCD1234].mkv", "Frieren", 5, None, 0.90),
    ("[Erai-raws] Jujutsu Kaisen - 12 [1080p][Multiple Subtitle].mkv", "Jujutsu Kaisen", 12, None, 0.90),
    ("[ASW] Oshi no Ko - 06 [1080p HEVC x265 10Bit][AAC].mkv", "Oshi no Ko", 6, None, 0.90),
    ("[Judas] Vinland Saga - 20 [1080p][HEVC x265 10bit][Multi-Subs].mkv", "Vinland Saga", 20, None, 0.90),
    ("[HorribleSubs] Bleach - 366 [720p].mkv", "Bleach", 366, None, 0.90),
    ("[SubsPlease] Dungeon Meshi - 01 (1080p) [9A8B7C6D].mkv", "Dungeon Meshi", 1, None, 0.90),
    ("[SubsPlease] Solo Leveling - 07 (1080p) [12345678].mkv", "Solo Leveling", 7, None, 0.90),
    ("[SubsPlease] Kaijuu 8-gou - 03 (1080p) [11223344].mkv", "Kaijuu 8-gou", 3, None, 0.90),
    ("[SubsPlease] Mushoku Tensei S2 - 15 (1080p) [55667788].mkv", "Mushoku Tensei S2", 15, 2, 0.90),

    # 2. Season indicators in title
    ("[Erai-raws] Jujutsu Kaisen 2nd Season - 14 [1080p].mkv", "Jujutsu Kaisen 2nd Season", 14, 2, 0.90),
    ("[Judas] Vinland Saga S2 - 20.mkv", "Vinland Saga S2", 20, 2, 0.90),
    ("[SubsPlease] Boku no Hero Academia Season 7 - 04 (1080p) [AABBCCDD].mkv", "Boku no Hero Academia Season 7", 4, 7, 0.90),
    ("[Erai-raws] Kimetsu no Yaiba - Hashira Geiko-hen - 02 [1080p].mkv", "Kimetsu no Yaiba - Hashira Geiko-hen", 2, None, 0.90),
    ("[SubsPlease] Kage no Jitsuryokusha ni Naritakute! 2nd Season - 08 (1080p).mkv", "Kage no Jitsuryokusha ni Naritakute! 2nd Season", 8, 2, 0.90),

    # 3. SxxExx notation
    ("Attack on Titan S04E05 1080p.mkv", "Attack on Titan", 5, 4, 0.90),
    ("Demon Slayer S01E19 1080p WEB-DL x264.mp4", "Demon Slayer", 19, 1, 0.90),
    ("My Hero Academia S06E12.mkv", "My Hero Academia", 12, 6, 0.90),
    ("Steins.Gate.S01E01.1080p.BluRay.mkv", "Steins Gate", 1, 1, 0.90),
    ("Spy.x.Family.S02E03.1080p.CR.WEB-DL.AAC2.0.H.264.mkv", "Spy x Family", 3, 2, 0.90),

    # 4. Absolute numbering for long-running series
    ("[Group] One Piece - 1112 [1080p][WEB-DL][x264].mkv", "One Piece", 1112, None, 0.85),
    ("[SubsPlease] One Piece - 1089 (1080p) [FEDCBA98].mkv", "One Piece", 1089, None, 0.85),
    ("One.Piece.1112.1080p.WEB-DL.mkv", "One Piece", 1112, None, 0.80),
    ("[Group] Detective Conan - 1095 (1080p).mkv", "Detective Conan", 1095, None, 0.85),
    ("[SubsPlease] Boruto - Naruto Next Generations - 293 (1080p).mkv", "Boruto - Naruto Next Generations", 293, None, 0.85),

    # 5. Punctuation, symbols, and special titles
    ("86 - Eighty Six - 11 (1080p).mkv", "86 - Eighty Six", 11, None, 0.80),
    ("3-gatsu no Lion 2nd Season - 45.mkv", "3-gatsu no Lion 2nd Season", 45, 2, 0.80),
    ("[SubsPlease] Bocchi the Rock! - 03 (1080p) [12AB34CD].mkv", "Bocchi the Rock!", 3, None, 0.90),
    ("Bocchi.the.Rock!.-.03.1080p.mkv", "Bocchi the Rock!", 3, None, 0.80),
    ("[SubsPlease] Re Zero kara Hajimeru Isekai Seikatsu 3rd Season - 01 (1080p).mkv", "Re Zero kara Hajimeru Isekai Seikatsu 3rd Season", 1, 3, 0.90),
    ("[SubsPlease] Mob Psycho 100 III - 06 (1080p).mkv", "Mob Psycho 100 III", 6, None, 0.90),
    ("[SubsPlease] Cyberpunk - Edgerunners - 10 (1080p).mkv", "Cyberpunk - Edgerunners", 10, None, 0.90),
    ("[SubsPlease] Chainsaw Man - 12 (1080p).mkv", "Chainsaw Man", 12, None, 0.90),
    ("[SubsPlease] Bleach - Sennen Kessen-hen - 24 (1080p).mkv", "Bleach - Sennen Kessen-hen", 24, None, 0.90),

    # 6. Version suffixes (e.g. 05v2)
    ("[SubsPlease] Sousou no Frieren - 05v2 (1080p).mkv", "Sousou no Frieren", 5, None, 0.85),
    ("[Erai-raws] Wind Breaker - 01v2 [1080p].mkv", "Wind Breaker", 1, None, 0.85),

    # 7. Episode prefix notations ("EP01", "Episode 12")
    ("[Group] Mashle EP05 [1080p].mkv", "Mashle", 5, None, 0.80),
    ("Chainsaw Man Episode 08 1080p.mkv", "Chainsaw Man", 8, None, 0.80),
    ("[Group] Dandadan - Episode 01 [1080p].mkv", "Dandadan", 1, None, 0.85),

    # 8. Leading zeroes and high episode numbers
    ("[Group] Sousou no Frieren - 028.mkv", "Sousou no Frieren", 28, None, 0.85),
    ("[Group] Naruto Shippuden - 500 (1080p).mkv", "Naruto Shippuden", 500, None, 0.85),
    ("[Group] Gintama - 050 [720p].mkv", "Gintama", 50, None, 0.85),
    ("[Group] Hunter x Hunter (2011) - 148 [1080p].mkv", "Hunter x Hunter", 148, None, 0.80),

    # 9. Unicode / Japanese Characters in title
    ("[Group] 葬送のフリーレン - 05 [1080p].mkv", "葬送のフリーレン", 5, None, 0.85),
    ("[Group] 呪術廻戦 - 12 [1080p].mkv", "呪術廻戦", 12, None, 0.85),

    # 10. Path inputs (full absolute macOS path)
    ("/Volumes/Anime/[SubsPlease] Sousou no Frieren - 05 (1080p) [ABCD1234].mkv", "Sousou no Frieren", 5, None, 0.90),
    ("/Users/abdulaziz/Downloads/[Erai-raws] Jujutsu Kaisen 2nd Season - 14.mkv", "Jujutsu Kaisen 2nd Season", 14, 2, 0.90),
    ("/Volumes/External/One.Piece.1112.1080p.WEB-DL.mkv", "One Piece", 1112, None, 0.80),
]


@pytest.mark.parametrize("filename,expected_title,expected_ep,expected_season,min_conf", TEST_CASES)
def test_valid_filename_parsing(filename, expected_title, expected_ep, expected_season, min_conf):
    res = parse_filename(filename)
    assert res.episode == expected_ep, f"Failed episode for '{filename}': got {res.episode}, expected {expected_ep}"
    assert expected_title.lower() in res.title.lower(), f"Failed title for '{filename}': got '{res.title}', expected '{expected_title}'"
    if expected_season is not None:
        assert res.season == expected_season, f"Failed season for '{filename}': got {res.season}, expected {expected_season}"
    assert res.confidence >= min_conf, f"Confidence too low for '{filename}': {res.confidence} < {min_conf}"


# Negative & Adversarial rejection cases: Must NEVER invent an episode number
NEGATIVE_CASES = [
    ("", "Empty filename"),
    ("movie.mp4", "No episode number detected"),
    ("Princess Mononoke (1997) [1080p Bluray].mkv", "Movie without episode"),
    ("Spirited.Away.2001.1080p.BluRay.x264.mkv", "Movie with year"),
    ("Kimi no Na wa (1080p).mkv", "Movie without episode number"),
    ("subtitles.srt", "Non-video extension"),
    ("soundtrack.flac", "Non-video extension"),
    ("notes.nfo", "Non-video extension"),
    ("cover.jpg", "Non-video extension"),
    ("[Group] Complete Series (1080p) [Batch].mkv", "Batch file without episode"),
    ("[Group] Jujutsu Kaisen OST [FLAC].zip", "Non-video extension"),
]


@pytest.mark.parametrize("filename,description", NEGATIVE_CASES)
def test_negative_rejection_cases(filename, description):
    res = parse_filename(filename)
    assert res.episode is None, f"Should reject episode for {description} ('{filename}'), but got {res.episode}"
    assert res.confidence == 0.0 or len(res.warnings) > 0
