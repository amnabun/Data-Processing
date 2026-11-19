"""Shared value objects and validation rules."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping


class DataError(ValueError):
    """An input or data error that can be shown directly to the user."""


def parse_rating_bound(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise DataError("Rating bounds must be whole numbers.") from exc


class TimeControl(str, Enum):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"


def classify_time_control(value: str) -> TimeControl | None:
    """Return the coursework category, or None for an excluded time control."""
    if value == "-":  # Correspondence games have no clock.
        return None
    if not re.fullmatch(r"[0-9]+\+[0-9]+", value):
        raise DataError("TimeControl must contain non-negative seconds as initial+increment.")
    initial, increment = map(int, value.split("+"))
    duration = initial + 40 * increment
    for lower, upper, category in (
        (30, 180, TimeControl.BULLET),
        (180, 480, TimeControl.BLITZ),
        (480, 1500, TimeControl.RAPID),
    ):
        if lower <= duration < upper:
            return category
    return None


def required_text(headers: Mapping[str, str], key: str) -> str:
    value = headers.get(key, "").strip()
    if not value or value in {"?", "-"} or any(ord(c) < 32 for c in value):
        raise DataError(f"Missing or invalid {key}.")
    return value


def integer_header(headers: Mapping[str, str], key: str) -> int:
    value = required_text(headers, key)
    if not re.fullmatch(r"[+-]?[0-9]+", value):
        raise DataError(f"{key} must be an integer.")
    number = int(value)
    if not -(2**31) <= number < 2**31:
        raise DataError(f"{key} is outside the supported integer range.")
    return number


@dataclass(frozen=True)
class Game:
    white: str
    black: str
    white_pre: int
    black_pre: int
    white_post: int
    black_post: int
    game_rating: float
    opening: str
    time_control: str
    played_at: str

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "Game | None":
        category = classify_time_control(headers.get("TimeControl", ""))
        if category is None:
            return None
        white = required_text(headers, "White")
        black = required_text(headers, "Black")
        if white == black:
            raise DataError("A game must have two different players.")
        white_pre = integer_header(headers, "WhiteElo")
        black_pre = integer_header(headers, "BlackElo")
        white_post = white_pre + integer_header(headers, "WhiteRatingDiff")
        black_post = black_pre + integer_header(headers, "BlackRatingDiff")
        if min(white_pre, black_pre, white_post, black_post) < 0:
            raise DataError("Player ratings cannot be negative.")
        opening = required_text(headers, "Opening").split(":", 1)[0].strip()
        if not opening:
            raise DataError("The main opening name is empty.")
        stamp = f"{required_text(headers, 'UTCDate')} {required_text(headers, 'UTCTime')}"
        if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", stamp):
            raise DataError("UTCDate and UTCTime must use YYYY.MM.DD and HH:MM:SS.")
        try:
            timestamp = datetime.strptime(stamp, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise DataError("Invalid UTC date or time.") from exc
        return cls(
            white,
            black,
            white_pre,
            black_pre,
            white_post,
            black_post,
            (white_pre + black_pre) / 2,
            opening,
            category.value,
            timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        )


@dataclass(frozen=True)
class OpeningPopularity:
    opening: str
    games: int
    percentage: float


@dataclass(frozen=True)
class PlayerImprovement:
    player: str
    initial_rating: int
    final_rating: int
    games: int

    @property
    def improvement(self) -> int:
        return self.final_rating - self.initial_rating


@dataclass(frozen=True)
class SimilarPlayer:
    player: str
    distance: float
    details: str
