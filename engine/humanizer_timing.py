"""Timing model: how long to wait before each keystroke."""
from __future__ import annotations

import random
import re

# Words and fragments typed in fast "bursts" because they're muscle memory.
BURST_WORDS = {
    "the", "and", "to", "of", "a", "in", "is", "it", "that", "for", "you", "with",
    "on", "as", "was", "this", "be", "are", "have", "not", "but", "i", "at", "or",
    "from", "they", "we", "he", "she", "his", "her", "by", "an", "my", "so", "if",
}
BURST_NGRAMS = ("ing", "tion", "the", "and", "ed", "er", "th", "he", "re", "ly")

COMMA_PAUSE = 0.30        # seconds, scaled by the pause slider
SENTENCE_PAUSE = 0.85
PARAGRAPH_PAUSE = 2.2
FATIGUE_MAX = 0.30        # up to 30% slower by the end of the text

_WORD_RE = re.compile(r"[A-Za-z']+")


def burst_mask(text: str) -> list[bool]:
    """True for characters that belong to a common word or fragment."""
    mask = [False] * len(text)
    for m in _WORD_RE.finditer(text):
        word = m.group().lower()
        if word in BURST_WORDS:
            for i in range(m.start(), m.end()):
                mask[i] = True
            continue
        for gram in BURST_NGRAMS:
            start = word.find(gram)
            while start != -1:
                for i in range(m.start() + start, m.start() + start + len(gram)):
                    mask[i] = True
                start = word.find(gram, start + 1)
    return mask


class TimingModel:
    def __init__(self, settings, rng: random.Random, text_len: int):
        self.s = settings
        self.rng = rng
        self.text_len = max(1, text_len)
        self.base = 60.0 / (max(5.0, float(settings.wpm)) * 5.0)  # sec per char

    def _fatigue(self, index: int) -> float:
        if not self.s.fatigue_enabled:
            return 1.0
        return 1.0 + FATIGUE_MAX * (index / self.text_len) ** 1.3

    def _jitter(self) -> float:
        v = self.s.speed_variance
        if v <= 0:
            return 1.0
        return min(3.0, max(0.3, self.rng.gauss(1.0, v)))

    def char_delay(self, index: int, ch: str, prev: str, burst: bool) -> float:
        d = self.base * self._jitter() * self._fatigue(index)
        if burst and self.s.burst_enabled:
            d *= 0.6
        if ch.isupper() and not prev.isupper():
            d += self.base * 0.35  # reaching for shift
        if not ch.isascii():
            d += self.base * 0.8   # special characters take a moment
        return d

    def quick_delay(self) -> float:
        """Backspaces and retyping are faster than composing."""
        return self.base * 0.55 * self._jitter()

    def nav_delay(self, ctrl: bool) -> float:
        r = self.rng
        return r.uniform(0.11, 0.24) if ctrl else r.uniform(0.035, 0.075)

    def punctuation_pause(self, ch: str, nxt: str) -> float:
        scale = self.s.punct_pause_scale
        if scale <= 0:
            return 0.0
        r = self.rng.uniform(0.7, 1.35)
        if ch in ",;:":
            return COMMA_PAUSE * scale * r
        if ch in ".!?" and (nxt in " \n\"'”’)" or nxt == ""):
            return SENTENCE_PAUSE * scale * r
        if ch == "\n":
            return PARAGRAPH_PAUSE * scale * r
        return 0.0

    def thinking_pause(self) -> float:
        """Chance of a mid-sentence 'thinking' pause at a word boundary."""
        if self.rng.random() < self.s.thinking_freq:
            return self.rng.lognormvariate(0.6, 0.45)  # median ~1.8s
        return 0.0

    def notice_delay(self) -> float:
        """Time between making a typo and reacting to it."""
        return self.rng.uniform(0.22, 0.75)

    def hesitate(self, lo: float, hi: float) -> float:
        return self.rng.uniform(lo, hi)
