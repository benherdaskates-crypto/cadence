"""Typo generation based on a QWERTY layout."""
from __future__ import annotations

import random

_ROWS = ["1234567890-=", "qwertyuiop[]", "asdfghjkl;'", "zxcvbnm,./"]
# Row offsets (in key widths) approximating a real staggered keyboard.
_OFFSETS = [0.0, 0.5, 0.75, 1.25]


def _build_neighbors() -> dict[str, str]:
    pos: dict[str, tuple[int, float]] = {}
    for r, row in enumerate(_ROWS):
        for i, ch in enumerate(row):
            pos[ch] = (r, i + _OFFSETS[r])
    out: dict[str, str] = {}
    for ch, (r, x) in pos.items():
        near = []
        for other, (r2, x2) in pos.items():
            if other == ch:
                continue
            if abs(r2 - r) <= 1 and abs(x2 - x) <= 1.0:
                near.append(other)
        out[ch] = "".join(sorted(near))
    return out


NEIGHBORS = _build_neighbors()
# Typos into letters look more natural than typos into digits/punctuation.
_LETTER_NEIGHBORS = {k: "".join(c for c in v if c.isalpha()) or v for k, v in NEIGHBORS.items()}

TYPO_KINDS = ("neighbor", "double", "swap")
TYPO_WEIGHTS = (0.70, 0.15, 0.15)


def can_typo(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def neighbor_of(ch: str, rng: random.Random) -> str | None:
    """A neighboring key for `ch`, preserving case."""
    options = _LETTER_NEIGHBORS.get(ch.lower())
    if not options:
        return None
    wrong = rng.choice(options)
    return wrong.upper() if ch.isupper() else wrong


def pick_kind(rng: random.Random, swap_possible: bool) -> str:
    kind = rng.choices(TYPO_KINDS, TYPO_WEIGHTS)[0]
    if kind == "swap" and not swap_possible:
        kind = "neighbor"
    return kind
