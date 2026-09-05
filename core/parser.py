"""Deterministic filename parser for torrent and fansub anime video files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Tuple

from core.models import NumberingType, ParsedAnime

# Valid video file extensions
VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".webm",
    ".m4v",
    ".ts",
    ".mov",
}

# Hex checksum / CRC32 pattern, e.g. [ABCD1234], (12345678)
_CRC_PATTERN = re.compile(r"[\(\[](?:[0-9a-fA-F]{8})[\)\]]")

# Release group / fansub brackets at the start: ^[Group Name] or ^(Group Name)
_INITIAL_BRACKET_PATTERN = re.compile(r"^\s*([\[\(])([^\]\)]+)([\]\)])\s*")

# Brackets containing non-title technical metadata
_TECHNICAL_TAGS_PATTERN = re.compile(
    r"[\[\(]"
    r"[^\]\)]*?"
    r"(?:"
    r"\b\d{3,4}[pi]\b|\b4k\b|\buhd\b|"
    r"\bx264\b|\bx265\b|\bh\.?264\b|\bh\.?265\b|\bhevc\b|\bav1\b|\bxvid\b|\bdivx\b|\b10bit\b|\b8bit\b|\bhi10p\b|"
    r"\baac\b|\bflac\b|\bac3\b|\bdts\b|\bmp3\b|\beac3\b|\bopus\b|"
    r"\bweb-?dl\b|\bweb-?rip\b|\bbd-?rip\b|\bbluray\b|\bblu-ray\b|\bdvd-?rip\b|\bhdtv\b|\btv-?rip\b|\braws?\b|"
    r"\bre-?pack\b|\bremux\b|\bmultiple\s+subtitles?\b|\bmulti-?subs?\b"
    r")"
    r"[^\]\)]*?"
    r"[\]\)]",
    re.IGNORECASE,
)

# Individual standalone tags without brackets (e.g. in dot-separated filenames)
_STANDALONE_TAGS = [
    re.compile(r"\b(?:480|576|720|1080|1440|2160)[pi]\b", re.IGNORECASE),
    re.compile(r"\b(?:4k|uhd)\b", re.IGNORECASE),
    re.compile(r"\b(?:x264|x265|h\.?264|h\.?265|hevc|av1|xvid|10bit|8bit)\b", re.IGNORECASE),
    re.compile(r"\b(?:web-?dl|web-?rip|bd-?rip|bluray|blu-ray|dvd-?rip|hdtv)\b", re.IGNORECASE),
    re.compile(r"\b(?:aac|flac|ac3|dts|mp3|eac3|opus)(?:\s*\d\.\d)?\b", re.IGNORECASE),
]

# Season indicators in title, e.g. "2nd Season", "Season 2", "S2"
_SEASON_TEXT_PATTERN = re.compile(
    r"\b(?:(\d+)(?:st|nd|rd|th)\s+season|season\s+(\d+)|s(\d+))\b",
    re.IGNORECASE,
)

# SxxExx pattern: S01E05, S1E5, S02 - E14
_SXXEXX_PATTERN = re.compile(
    r"\bS(\d{1,2})[\s._-]*E(\d{1,4})(?:v\d+)?\b",
    re.IGNORECASE,
)

# Standard fansub delimiter episode: " - 05", " - 1112", " - 05v2", " - #05"
_DASH_EPISODE_PATTERN = re.compile(
    r"(?:\s+-\s+|\s*-\s*)(?:#\s*|EP?\s*)?(\d{1,4})(?:v\d+)?(?=\s*(?:\[|\(|$|\s+-|\s+[A-Za-z]))",
    re.IGNORECASE,
)

# Ep notation: "Ep 05", "Episode 12", "E05"
_EP_PREFIX_PATTERN = re.compile(
    r"\b(?:EPISODE|EP)[\s._-]*(\d{1,4})(?:v\d+)?\b",
    re.IGNORECASE,
)

# Delimited standalone number (e.g. One.Piece.1112.1080p)
_DELIMITED_NUMBER_PATTERN = re.compile(
    r"[\._\s](\d{1,4})(?:v\d+)?[\._\s]",
    re.IGNORECASE,
)


def _clean_separators(text: str) -> str:
    """Normalize dots and underscores to spaces while preserving hyphens."""
    cleaned = text.replace(".", " ").replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_filename(filename_or_path: str) -> ParsedAnime:
    """
    Parse a media filename deterministically.

    Extracts anime title, episode number, season, numbering style, and confidence.
    Never invents episode numbers or performs arbitrary guesses.
    """
    raw_input = filename_or_path
    warnings: list[str] = []

    # 1. Normalize path to base filename
    base_name = os.path.basename(filename_or_path).strip()
    if not base_name:
        return ParsedAnime(
            title="",
            episode=None,
            confidence=0.0,
            raw_filename=raw_input,
            warnings=["Empty filename"],
        )

    # 2. Check and remove extension
    stem, ext = os.path.splitext(base_name)
    ext_lower = ext.lower()
    if ext_lower and ext_lower not in VIDEO_EXTENSIONS:
        return ParsedAnime(
            title="",
            episode=None,
            confidence=0.0,
            raw_filename=raw_input,
            warnings=[f"Non-video extension: {ext}"],
        )

    working = stem

    # 3. Extract and strip release group from the beginning if present
    # Doing this BEFORE tag stripping prevents groups like [Erai-raws] from being swallowed by raw tag patterns
    group_match = _INITIAL_BRACKET_PATTERN.match(working)
    release_group: Optional[str] = None
    if group_match:
        release_group = group_match.group(2).strip()
        working = working[group_match.end():]

    # 4. Strip CRC32 hashes like [1234ABCD]
    working = _CRC_PATTERN.sub("", working)

    # 5. Strip technical metadata in brackets [1080p][x264]...
    working = _TECHNICAL_TAGS_PATTERN.sub("", working)

    # 6. Check for Season indicators inside text (e.g. 2nd Season)
    detected_season: Optional[int] = None
    season_text_match = _SEASON_TEXT_PATTERN.search(working)
    if season_text_match:
        s_num = (
            season_text_match.group(1)
            or season_text_match.group(2)
            or season_text_match.group(3)
        )
        if s_num and s_num.isdigit():
            detected_season = int(s_num)

    # 7. Detect Episode and Season/Episode notation
    detected_episode: Optional[int] = None
    numbering_type = NumberingType.UNKNOWN
    episode_match_span: Optional[Tuple[int, int]] = None

    # Priority A: SxxExx
    sxx_match = _SXXEXX_PATTERN.search(working)
    if sxx_match:
        detected_season = int(sxx_match.group(1))
        detected_episode = int(sxx_match.group(2))
        numbering_type = NumberingType.SEASON_EPISODE
        episode_match_span = sxx_match.span()
    else:
        # Priority B: Standard " - 05" dash pattern
        dash_matches = list(_DASH_EPISODE_PATTERN.finditer(working))
        if dash_matches:
            chosen_match = dash_matches[-1]
            detected_episode = int(chosen_match.group(1))
            episode_match_span = chosen_match.span()
            if detected_episode >= 100:
                numbering_type = NumberingType.ABSOLUTE
            else:
                numbering_type = NumberingType.EPISODE
        else:
            # Priority C: Ep / Episode prefix
            ep_match = _EP_PREFIX_PATTERN.search(working)
            if ep_match:
                detected_episode = int(ep_match.group(1))
                numbering_type = NumberingType.EPISODE
                episode_match_span = ep_match.span()
            else:
                # Priority D: Delimited number in dot-style filenames: One.Piece.1112.1080p
                temp_work = working
                for tag_pattern in _STANDALONE_TAGS:
                    temp_work = tag_pattern.sub(" ", temp_work)

                candidate_nums = []
                for num_match in _DELIMITED_NUMBER_PATTERN.finditer(temp_work):
                    n_val = int(num_match.group(1))
                    # Ignore common year ranges unless plausible absolute episode
                    if 1970 <= n_val <= 2035:
                        continue
                    # Ignore common resolution numbers
                    if n_val in (480, 576, 720, 1080, 1440, 2160):
                        continue
                    candidate_nums.append((n_val, num_match.span()))

                if len(candidate_nums) == 1:
                    detected_episode = candidate_nums[0][0]
                    episode_match_span = candidate_nums[0][1]
                    numbering_type = (
                        NumberingType.ABSOLUTE
                        if detected_episode >= 100
                        else NumberingType.EPISODE
                    )
                elif len(candidate_nums) > 1:
                    warnings.append(
                        f"Multiple ambiguous candidate episode numbers found: {[c[0] for c in candidate_nums]}"
                    )

    # 8. Extract Title based on episode match position
    title_part = ""
    if episode_match_span is not None:
        title_part = working[:episode_match_span[0]]
    else:
        title_part = working

    # 9. Clean standalone tags from title part
    for tag_pattern in _STANDALONE_TAGS:
        title_part = tag_pattern.sub(" ", title_part)

    # Remove trailing/leading brackets/parentheses and clean separators
    title_part = re.sub(r"[\[\]\(\)]", " ", title_part)
    clean_title = _clean_separators(title_part)

    # Strip trailing hyphens from title (e.g. "Frieren - " -> "Frieren")
    clean_title = re.sub(r"\s*-\s*$", "", clean_title).strip()

    # 10. Handle special case: title contains release group if not stripped
    if not clean_title and release_group:
        clean_title = release_group
        warnings.append("Title derived from initial bracket because body was empty")

    # 11. Calculate Confidence
    confidence = 0.0
    if not clean_title:
        warnings.append("Could not extract title")
        confidence = 0.0
    elif detected_episode is None:
        warnings.append("No episode number detected")
        confidence = 0.0
    else:
        confidence = 0.85
        if numbering_type == NumberingType.SEASON_EPISODE:
            confidence = 0.95
        elif numbering_type == NumberingType.EPISODE and release_group:
            confidence = 0.95
        elif numbering_type == NumberingType.ABSOLUTE:
            confidence = 0.90

        if warnings:
            confidence = max(0.0, confidence - 0.20 * len(warnings))

    return ParsedAnime(
        title=clean_title,
        episode=detected_episode,
        season=detected_season,
        numbering=numbering_type,
        confidence=round(confidence, 2),
        raw_filename=raw_input,
        warnings=warnings,
    )
