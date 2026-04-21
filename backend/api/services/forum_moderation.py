from __future__ import annotations

import re
from functools import lru_cache


_CUSTOM_BANNED_WORDS = [
    "fuck",
    "motherfucker",
    "shit",
    "bullshit",
    "bitch",
    "asshole",
    "dickhead",
    "cunt",
    "slut",
    "whore",
    "retard",
    "faggot",
    "nigger",
    "nigga",
    "kike",
    "spic",
    "chink",
    "tranny",
]

_WHITELIST_WORDS = [
    "cocky",
]

_LEETSPEAK_TRANSLATION = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
        "!": "i",
        "+": "t",
    }
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_leetspeak(value: str) -> str:
    return (value or "").casefold().translate(_LEETSPEAK_TRANSLATION)


@lru_cache(maxsize=1)
def _banned_words_casefolded() -> set[str]:
    return {word.casefold() for word in _CUSTOM_BANNED_WORDS}


@lru_cache(maxsize=1)
def _whitelist_words_casefolded() -> set[str]:
    return {word.casefold() for word in _WHITELIST_WORDS}


def _strip_whitelist_words(text: str) -> str:
    sanitized = text
    for allowed in _whitelist_words_casefolded():
        sanitized = re.sub(rf"(?i)\b{re.escape(allowed)}\b", " ", sanitized)
    return sanitized


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.casefold())


@lru_cache(maxsize=1)
def _blocked_language_patterns() -> tuple[re.Pattern[str], ...]:
    patterns: list[re.Pattern[str]] = []
    for word in _banned_words_casefolded():
        pieces = [rf"{re.escape(char)}+" for char in word]
        body = r"[\W_]*".join(pieces)
        patterns.append(re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE))
    return tuple(patterns)


def contains_blocked_language(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    normalized_leetspeak = _normalize_leetspeak(normalized)
    sanitized = _strip_whitelist_words(normalized_leetspeak)
    tokens = _tokenize(sanitized)
    banned_words = _banned_words_casefolded()
    if any(token in banned_words for token in tokens):
        return True

    return any(pattern.search(sanitized) for pattern in _blocked_language_patterns())


def validate_public_text(*parts: str, context_label: str = "Posts") -> None:
    combined = " ".join(part for part in parts if part)
    if contains_blocked_language(combined):
        raise ValueError(
            f"{context_label} cannot include slurs or explicit abusive profanity. "
            "Please rephrase and try again."
        )


def validate_forum_text(*parts: str) -> None:
    validate_public_text(*parts, context_label="Forum posts")


def validate_community_text(*parts: str) -> None:
    validate_public_text(*parts, context_label="Community posts")
