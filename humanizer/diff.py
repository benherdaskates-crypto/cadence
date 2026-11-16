"""Word-level diff between the original and humanized text, for the "Show changes" view."""
from __future__ import annotations

import difflib
import re

_TOKEN = re.compile(r"\s+|\w+(?:['’]\w+)*|[^\w\s]")


def word_diff(a: str, b: str) -> list[list[str]]:
    """Returns [op, text] segments where op is "eq", "del" or "ins".
    Concatenating eq+del gives `a`; eq+ins gives `b`."""
    ta, tb = _TOKEN.findall(a), _TOKEN.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    out: list[list[str]] = []

    def add(op, toks):
        if not toks:
            return
        s = "".join(toks)
        if out and out[-1][0] == op:
            out[-1][1] += s
        else:
            out.append([op, s])
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            add("eq", ta[i1:i2])
        else:
            add("del", ta[i1:i2])
            add("ins", tb[j1:j2])
    return out


def change_ratio(a: str, b: str) -> float:
    """Share of words that changed (0..1)."""
    wa, wb = re.findall(r"\w+", a), re.findall(r"\w+", b)
    if not wa and not wb:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()
