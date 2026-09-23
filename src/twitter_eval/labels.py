"""Class vocabulary: normalising the CSV labels and building SemIf options."""

from __future__ import annotations

from .config import LabelOption

_ALIASES: dict[str, str] = {
    "positive": "positive",
    "pos": "positive",
    "negative": "negative",
    "neg": "negative",
    "neutral": "neutral",
    "neu": "neutral",
    "irrelevant": "irrelevant",
    "irr": "irrelevant",
}


def normalize_label(raw: str | None) -> str | None:
    """Map a raw column-C value onto a canonical class id, or None if unknown."""
    if raw is None:
        return None
    key = raw.strip().lower().replace(" ", "_")
    return _ALIASES.get(key)


def to_options(labels: list[LabelOption]) -> list[dict[str, str]]:
    """Build the SemIf ``options`` payload (2-16 described options)."""
    if not 2 <= len(labels) <= 16:
        raise ValueError(f"labels must contain 2-16 entries, got {len(labels)}")
    ids = [label.id for label in labels]
    if len(ids) != len(set(ids)):
        raise ValueError("label ids must be unique")
    return [{"id": label.id, "description": label.description} for label in labels]


def label_ids(labels: list[LabelOption]) -> list[str]:
    return [label.id for label in labels]
