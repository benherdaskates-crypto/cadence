"""Keystroke actions and a virtual editor that models what they do to a text field.

The planner emits a flat list of `Action`s. The same list is replayed either
against the real keyboard (engine.typer) or against `VirtualEditor`, which is
how cursor tracking is verified: if the virtual buffer ends up equal to the
target text, the keystrokes are correct for any editor that follows the
conservative navigation rules in engine.revisions.
"""
from __future__ import annotations

from dataclasses import dataclass

# Key names understood by both the real backend and the virtual editor.
KEYS = {"backspace", "left", "right", "home", "end", "enter", "tab"}


@dataclass(slots=True)
class Action:
    kind: str            # "char" | "key" | "break"
    value: str = ""      # the character, or a key name from KEYS
    delay: float = 0.0   # seconds to wait BEFORE performing the action
    ctrl: bool = False
    shift: bool = False
    note: str = "type"   # type | typo | fix | nav | rethink | revise | break


def is_word_char(c: str) -> bool:
    """ASCII letters and digits only. Accented letters and punctuation are
    deliberately excluded because editors disagree on how Ctrl+Arrow treats them."""
    return c.isascii() and c.isalnum()


def model_ctrl_left(buf: list[str] | str, p: int) -> int:
    """Windows-style Ctrl+Left: skip spaces to the left, then the word."""
    q = p
    while q > 0 and buf[q - 1] == " ":
        q -= 1
    while q > 0 and is_word_char(buf[q - 1]):
        q -= 1
    if q == p and p > 0:
        q = p - 1
    return q


def model_ctrl_right(buf: list[str] | str, p: int) -> int:
    """Windows-style Ctrl+Right: skip the rest of the word, then spaces,
    landing on the start of the next word."""
    n = len(buf)
    q = p
    while q < n and is_word_char(buf[q]):
        q += 1
    while q < n and buf[q] == " ":
        q += 1
    if q == p and p < n:
        q = p + 1
    return q


class VirtualEditor:
    """A minimal plain-text editor: a buffer and a caret."""

    def __init__(self, text: str = "", cursor: int | None = None):
        self.buf: list[str] = list(text)
        self.cursor = len(self.buf) if cursor is None else cursor

    @property
    def text(self) -> str:
        return "".join(self.buf)

    def apply(self, a: Action) -> None:
        if a.kind == "char":
            self.buf.insert(self.cursor, a.value)
            self.cursor += 1
        elif a.kind == "key":
            self._key(a.value, a.ctrl)
        # "break" does nothing to the document

    def _key(self, name: str, ctrl: bool) -> None:
        b, c = self.buf, self.cursor
        if name == "backspace":
            if c > 0:
                del b[c - 1]
                self.cursor = c - 1
        elif name == "enter":
            b.insert(c, "\n")
            self.cursor = c + 1
        elif name == "tab":
            b.insert(c, "\t")
            self.cursor = c + 1
        elif name == "left":
            self.cursor = model_ctrl_left(b, c) if ctrl else max(0, c - 1)
        elif name == "right":
            self.cursor = model_ctrl_right(b, c) if ctrl else min(len(b), c + 1)
        elif name == "home":
            if ctrl:
                self.cursor = 0
            else:
                while self.cursor > 0 and b[self.cursor - 1] != "\n":
                    self.cursor -= 1
        elif name == "end":
            if ctrl:
                self.cursor = len(b)
            else:
                while self.cursor < len(b) and b[self.cursor] != "\n":
                    self.cursor += 1
        else:
            raise ValueError(f"unknown key {name!r}")
