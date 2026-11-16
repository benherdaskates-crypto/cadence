"""Revise-later support: deferred fixes, rough phrasings, and keyboard navigation.

Cursor tracking rules
---------------------
Different editors (Notepad, Word, browsers, Google Docs) agree on plain
Left/Right arrows moving one character, but disagree on Ctrl+Left/Right around
punctuation, apostrophes and accented letters, and Home/End/Up/Down depend on
visual line wrapping, which we can't see. So navigation only uses:

* Left / Right arrows (always safe).
* Ctrl+Left / Ctrl+Right, but only across spans made of ASCII letters, digits
  and spaces, landing on a word start that sits right after a space/newline
  inside text Cadence typed itself, and (for Ctrl+Right) only when starting
  at or inside a word. These rules were measured against the Win32 EDIT and
  RichEdit controls (tests/real_window_check.py).
* Ctrl+Home / Ctrl+End, only when the user says the document contains nothing
  but Cadence's text ("empty document" setting).
"""
from __future__ import annotations

from dataclasses import dataclass

from .actions import is_word_char, model_ctrl_left, model_ctrl_right

REVISION_AMOUNTS = {
    # share of typos left for later, per-word chance of a rough phrasing,
    # per-word chance of omitting a small word
    "Few":  (0.15, 0.004, 0.003),
    "Some": (0.30, 0.010, 0.006),
    "Many": (0.50, 0.020, 0.010),
}
REVISE_WHEN = ("After paragraphs", "At the end", "Mixed")

# Small words people commonly drop on a first pass and insert later.
OMITTABLE = {"the", "a", "an", "very", "really", "just", "that", "also", "even", "still"}

# Rough-draft alternatives. Typed first, then revised to the real word.
SYNONYMS: dict[str, list[str]] = {
    "important": ["big", "key", "major"], "large": ["big", "huge"], "big": ["large", "huge"],
    "small": ["little", "tiny"], "little": ["small"], "quickly": ["fast", "rapidly"],
    "however": ["but", "though"], "because": ["since", "as"], "many": ["lots of", "a lot of"],
    "often": ["usually", "frequently"], "usually": ["often", "normally"],
    "difficult": ["hard", "tough"], "hard": ["difficult", "tough"], "easy": ["simple"],
    "simple": ["easy", "basic"], "show": ["prove", "reveal"], "shows": ["proves", "reveals"],
    "help": ["assist", "aid"], "helps": ["assists"], "use": ["utilize", "apply"],
    "important.": [], "start": ["begin"], "begin": ["start"], "end": ["finish"],
    "finish": ["end", "complete"], "think": ["believe", "feel"], "believe": ["think"],
    "good": ["great", "nice"], "great": ["good", "excellent"], "bad": ["poor", "awful"],
    "make": ["create", "build"], "makes": ["creates"], "get": ["obtain", "receive"],
    "very": ["really", "quite"], "really": ["very", "truly"], "also": ["too", "as well"],
    "clear": ["obvious", "plain"], "main": ["primary", "key"], "change": ["shift", "alter"],
    "changes": ["shifts"], "idea": ["concept", "notion"], "ideas": ["concepts"],
    "problem": ["issue"], "problems": ["issues"], "result": ["outcome"], "results": ["outcomes"],
    "people": ["folks", "individuals"], "different": ["distinct", "various"],
    "several": ["a few", "some"], "seems": ["appears", "looks"], "maybe": ["perhaps"],
    "perhaps": ["maybe"], "need": ["require"], "needs": ["requires"], "want": ["wish"],
    "find": ["discover"], "found": ["discovered"], "understand": ["grasp", "get"],
    "explain": ["describe"], "example": ["instance"], "especially": ["particularly"],
    "probably": ["likely"], "actually": ["really", "in fact"], "rather": ["instead"],
    "therefore": ["so", "thus"], "although": ["though", "even though"],
    "significant": ["major", "big"], "increase": ["rise", "boost"], "improve": ["better", "boost"],
    "suggests": ["implies", "shows"], "support": ["back", "help"], "allow": ["let", "permit"],
    "allows": ["lets", "permits"], "around": ["about", "roughly"], "about": ["around"],
    "enough": ["sufficient"], "amazing": ["incredible", "great"], "strong": ["powerful"],
    "fast": ["quick"], "quick": ["fast"], "begins": ["starts"], "started": ["began"],
}
SYNONYMS = {k: v for k, v in SYNONYMS.items() if v and k.isalpha()}


def match_case(alt: str, word: str) -> str:
    if word.isupper() and len(word) > 1:
        return alt.upper()
    if word[0].isupper():
        return alt[0].upper() + alt[1:]
    return alt


@dataclass(slots=True)
class PendingFix:
    """buffer[start:start+len(wrong)] == wrong, and should become `right`."""
    start: int
    wrong: str
    right: str
    seq: int
    kind: str


# --------------------------------------------------------------------------
# Navigation planning
# --------------------------------------------------------------------------

def _safe_span(buf, a: int, b: int) -> bool:
    return all(buf[i] == " " or is_word_char(buf[i]) for i in range(a, b))


def safe_ctrl_left(buf, p: int) -> int | None:
    """Where Ctrl+Left lands from p, if every editor would agree; else None."""
    q = model_ctrl_left(buf, p)
    if q >= p or q < 1:
        return None
    if buf[q - 1] not in (" ", "\n"):
        return None
    if not is_word_char(buf[q]):
        return None
    if not _safe_span(buf, q, p):
        return None
    return q


def safe_ctrl_right(buf, p: int) -> int | None:
    # Starting on whitespace is ambiguous: the classic Win32 EDIT control
    # (Notepad-style text boxes) skips the *next* word too. Only jump when the
    # caret is at or inside a word, where every editor agrees.
    if p >= len(buf) or not is_word_char(buf[p]):
        return None
    q = model_ctrl_right(buf, p)
    if q <= p or q >= len(buf):
        return None
    if not is_word_char(buf[q]) or buf[q - 1] != " ":
        return None
    if not _safe_span(buf, p, q):
        return None
    return q


def _direct(buf, a: int, b: int, word_jumps: bool) -> list[tuple[str, bool]]:
    keys: list[tuple[str, bool]] = []
    p = a
    while p > b:
        q = safe_ctrl_left(buf, p) if word_jumps else None
        if q is not None and q >= b:
            keys.append(("left", True))
            p = q
        else:
            keys.append(("left", False))
            p -= 1
    while p < b:
        q = safe_ctrl_right(buf, p) if word_jumps else None
        if q is not None and q <= b:
            keys.append(("right", True))
            p = q
        else:
            keys.append(("right", False))
            p += 1
    return keys


def plan_navigation(buf, a: int, b: int, word_jumps: bool = True,
                    doc_anchors: bool = False) -> list[tuple[str, bool]]:
    """Key presses (name, ctrl) that move the caret from a to b in `buf`."""
    best = _direct(buf, a, b, word_jumps)
    if doc_anchors:
        via_home = [("home", True)] + _direct(buf, 0, b, word_jumps)
        via_end = [("end", True)] + _direct(buf, len(buf), b, word_jumps)
        for cand in (via_home, via_end):
            if len(cand) < len(best):
                best = cand
    return best
