"""Text helpers: matching people's names written in different ways."""

from __future__ import annotations

import re
import unicodedata

_SEPARATORS = re.compile(r"[\s\-‐-―_.'’]+")


def fold(text: str) -> str:
    """Lower-case, strip accents, collapse spaces/hyphens/dots: ``"PEYROL-KLEIBER Élodie"`` -> ``"peyrol kleiber elodie"``."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SEPARATORS.sub(" ", without_marks.casefold()).strip()


def name_key(name: str) -> str:
    """Order-independent key for a person's name.

    "Thouverez Ludivine", "Ludivine Thouverez" and "THOUVEREZ ludivine" share a key,
    so the same person typed as "Nom Prénom" or "Prénom Nom" is recognised.
    """
    return " ".join(sorted(fold(name).split()))


def split_people(text: str) -> list[str]:
    """Split a legacy free-text people field (newlines, commas, semicolons)."""
    return [part.strip() for part in re.split(r"[\n,;]+", text) if part.strip()]
