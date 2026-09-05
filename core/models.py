"""Core data models for iina-mal-scrobbler."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class NumberingType(str, Enum):
    """Classification of how episode numbering appears in the filename."""

    EPISODE = "episode"
    SEASON_EPISODE = "season_episode"
    ABSOLUTE = "absolute"
    UNKNOWN = "unknown"


class ScrobbleStatus(str, Enum):
    """Explicit outcome status for scrobbler operations."""

    SCROBBLED = "scrobbled"
    ALREADY_SYNCED = "already_synced"
    PENDING = "pending"
    AUTH_REQUIRED = "auth_required"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"
    PARSE_FAILED = "parse_failed"
    API_ERROR = "api_error"


@dataclass
class ParsedAnime:
    """Structured representation of a parsed anime video file."""

    title: str
    episode: Optional[int]
    season: Optional[int] = None
    numbering: NumberingType = NumberingType.UNKNOWN
    confidence: float = 0.0
    raw_filename: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert model to JSON-serializable dictionary."""
        data = asdict(self)
        data["numbering"] = self.numbering.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParsedAnime:
        """Instantiate model from dictionary."""
        numbering_val = data.get("numbering", NumberingType.UNKNOWN.value)
        try:
            numbering = NumberingType(numbering_val)
        except ValueError:
            numbering = NumberingType.UNKNOWN

        return cls(
            title=data.get("title", ""),
            episode=data.get("episode"),
            season=data.get("season"),
            numbering=numbering,
            confidence=float(data.get("confidence", 0.0)),
            raw_filename=data.get("raw_filename", ""),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class AnimeMatch:
    """A matched anime candidate from MyAnimeList."""

    mal_id: int
    title: str
    score: float
    media_type: str = "tv"
    num_episodes: int = 0
    current_watched_episodes: int = 0
    current_status: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert model to JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class ScrobbleResult:
    """Outcome report for an attempted scrobble action."""

    success: bool
    status: ScrobbleStatus
    reason: str
    mal_id: Optional[int] = None
    anime_title: Optional[str] = None
    episode: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert model to JSON-serializable dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        return data
