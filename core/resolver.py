"""Deterministic resolver and ambiguity guard for matching parsed anime to MAL entries."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Optional

from core.config import AMBIGUITY_DELTA_THRESHOLD, MIN_MATCH_CONFIDENCE
from core.models import AnimeMatch, ParsedAnime


def normalize_title(title: str) -> str:
    """Normalize anime title for comparison: lowercase, alphanumeric, unified spaces."""
    cleaned = title.lower()
    # Replace special punctuation with space
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _tokenize(text: str) -> set[str]:
    """Convert normalized title to a set of words."""
    norm = normalize_title(text)
    return {word for word in norm.split() if word}


def calculate_similarity(parsed_title: str, candidate_title: str) -> float:
    """Compute combined token-overlap and sequence-matching similarity score (0.0 - 1.0)."""
    norm_p = normalize_title(parsed_title)
    norm_c = normalize_title(candidate_title)

    if not norm_p or not norm_c:
        return 0.0

    if norm_p == norm_c:
        return 1.0

    # Token overlap (Jaccard similarity)
    tokens_p = _tokenize(norm_p)
    tokens_c = _tokenize(norm_c)

    if not tokens_p or not tokens_c:
        return 0.0

    intersection = tokens_p.intersection(tokens_c)
    union = tokens_p.union(tokens_c)
    jaccard = len(intersection) / len(union)

    # Sequence matcher for order and spelling
    seq_ratio = difflib.SequenceMatcher(None, norm_p, norm_c).ratio()

    # Substring bonus: if parsed title is full prefix or subset
    substring_bonus = 0.0
    if norm_p in norm_c or norm_c in norm_p:
        substring_bonus = 0.10

    score = (0.45 * jaccard) + (0.45 * seq_ratio) + substring_bonus
    return min(1.0, round(score, 3))


def score_candidate(parsed: ParsedAnime, candidate: AnimeMatch) -> float:
    """
    Score a candidate against parsed anime metadata.

    Evaluates primary title, English title, Japanese title, and all synonyms.
    Applies season consistency checks and penalties.
    """
    all_titles = [candidate.title] + candidate.synonyms
    best_similarity = 0.0

    for candidate_str in all_titles:
        sim = calculate_similarity(parsed.title, candidate_str)
        # Also evaluate similarity without season text in candidate if candidate has season
        cand_no_season = re.sub(
            r"\b(?:season\s*\d+|\d+(?:st|nd|rd|th)\s*season|s\d+)\b",
            "",
            candidate_str,
            flags=re.IGNORECASE,
        )
        cand_no_season = re.sub(r"\s+", " ", cand_no_season).strip()
        if cand_no_season:
            sim_no_season = calculate_similarity(parsed.title, cand_no_season)
            sim = max(sim, sim_no_season)

        if sim > best_similarity:
            best_similarity = sim

    # Season check across primary title and all synonyms
    candidate_season: Optional[int] = None
    for cand_text in all_titles:
        c_norm = normalize_title(cand_text)
        cand_season_match = re.search(r"\b(?:season\s*(\d+)|(\d+)(?:st|nd|rd|th)\s*season|s(\d+))\b", c_norm)
        if cand_season_match:
            s_val = cand_season_match.group(1) or cand_season_match.group(2) or cand_season_match.group(3)
            if s_val and s_val.isdigit():
                candidate_season = int(s_val)
                break

    if parsed.season is not None:
        if candidate_season is not None:
            if parsed.season == candidate_season:
                best_similarity = min(1.0, best_similarity + 0.10)
            else:
                # Season mismatch penalty
                best_similarity = max(0.0, best_similarity - 0.40)
        else:
            # Parsed wants season 2+, but candidate has no season indicator -> slight penalty if season > 1
            if parsed.season > 1:
                best_similarity = max(0.0, best_similarity - 0.15)
    else:
        # Parsed has no season, but candidate is Season 2, 3, etc. -> slight penalty
        if candidate_season is not None and candidate_season > 1:
            best_similarity = max(0.0, best_similarity - 0.20)

    # Episode bounds and media_type check:
    # 1. Movie guard: If watching episode > 1, a 1-episode movie cannot be the target
    if parsed.episode is not None and parsed.episode > 1:
        if candidate.media_type == "movie" or candidate.num_episodes == 1:
            best_similarity = max(0.0, best_similarity - 0.40)

    # 2. Episode bounds check for series
    if candidate.num_episodes > 0 and parsed.episode is not None:
        if parsed.episode > candidate.num_episodes + 5:
            # Probably an absolute numbering targeting a sequel
            best_similarity = max(0.0, best_similarity - 0.25)

    return round(best_similarity, 3)


@dataclass
class ResolverOutcome:
    """Result of resolving candidates against a parsed anime."""

    match: Optional[AnimeMatch]
    is_ambiguous: bool
    reason: str
    candidates_scored: list[tuple[AnimeMatch, float]]


class AnimeResolver:
    """Ambiguity-safe resolver for anime search candidates."""

    def __init__(
        self,
        min_confidence: float = MIN_MATCH_CONFIDENCE,
        ambiguity_threshold: float = AMBIGUITY_DELTA_THRESHOLD,
    ) -> None:
        self.min_confidence = min_confidence
        self.ambiguity_threshold = ambiguity_threshold

    def resolve(self, parsed: ParsedAnime, candidates: list[AnimeMatch]) -> ResolverOutcome:
        """Evaluate and select the best candidate or declare ambiguity/no match."""
        if not candidates:
            return ResolverOutcome(
                match=None,
                is_ambiguous=False,
                reason="No candidate results provided by MAL search.",
                candidates_scored=[],
            )

        scored: list[tuple[AnimeMatch, float]] = []
        for cand in candidates:
            score = score_candidate(parsed, cand)
            scored.append((cand, score))

        # Sort descending by score
        scored.sort(key=lambda x: x[1], reverse=True)

        best_candidate, best_score = scored[0]

        # Check if best score meets minimum confidence
        if best_score < self.min_confidence:
            return ResolverOutcome(
                match=None,
                is_ambiguous=False,
                reason=f"Best candidate '{best_candidate.title}' score {best_score:.2f} is below threshold {self.min_confidence:.2f}.",
                candidates_scored=scored,
            )

        # Ambiguity check: if multiple candidates are close to each other
        if len(scored) > 1:
            second_candidate, second_score = scored[1]
            if second_score >= self.min_confidence:
                score_delta = best_score - second_score
                if score_delta < self.ambiguity_threshold:
                    return ResolverOutcome(
                        match=None,
                        is_ambiguous=True,
                        reason=(
                            f"Ambiguous match between '{best_candidate.title}' ({best_score:.2f}) "
                            f"and '{second_candidate.title}' ({second_score:.2f}). Delta {score_delta:.2f} < {self.ambiguity_threshold:.2f}."
                        ),
                        candidates_scored=scored,
                    )

        # Safe unique selection
        best_candidate.score = best_score
        return ResolverOutcome(
            match=best_candidate,
            is_ambiguous=False,
            reason=f"Selected '{best_candidate.title}' with high confidence {best_score:.2f}.",
            candidates_scored=scored,
        )
