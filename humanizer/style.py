"""Writing-style profiles built from samples the user wrote themselves.

A profile is a handful of measurable habits (sentence length, contractions,
commas, how sentences start, punctuation) that both engines use: the rule-based
engine tunes its rules to them, and Local AI gets the profile plus excerpts of
the sample as examples to imitate.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+(?=[\"“‘(\[]?[A-Za-z0-9])")
_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_CONTRACTION = re.compile(r"\b[A-Za-z]+['’](?:t|s|re|ve|ll|d|m)\b", re.IGNORECASE)
# Places a contraction *could* have been used: "it is", "do not", ...
_EXPANDABLE = re.compile(
    r"\b(?:it|that|there|what|who|he|she|they|we|you|i)\s+(?:is|are|am|will|would|have|has)\b"
    r"|\b(?:do|does|did|is|are|was|were|could|would|should|will|have|has|had)\s+not\b|\bcannot\b",
    re.IGNORECASE)
_STOP = set("""a an the and or but so of to in on at for with by from as is are was were be been being it its this that
these those they them their there here we our you your he she his her i me my not no do does did have has had will
would can could should may might must just also very than then into about over more most such which who what when
where how why if because while out up down off all some any each every one two me him us""".split())


@dataclass
class StyleProfile:
    sentences: int = 0
    avg_sentence_words: float = 0.0
    sentence_words_std: float = 0.0
    short_sentence_share: float = 0.0      # sentences under 8 words
    contraction_rate: float = 0.0          # contractions / (contractions + expandable phrases)
    commas_per_sentence: float = 0.0
    starts_with_and_but: float = 0.0       # share of sentences starting with And/But/So
    first_person: float = 0.0              # I/my/me per 100 words
    questions: float = 0.0                 # share of sentences ending in ?
    exclamations: float = 0.0
    avg_word_length: float = 0.0
    uses_dashes: bool = False
    uses_semicolons: bool = False
    signature_words: list = field(default_factory=list)

    def summary(self) -> list[str]:
        """Short, human-readable traits for the UI."""
        if not self.sentences:
            return []
        out = [f"~{self.avg_sentence_words:.0f} words per sentence"]
        c = self.contraction_rate
        out.append("contractions: " + ("almost always" if c > .75 else "often" if c > .45 else "sometimes" if c > .15 else "rarely"))
        cm = self.commas_per_sentence
        out.append("commas: " + ("lots" if cm > 1.2 else "some" if cm > .6 else "few"))
        if self.short_sentence_share > .25:
            out.append("lots of short sentences")
        if self.starts_with_and_but > .08:
            out.append("starts sentences with And/But/So")
        if self.first_person > 2:
            out.append("writes in first person")
        if self.questions > .08:
            out.append("asks questions")
        out.append("plain words" if self.avg_word_length < 4.4 else "longer words" if self.avg_word_length > 5.0 else "everyday vocabulary")
        return out


def analyze(text: str) -> StyleProfile:
    text = text.strip()
    if not text:
        return StyleProfile()
    sents = [s.strip() for p in text.split("\n") for s in _SENT_SPLIT.split(p.strip()) if s.strip()]
    lens = [len(_WORD.findall(s)) for s in sents]
    lens = [n for n in lens if n] or [0]
    words = _WORD.findall(text)
    n_words = max(1, len(words))
    contractions = len(_CONTRACTION.findall(text))
    expandable = len(_EXPANDABLE.findall(text))
    starts = [s.split()[0].strip("\"“‘(").lower() for s in sents if s.split()]
    content = [w.lower() for w in words if w.lower() not in _STOP and len(w) > 3]
    sig = [w for w, c in Counter(content).most_common(12) if c >= 2][:8]
    return StyleProfile(
        sentences=len(sents),
        avg_sentence_words=statistics.mean(lens),
        sentence_words_std=statistics.pstdev(lens) if len(lens) > 1 else 0.0,
        short_sentence_share=sum(1 for n in lens if n < 8) / len(lens),
        contraction_rate=contractions / (contractions + expandable) if contractions + expandable else 0.5,
        commas_per_sentence=text.count(",") / max(1, len(sents)),
        starts_with_and_but=sum(1 for w in starts if w in ("and", "but", "so")) / max(1, len(starts)),
        first_person=100 * sum(1 for w in words if w.lower() in ("i", "my", "me", "i'm", "i’m", "i've", "i’ve")) / n_words,
        questions=sum(1 for s in sents if s.rstrip("\"”’) ").endswith("?")) / max(1, len(sents)),
        exclamations=sum(1 for s in sents if s.rstrip("\"”’) ").endswith("!")) / max(1, len(sents)),
        avg_word_length=sum(len(w) for w in words) / n_words,
        uses_dashes="—" in text or " - " in text or "--" in text,
        uses_semicolons=";" in text,
        signature_words=sig,
    )


def excerpts(text: str, max_chars: int = 900) -> list[str]:
    """One or two representative paragraphs to show a model as examples."""
    paras = [p.strip() for p in text.split("\n") if len(p.split()) >= 12]
    if not paras:
        return [text.strip()[:max_chars]] if text.strip() else []
    paras.sort(key=lambda p: abs(len(p.split()) - 70))          # medium-length paragraphs first
    out, used = [], 0
    for p in paras:
        if used + len(p) > max_chars and out:
            break
        out.append(p[:max_chars])
        used += len(p)
        if len(out) == 2:
            break
    return out


def prompt_block(profile: StyleProfile, text: str) -> str:
    """Instructions + examples for Local AI."""
    traits = "; ".join(profile.summary())
    ex = "\n\n".join(f"<example>\n{e}\n</example>" for e in excerpts(text))
    rules = [
        f"Aim for sentences around {profile.avg_sentence_words:.0f} words on average, with similar variety.",
        "Use contractions about as often as the examples do." if profile.contraction_rate > .15 else "Avoid contractions, like the examples.",
        f"Use about {profile.commas_per_sentence:.1f} commas per sentence, like the examples.",
    ]
    if profile.starts_with_and_but > .08:
        rules.append("Starting a sentence with And, But or So is fine; the writer does it.")
    if profile.first_person > 2:
        rules.append("Keep the writer's first-person voice where the original allows it.")
    return ("Match the writer's style shown in these examples: vocabulary, sentence length, punctuation habits "
            f"and tone. Measured traits: {traits}.\n- " + "\n- ".join(rules) +
            f"\nUse the examples for style only; never copy their content.\n{ex}")


# ---------------------------------------------------------------------------
# Saved templates (%APPDATA%\CadenceFree\styles.json)
# ---------------------------------------------------------------------------
@dataclass
class StyleTemplate:
    id: str
    name: str
    text: str

    def to_public(self) -> dict:
        prof = analyze(self.text)
        return {"id": self.id, "name": self.name, "text": self.text, "words": len(_WORD.findall(self.text)),
                "summary": prof.summary(), "profile": asdict(prof)}


class StyleStore:
    MIN_WORDS = 60

    def __init__(self, path: Path):
        self.path = path
        self.items: list[StyleTemplate] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.items = [StyleTemplate(**d) for d in data if {"id", "name", "text"} <= set(d)]
        except (OSError, ValueError, TypeError):
            pass

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(i) for i in self.items], indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        return [i.to_public() for i in self.items]

    def get(self, sid: str) -> StyleTemplate | None:
        return next((i for i in self.items if i.id == sid), None)

    def save(self, name: str, text: str, sid: str | None = None) -> StyleTemplate:
        name, text = name.strip() or "My style", text.strip()
        if len(_WORD.findall(text)) < self.MIN_WORDS:
            raise ValueError(f"Add at least {self.MIN_WORDS} words of your own writing so there's enough to learn from.")
        item = self.get(sid) if sid else None
        if item:
            item.name, item.text = name, text
        else:
            item = StyleTemplate(uuid.uuid4().hex[:10], name, text)
            self.items.append(item)
        self._save()
        return item

    def delete(self, sid: str) -> None:
        self.items = [i for i in self.items if i.id != sid]
        self._save()
