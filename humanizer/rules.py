"""Rule-based humanizer: pure Python, works offline with no installs.

Pipeline (per paragraph, scaled by strength 0=light, 1=moderate, 2=heavy):
  protect facts -> sentence openers -> curated phrase swaps -> contractions
  -> sentence rhythm (split/merge) -> repeated-ending cleanup
then across paragraphs: vary repeated opening transitions; finally restore facts.

Facts are protected by swapping them for opaque placeholders before any rule
runs: numbers, dates, URLs/emails, anything in quotation marks, acronyms and
proper nouns. Rules can't see inside placeholders, so they can't change them.
There is deliberately no thesaurus/synonym spinning, only the curated phrase
dictionary in phrases.json.
"""
from __future__ import annotations

import json
import random
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

PH_O, PH_C = "", ""      # placeholder brackets
MK = ""                         # marks where a replacement was inserted (for a/an)
_PH_RE = re.compile(f"{PH_O}(\\d+){PH_C}")

TONES = ("Casual", "Neutral", "Formal", "Student essay")
STRENGTHS = ("Light touch", "Moderate", "Heavy rewrite")
P_REPLACE = (0.55, 0.85, 1.0)
P_CONTRACT = (0.45, 0.75, 0.9)
CV_TARGET = (0.25, 0.40, 0.50)        # below this, sentence lengths count as too uniform
MAX_RHYTHM_OPS = (1, 2, 3)
SPLIT_MIN_WORDS = (26, 22, 18)
MERGE_MAX_WORDS = (7, 9, 11)
ENDING_OVERLAP = (None, 0.7, 0.6)

CASUAL_SWAPS = {"lots of", "a lot of", "a big deal", "matters a lot for", "matter a lot for", "all sorts of",
                "lots of different", "plenty of", "a bunch of", "you really need to", "it really matters to",
                "get into", "dig into", "digging into", "dug into", "right now", "on top of", "folks"}
CASUAL_ONLY = {"Plus,", "So", "On top of that,", "What's more,", "Basically,", "That's why"}

MONTHS = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
NUMBER_WORDS = (r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
                r"hundred|thousand|million|billion|trillion|half|quarter|percent|dozen")
PROTECT_PATTERNS = [
    r"https?://\S+|www\.\S+",
    r"\b[\w.+-]+@[\w-]+\.[\w.]+\b",
    r'"[^"\n]*"',
    r"“[^”\n]*”",
    r"‘[^\n]*?’(?=[\s.,;:!?)]|$)",
    rf"\b{MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS}(?:,?\s+\d{{4}})?\b",
    r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b",
    r"\b(?:[A-Za-z]\.){2,}",                                   # e.g. U.S. i.e.
    r"[$€£¥]?\d[\d,]*(?:\.\d+)?(?:\s?%|[kKmMbB]n?\b|(?:st|nd|rd|th)\b)?",
    rf"(?i:\b(?:{NUMBER_WORDS})\b)",
    r"\b[A-Z]{2,}[a-z]?s?\b",                                  # acronyms: NASA, AI, APIs (case-sensitive)
]
_PROTECT_RE = re.compile("|".join(f"(?:{p})" for p in PROTECT_PATTERNS))
_CAP_WORD = re.compile(r"\b[A-Z][\w'’-]*")
ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "inc", "ltd", "co", "no", "fig", "approx", "dept", "est"}
# After a dash, these start an add-on phrase that reads best after a comma ("works, mostly").
DASH_SOFT = {"and", "but", "or", "nor", "mostly", "most", "sometimes", "usually", "often", "maybe", "probably",
             "almost", "even", "especially", "at", "just", "if", "unless", "though", "although", "except", "not",
             "only", "still", "yet", "like", "such", "plus", "which", "including", "both", "all"}
# A short sentence starting with one of these clearly continues the one before it.
MERGE_STARTERS = {"it", "they", "this", "these", "those", "that"}
# Openers whose trailing comma can go: "Today most people..." (not "However", "Also", "Yes").
INTRO_NO_COMMA = {"in", "on", "at", "after", "before", "during", "since", "for", "by", "today", "now", "then",
                  "still", "so", "plus", "yet", "sometimes", "usually", "often", "honestly", "basically",
                  "clearly", "lately", "recently", "later", "soon", "first", "next", "finally", "eventually",
                  "luckily", "sadly", "generally", "normally", "these", "back", "of", "arguably", "nowadays"}
SAFE_LOWER = {"the", "it", "this", "that", "they", "these", "those", "there", "its", "their", "a", "an", "we",
              "he", "she", "his", "her", "our", "some", "many", "most", "each", "every", "such", "one's"}
STOP = set("""a an the and or but so of to in on at for with by from as is are was were be been being it its this that
these those they them their there here we our you your he she his her i me my not no do does did have has had
will would can could should may might must just also very than then into about over more most such which who what""".split())

CONTRACTIONS = [
    ("do not", "don't"), ("does not", "doesn't"), ("did not", "didn't"), ("is not", "isn't"),
    ("are not", "aren't"), ("was not", "wasn't"), ("were not", "weren't"), ("cannot", "can't"),
    ("can not", "can't"), ("will not", "won't"), ("would not", "wouldn't"), ("should not", "shouldn't"),
    ("could not", "couldn't"), ("have not", "haven't"), ("has not", "hasn't"), ("had not", "hadn't"),
    ("it is", "it's"), ("that is", "that's"), ("there is", "there's"), ("what is", "what's"),
    ("who is", "who's"), ("here is", "here's"), ("he is", "he's"), ("she is", "she's"),
    ("they are", "they're"), ("we are", "we're"), ("you are", "you're"), ("i am", "I'm"),
    ("i will", "I'll"), ("we will", "we'll"), ("they will", "they'll"), ("you will", "you'll"),
]
# Only contract when another word follows (never "...what it is." at a clause end).
_CONTRACT_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a, _ in sorted(CONTRACTIONS, key=lambda x: -len(x[0]))) + r")\b(?=\s+[\w" + PH_O + r"])",
    re.IGNORECASE)
_CONTRACT_MAP = {a: b for a, b in CONTRACTIONS}

TRANSITION_GROUPS = {
    "add": ["Also,", "Plus,", "Additionally,", "Furthermore,", "Moreover,", "In addition,", "On top of that,", "What's more,"],
    "contrast": ["But", "Still,", "However,", "Even so,", "That said,", "Nevertheless,", "Nonetheless,"],
    "result": ["So", "As a result,", "Because of that,", "Therefore,", "Thus,", "Consequently,"],
}


def _resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "humanizer" / name


def load_dictionary(path: Path | None = None) -> dict:
    data = json.loads((path or _resource("phrases.json")).read_text(encoding="utf-8"))
    return {"openers": {k.lower(): v for k, v in data["openers"].items()},
            "phrases": {k.lower(): v for k, v in data["phrases"].items()}}


@dataclass
class Result:
    text: str
    stats: dict = field(default_factory=dict)


class RuleHumanizer:
    def __init__(self, dictionary: dict | None = None):
        d = dictionary or load_dictionary()
        self.openers = d["openers"]
        self.phrases = d["phrases"]
        op = sorted(self.openers, key=len, reverse=True)
        self._opener_re = re.compile(r"^(" + "|".join(re.escape(o) for o in op) + r")\s*", re.IGNORECASE)
        ph = sorted(self.phrases, key=len, reverse=True)
        self._phrase_re = re.compile(r"(?<![\w-])(" + "|".join(re.escape(p) for p in ph) + r")(?![\w-])", re.IGNORECASE)

    # ------------------------------------------------------------------ API
    def polish(self, text: str, strength: int = 1, tone: str = "Neutral", seed: int | None = None,
               style=None) -> Result:
        """Light cleanup for text another engine already rewrote: dashes, stock
        phrases, contractions and extra commas, without restructuring sentences."""
        return self.humanize(text, strength, tone, seed, structural=False, style=style)

    def humanize(self, text: str, strength: int = 1, tone: str = "Neutral", seed: int | None = None,
                 structural: bool = True, style=None) -> Result:
        """style: optional humanizer.style.StyleProfile measured from the user's own writing.
        When given, contraction rate, sentence splitting and comma use follow it."""
        strength = max(0, min(2, int(strength)))
        rng = random.Random(seed)
        stats = {"phrases": 0, "openers": 0, "contractions": 0, "splits": 0, "merges": 0,
                 "endings": 0, "transitions": 0, "dashes": 0, "commas": 0}
        stats["_style"] = style if style is not None and getattr(style, "sentences", 0) >= 3 else None
        if not text.strip():
            return Result(text, stats)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        apostrophe = "’" if text.count("’") > text.count("'") else "'"
        masked, store = self._protect(text)
        lines = masked.split("\n")
        out_lines = []
        for line in lines:
            if not line.strip():
                out_lines.append(line)
                continue
            indent = line[: len(line) - len(line.lstrip())]
            para = self._fix_dashes(line.strip(), stats)
            sents = self._split_sentences(para, store)
            drop_last = structural and self._repeats_opening(sents, strength, store)
            sents = [self._sentence_pass(s, strength, tone, rng, stats, apostrophe, always=not structural) for s in sents]
            if drop_last:
                sents.pop()
                stats["endings"] += 1
            sents = [s for s in sents if s.strip()]
            if structural:
                sents = self._rhythm(sents, strength, tone, rng, stats)
            if not (tone == "Formal" and strength == 0):   # fewer commas, last so splits can use them
                sents = [self._trim_commas(x, strength, tone, rng, stats) for x in sents]
            out_lines.append(indent + " ".join(sents))
        if structural:
            out_lines = self._vary_paragraph_openers(out_lines, strength, tone, rng, stats)
        out = "\n".join(out_lines)
        out = self._fix_articles(out)
        out = self._tidy(out)
        stats.pop("_recent", None)
        stats.pop("_style", None)
        return Result(self._restore(out, store), stats)

    # ------------------------------------------------------------------ protection
    def _protect(self, text: str):
        store: list[str] = []

        def keep(m):
            store.append(m.group(0))
            return f"{PH_O}{len(store) - 1}{PH_C}"
        masked = _PROTECT_RE.sub(keep, text)

        # Proper nouns: capitalized words that aren't at the start of a sentence,
        # plus the same words wherever else they appear.
        names = set()
        for m in _CAP_WORD.finditer(masked):
            before = masked[: m.start()].rstrip(" \t\"“‘(['’")
            if before and before[-1] not in ".!?:\n" and not _ends_sentence_ph(before, store):
                names.add(m.group(0))
        names.discard("I")
        if names:
            name_re = re.compile(r"(?<![\w" + PH_O + r"])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w'’-])")
            masked = name_re.sub(keep, masked)
        return masked, store

    @staticmethod
    def _restore(text: str, store: list[str]) -> str:
        # Placeholders can nest only once (names found after numbers), so loop.
        for _ in range(3):
            new = _PH_RE.sub(lambda m: store[int(m.group(1))], text)
            if new == text:
                break
            text = new
        return text

    # ------------------------------------------------------------------ sentences
    @staticmethod
    def _split_sentences(para: str, store: list[str]) -> list[str]:
        out, start = [], 0
        boundary = r"(?:(?<=[.!?])|(?<=" + PH_C + r"))[\"”’)\]]*\s+(?=[A-Z" + PH_O + r"\"“‘(\d])"
        for m in re.finditer(boundary, para):
            chunk = para[start:m.start()]
            if chunk.endswith(PH_C) and not _ends_sentence_ph(chunk, store):
                continue
            last = re.findall(r"(\w+)\.$", chunk)
            if last and last[0].lower() in ABBREV:
                continue
            out.append(para[start:m.end()].strip())
            start = m.end()
        out.append(para[start:].strip())
        return [s for s in out if s]

    def _sentence_pass(self, s: str, strength, tone, rng, stats, apos, always: bool = False) -> str:
        p = 1.0 if always else P_REPLACE[strength]
        # 1. Mechanical sentence openers ("Furthermore,", "It is important to note that").
        prefix = ""
        for _ in range(3):                       # "Furthermore, it is important to note that ..."
            m = self._opener_re.match(s)
            p_open = 1.0 if strength >= 1 else max(p, 0.7)    # stock openers are the biggest tell
            if not m or (not prefix and rng.random() >= p_open):   # stacked openers always go
                break
            options = self.openers[m.group(1).lower()]
            if tone == "Formal":
                options = [o for o in options if o not in CASUAL_ONLY] or [""]
            if prefix and "" in options:         # already have an opener: drop stacked ones
                options = [""]
            recent = stats.setdefault("_recent", [])
            fresh = [o for o in options if not o or o not in recent[-4:]]
            rep = rng.choice(fresh or [""])
            if rep:
                recent.append(rep)
            s = s[m.end():]
            stats["openers"] += 1
            if rep:
                if not rep.endswith(","):
                    s = _lower_first(s)
                prefix += rep + " "
        if prefix:
            s = prefix + (s if prefix.rstrip().endswith(",") else _lower_first(s))
        else:
            s = _upper_first(s)

        # 2. Curated phrase replacements anywhere in the sentence.
        def swap(mm):
            if rng.random() >= p:
                return mm.group(0)
            options = self.phrases[mm.group(1).lower()]
            if tone == "Formal":
                options = [o for o in options if "'" not in o and o not in
                           CASUAL_SWAPS] or options
            rep = rng.choice(options)
            stats["phrases"] += 1
            if mm.group(0)[0].isupper() and rep:
                rep = rep[0].upper() + rep[1:]
            return MK + rep
        s = self._phrase_re.sub(swap, s)
        s = re.sub(r"\s{2,}", " ", s).strip()

        # 3. Contractions (skipped for formal writing).
        if tone != "Formal":
            pc = P_CONTRACT[strength] * (0.5 if tone == "Student essay" else 1.0) * (1.15 if tone == "Casual" else 1.0)
            st = stats.get("_style")
            if st is not None:          # the writer's own habit wins over the tone default
                pc = min(1.0, st.contraction_rate * (0.85 + 0.15 * strength))

            def contract(mm):
                if rng.random() >= pc:
                    return mm.group(0)
                rep = _CONTRACT_MAP[mm.group(1).lower()].replace("'", apos)
                stats["contractions"] += 1
                if mm.group(1)[0].isupper():
                    rep = rep[0].upper() + rep[1:]
                return rep
            s = _CONTRACT_RE.sub(contract, s)

        return s

    # ------------------------------------------------------------------ dashes & commas
    @staticmethod
    def _fix_dashes(para: str, stats) -> str:
        """Replace em dashes, spaced en dashes and '--' (quotes and number ranges
        are protected placeholders, so they're never touched)."""
        dash = r"(?:\s*—\s*|\s+–\s+|\s*--\s*)"
        if not re.search(dash, para):
            return para

        # Paired dashes around a short aside -> parentheses.
        def aside(m):
            inner = m.group(1).strip()
            stats["dashes"] += 2
            return f" ({inner}) " if len(inner.split()) <= 9 else f", {inner}, "
        para = re.sub(dash + r"([^—–.!?]{1,90}?)" + dash, aside, para)

        # Single dash: new sentence before a full clause, colon before a short phrase.
        def single(m):
            stats["dashes"] += 1
            rest = m.group(2)
            body = re.match(r"([^.!?]*)", rest).group(1)
            words = body.split()
            if words and words[0].lower().strip(",") in DASH_SOFT and len(words) <= 7:
                return m.group(1).rstrip(" ,;") + ", " + rest.lstrip()
            if len(words) >= 4:
                return m.group(1).rstrip(" ,;") + ". " + _upper_first(rest.lstrip())
            return m.group(1).rstrip(" ,;") + ": " + rest.lstrip()
        for _ in range(4):
            new = re.sub(r"([^—–]*?\S)" + dash + r"(\S.*)", single, para, count=1)
            if new == para:
                break
            para = new
        return re.sub(r"\s*(?:—|--)\s*", ", ", para)   # anything left (dash at an odd spot)

    def _trim_commas(self, s: str, strength, tone, rng, stats) -> str:
        p = (0.5, 0.8, 1.0)[strength]
        st = stats.get("_style")
        if st is not None:              # few commas in the sample -> trim hard; lots -> leave most
            cps = st.commas_per_sentence
            p = 1.0 if cps < 0.5 else 0.75 if cps < 0.9 else 0.4 if cps < 1.4 else 0.15

        def maybe(fn):
            def inner(m):
                if rng.random() >= p:
                    return m.group(0)
                stats["commas"] += 1
                return fn(m)
            return inner
        # Comma after a short introductory phrase: "In 2024, we" / "Today, most" / "Still, it".
        m = re.match(r"^((?:[A-Za-z']+|" + PH_O + r"\d+" + PH_C + r")(?: (?:[A-Za-z']+|" + PH_O + r"\d+" + PH_C + r")){0,2}), (?=\S)", s)
        if m and m.group(1).split()[0].lower() in INTRO_NO_COMMA and len(s.split()) > 4:
            s = maybe(lambda mm: mm.group(1) + " ")(m) + s[m.end():]
        # Serial (Oxford) comma: "a, b, and c" -> "a, b and c".
        s = re.sub(r"(, [^,.;:!?]{1,40}), (and|or) ", maybe(lambda mm: f"{mm.group(1)} {mm.group(2)} "), s)
        # Short compound sentence: "I went home, and she stayed." -> no comma.
        cm = re.match(r"^([^,;:]{6,70}), (and|so) ([^,;:]{4,70})$", s)
        if cm and len(s.split()) <= 12:
            s = maybe(lambda mm: f"{mm.group(1)} {mm.group(2)} {mm.group(3)}")(cm)
        # ", too." -> " too."
        s = re.sub(r", too([.!?])", maybe(lambda mm: f" too{mm.group(1)}"), s)
        return s

    # ------------------------------------------------------------------ rhythm
    def _rhythm(self, sents: list[str], strength, tone, rng, stats) -> list[str]:
        if len(sents) < 3:
            return sents
        st = stats.get("_style")
        self._split_min = SPLIT_MIN_WORDS[strength]
        cv_target = CV_TARGET[strength]
        if st is not None and st.avg_sentence_words:
            # Someone who writes ~12-word sentences gets long ones split sooner.
            self._split_min = int(max(12, min(30, st.avg_sentence_words * 1.45)))
            cv_target = max(cv_target, min(0.8, st.sentence_words_std / st.avg_sentence_words))
        self._and_starts = bool(st is not None and st.starts_with_and_but > 0.08)
        ops = 0
        fresh: set[str] = set()   # halves of a split; never merge them straight back
        for _ in range(MAX_RHYTHM_OPS[strength] * 2):
            if ops >= MAX_RHYTHM_OPS[strength] or _cv(sents) >= cv_target:
                break
            done = False
            # Only splits: merging two sentences with "and" too often joins ideas that
            # aren't actually connected, which changes the meaning.
            order = ("split",)
            for op in order:
                if op == "split" and self._try_split(sents, strength, tone, rng, fresh):
                    stats["splits"] += 1
                    done = True
                    break
                if op == "merge" and self._try_merge(sents, strength, rng, fresh):
                    stats["merges"] += 1
                    done = True
                    break
            if not done:
                break
            ops += 1
        return sents

    def _try_split(self, sents, strength, tone, rng, fresh) -> bool:
        best = None
        for i, s in enumerate(sents):
            n = len(s.split())
            if n < getattr(self, "_split_min", SPLIT_MIN_WORDS[strength]) or not s.endswith((".", "!", "?")):
                continue
            pats = [r", (and|but|so) ", r"; "] + ([r", which "] if strength == 2 else [])
            for pat in pats:
                for m in re.finditer(pat, s):
                    left = len(s[:m.start()].split())
                    right = n - left
                    if left < 6 or right < 6:
                        continue
                    score = abs(left - n / 2)
                    if best is None or score < best[0]:
                        best = (score, i, m)
        if not best:
            return False
        _, i, m = best
        s = sents[i]
        head = s[:m.start()].rstrip(",;") + "."
        tail = s[m.end():]
        conj = m.group(1) if m.lastindex else None
        if m.group(0).startswith(", which"):
            tail = "That " + tail
        elif conj in ("but", "so") or (conj == "and" and (tone == "Casual" or getattr(self, "_and_starts", False))
                                       and rng.random() < 0.6):
            tail = conj.capitalize() + " " + tail
        else:
            tail = _upper_first(tail)
        sents[i:i + 1] = [head, tail]
        fresh.update((head, tail))
        return True

    def _try_merge(self, sents, strength, rng, fresh) -> bool:
        cands = []
        for i in range(len(sents) - 1):
            a, b = sents[i], sents[i + 1]
            if a in fresh or b in fresh:
                continue
            na, nb = len(a.split()), len(b.split())
            first = b.split()[0] if b.split() else ""
            if (na <= MERGE_MAX_WORDS[strength] and nb <= MERGE_MAX_WORDS[strength] + 4 and na + nb <= 24
                    and a.endswith(".") and not a.endswith("..") and first.lower() in MERGE_STARTERS
                    and "," not in a and PH_O not in a[-3:]
                    and first[:1].isupper() and PH_O not in first):
                cands.append(i)
        if not cands:
            return False
        i = min(cands, key=lambda k: len(sents[k].split()) + len(sents[k + 1].split()))
        joiner = " and "                        # no comma, no semicolon: reads less formal
        sents[i:i + 2] = [sents[i][:-1] + joiner + _lower_first(sents[i + 1])]
        return True

    # ------------------------------------------------------------------ endings
    def _repeats_opening(self, sents, strength, store) -> bool:
        """True if the paragraph's last sentence mostly restates its first one."""
        thr = ENDING_OVERLAP[strength]
        if thr is None or len(sents) < 3:
            return False
        strip = lambda x: self._opener_re.sub("", x)      # "In conclusion," etc. don't count
        first, last = _content_words(strip(sents[0])), _content_words(strip(sents[-1]))
        if len(last) < 3 or len(first & last) / len(last) < thr:
            return False
        # Never drop a fact: every protected token in the last sentence must appear earlier.
        earlier = {store[int(x)] for x in _PH_RE.findall(" ".join(sents[:-1]))}
        last_facts = {store[int(x)] for x in _PH_RE.findall(sents[-1])}
        return last_facts <= earlier

    # ------------------------------------------------------------------ paragraphs
    def _vary_paragraph_openers(self, lines, strength, tone, rng, stats):
        prev = None
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            body = line.lstrip()
            indent = line[: len(line) - len(body)]
            op = _opening_transition(body)
            if op and prev and op.lower() == prev.lower() and rng.random() < P_REPLACE[strength]:
                group = next((g for g, opts in TRANSITION_GROUPS.items() if op in opts), None)
                rest = body[len(op):].lstrip()
                if group == "add" or group is None:
                    body = _upper_first(rest)
                    new_op = None
                else:
                    choices = [o for o in TRANSITION_GROUPS[group] if o.lower() != op.lower()
                               and not (tone == "Formal" and o in CASUAL_ONLY)]
                    new_op = rng.choice(choices)
                    rest = _lower_first(rest) if not new_op.endswith(",") else rest
                    body = f"{new_op} {rest}"
                lines[i] = indent + body
                stats["transitions"] += 1
                op = new_op
            prev = op
        return lines

    # ------------------------------------------------------------------ cleanup
    @staticmethod
    def _fix_articles(text: str) -> str:
        def fix(m):
            art, nxt = m.group(1), m.group(2)
            vowel = nxt.lower() in "aeiou"
            new = ("an" if vowel else "a")
            if art[0].isupper():
                new = new.capitalize()
            return f"{new} {nxt}"
        text = re.sub(r"\b(an?|An?) " + MK + r"(\w)", fix, text)
        return text.replace(MK, "")

    @staticmethod
    def _tidy(text: str) -> str:
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r" +([,.;:!?])", r"\1", text)
        text = re.sub(r",\s*,", ",", text)
        text = re.sub(r"^\s*,\s*", "", text, flags=re.M)
        return text


# ---------------------------------------------------------------------- helpers
def _upper_first(s: str) -> str:
    for i, c in enumerate(s):
        if c == PH_O:
            return s
        if c.isalpha():
            return s[:i] + c.upper() + s[i + 1:]
    return s


def _lower_first(s: str) -> str:
    m = re.match(r"(\W*)(\w+)", s)
    if not m or PH_O in m.group(0):
        return s
    w = m.group(2)
    if w.lower() in SAFE_LOWER or w.lower() in STOP:
        return s[: m.start(2)] + w[0].lower() + w[1:] + s[m.end(2):]
    return s


def _ends_sentence_ph(text: str, store: list[str]) -> bool:
    """Does `text` end with a placeholder whose content ends a sentence (a quote like "Hi.")?"""
    m = re.search(PH_O + r"(\d+)" + PH_C + r"$", text)
    return bool(m) and bool(re.search(r"[.!?][\"”’)]*$", store[int(m.group(1))]))


def _cv(sents) -> float:
    lens = [len(s.split()) for s in sents]
    if len(lens) < 2:
        return 1.0
    mean = statistics.mean(lens)
    return statistics.pstdev(lens) / mean if mean else 1.0


def _content_words(s: str) -> set[str]:
    words = re.findall(r"[a-z']+", s.lower())
    out = set()
    for w in words:
        if w in STOP or len(w) < 3:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def _opening_transition(body: str) -> str | None:
    for opts in TRANSITION_GROUPS.values():
        for o in sorted(opts, key=len, reverse=True):
            if body.startswith(o + " ") or body.lower().startswith(o.lower() + " "):
                return body[: len(o)]
    return None


_default: RuleHumanizer | None = None


def humanize(text: str, strength: int = 1, tone: str = "Neutral", seed: int | None = None, style=None) -> Result:
    global _default
    if _default is None:
        _default = RuleHumanizer()
    return _default.humanize(text, strength, tone, seed, style=style)


def polish(text: str, strength: int = 1, tone: str = "Neutral", seed: int | None = None, style=None) -> Result:
    global _default
    if _default is None:
        _default = RuleHumanizer()
    return _default.polish(text, strength, tone, seed, style=style)
