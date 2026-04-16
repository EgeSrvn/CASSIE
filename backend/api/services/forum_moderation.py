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


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


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


def contains_blocked_language(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    sanitized = _strip_whitelist_words(normalized)
    tokens = _tokenize(sanitized)
    banned_words = _banned_words_casefolded()
    return any(token in banned_words for token in tokens)


def validate_forum_text(*parts: str) -> None:
    combined = " ".join(part for part in parts if part)
    if contains_blocked_language(combined):
        raise ValueError(
            "Forum posts cannot include slurs or explicit abusive profanity. "
            "Please rephrase and try again."
        )
