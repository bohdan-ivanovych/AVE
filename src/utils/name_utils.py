"""Utility helpers for deriving human-friendly labels from asset filenames."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import re

# Common patterns that appear inside our asset filenames
_SUBJECT_PATTERN = re.compile(
    r"(subject|sub|main|hero|person|model|item|input)[_\-]?(\d+)",
    re.IGNORECASE,
)
_REFERENCE_PATTERN = re.compile(
    r"(reference|ref|style|background|bg|secondary)[_\-]?(\d+)",
    re.IGNORECASE,
)
_PHOTO_PATTERN = re.compile(
    r"(photo|shot|img|image|picture|pic)[_\-]?(\d+)",
    re.IGNORECASE,
)
_GENERIC_NUMBER = re.compile(r"(?:^|[_-])(w)(\d+)(?:$|[_-])", re.IGNORECASE)


def _normalize_number(value: str) -> str:
    """Strip leading zeroes while keeping the original string fallback."""
    try:
        return str(int(value))
    except ValueError:
        return value


def _match_label(stem: str, pattern: re.Pattern, prefix: str) -> Optional[str]:
    """Try to match a label and return formatted text."""
    match = pattern.search(stem)
    if not match:
        return None
    number = _normalize_number(match.group(2))
    return f"{prefix} {number}"


def describe_media_name(path: Path) -> str:
    """Return a friendly label such as 'Subject 1 · Photo 5' for a file."""
    stem = path.stem.lower()
    tokens: List[str] = []

    subject = _match_label(stem, _SUBJECT_PATTERN, "Subject")
    if subject:
        tokens.append(subject)

    reference = _match_label(stem, _REFERENCE_PATTERN, "Reference")
    if reference and reference not in tokens:
        tokens.append(reference)

    photo = _match_label(stem, _PHOTO_PATTERN, "Photo")
    if photo:
        tokens.append(photo)

    if not tokens:
        generic = _match_label(stem, _GENERIC_NUMBER, "Slot")
        if generic:
            tokens.append(generic)

    if not tokens:
        pretty = stem.replace("_", " ").replace("-", " ").strip()
        tokens.append(pretty.title() if pretty else path.stem)

    return " · ".join(tokens)


def build_pair_label(paths: List[Path]) -> str:
    """Create a combined label for multiple image paths."""
    if not paths:
        return "Untitled Pair"
    labels = [describe_media_name(p) for p in paths if p]
    if not labels:
        return "Untitled Pair"
    return " + ".join(labels[:2]) + (" +" if len(labels) > 2 else "")



