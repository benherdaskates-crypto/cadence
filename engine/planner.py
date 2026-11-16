"""Turns target text + settings into a complete, timed keystroke plan.

The whole session is planned up front, which gives an exact time estimate
(the plan's total delay) and lets every keystroke be checked against a
VirtualEditor before anything is sent to a real window.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from . import typos
from .actions import Action, VirtualEditor
from .humanizer_timing import TimingModel, burst_mask
from .revisions import (
    OMITTABLE, REVISION_AMOUNTS, SYNONYMS, PendingFix, match_case, plan_navigation,
)

MIN_DELAY = 0.012  # below this some apps drop keystrokes
_WORD_AT = re.compile(r"[A-Za-z]+")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Non-breaking/zero-width oddities from copy-paste
    return text.replace("​", "").replace("﻿", "")


class PlanError(RuntimeError):
    pass


@dataclass
class Plan:
    text: str
    actions: list[Action]
    typing_seconds: float
    break_seconds: float
    stats: dict = field(default_factory=dict)

    @property
    def total_seconds(self) -> float:
        return self.typing_seconds + self.break_seconds

    @property
    def effective_wpm(self) -> float:
        if self.typing_seconds <= 0:
            return 0.0
        return (len(self.text) / 5.0) / (self.typing_seconds / 60.0)


class _Builder:
    def __init__(self, text: str, settings, rng: random.Random):
        self.text = text
        self.s = settings
        self.rng = rng
        self.t = TimingModel(settings, rng, len(text))
        self.ed = VirtualEditor()
        self.actions: list[Action] = []
        self.pending: list[PendingFix] = []
        self.seq = 0
        self.carry = 0.0       # pause to add before the next keystroke
        self.stats = {"typos": 0, "caught": 0, "deferred": 0, "rough": 0,
                      "omitted": 0, "rethinks": 0, "revision_passes": 0}
        amt = REVISION_AMOUNTS.get(settings.revision_amount, REVISION_AMOUNTS["Some"])
        self.defer_share, self.rough_p, self.omit_p = amt
        if not settings.revise_enabled:
            self.defer_share = self.rough_p = self.omit_p = 0.0
        self.rethink_p = (self.rough_p * 0.8 + 0.006) if settings.rethink_enabled else 0.0
        self.burst = burst_mask(text)

    # ---- primitives -------------------------------------------------------
    def _emit(self, a: Action) -> None:
        a.delay = max(MIN_DELAY, a.delay + self.carry)
        self.carry = 0.0
        self.actions.append(a)
        self.ed.apply(a)

    def put(self, ch: str, delay: float, note: str = "type") -> None:
        if ch == "\n":
            self._emit(Action("key", "enter", delay, shift=self.s.shift_enter, note=note))
        elif ch == "\t":
            self._emit(Action("key", "tab", delay, note=note))
        else:
            self._emit(Action("char", ch, delay, note=note))

    def key(self, name: str, delay: float, ctrl: bool = False, note: str = "nav") -> None:
        self._emit(Action("key", name, delay, ctrl=ctrl, note=note))

    def backspace(self, n: int, note: str) -> None:
        for _ in range(n):
            self.key("backspace", self.t.quick_delay(), note=note)

    def type_clean(self, s: str, idx: int, note: str, quick: bool = False) -> None:
        """Type `s` without mistakes. idx is the target index it corresponds to
        (used for fatigue); may be approximate for alternative words."""
        prev = self.ed.buf[-1] if self.ed.buf else ""
        for k, ch in enumerate(s):
            if quick:
                d = self.t.quick_delay()
            else:
                i = min(len(self.text) - 1, idx + k)
                d = self.t.char_delay(i, ch, prev, self.burst[i] if 0 <= i < len(self.burst) else False)
            self.put(ch, d, note)
            prev = ch

    def navigate(self, target: int) -> None:
        keys = plan_navigation(self.ed.buf, self.ed.cursor, target,
                               word_jumps=self.s.word_jumps, doc_anchors=self.s.empty_doc)
        for name, ctrl in keys:
            self.key(name, self.t.nav_delay(ctrl), ctrl=ctrl, note="nav")
        if self.ed.cursor != target:
            raise PlanError("navigation model mismatch")

    def add_fix(self, start: int, wrong: str, right: str, kind: str) -> None:
        self.pending.append(PendingFix(start, wrong, right, self.seq, kind))
        self.seq += 1

    # ---- revision pass ----------------------------------------------------
    def revise(self) -> None:
        if not self.pending:
            return
        self.stats["revision_passes"] += 1
        frontier = len(self.ed.buf)
        if self.ed.cursor != frontier:
            raise PlanError("caret is not at the typing frontier")
        self.carry += self.t.hesitate(1.4, 3.6)  # re-reading what was written
        fixes = sorted(self.pending, key=lambda f: (f.start, f.seq))
        self.pending = []
        for n, f in enumerate(fixes):
            end = f.start + len(f.wrong)
            if "".join(self.ed.buf[f.start:end]) != f.wrong:
                raise PlanError("stale revision record")
            self.navigate(end)
            self.carry += self.t.hesitate(0.15, 0.55)
            self.backspace(len(f.wrong), note="revise")
            if f.right:
                self.type_clean(f.right, 0, note="revise", quick=False)
            delta = len(f.right) - len(f.wrong)
            for g in fixes[n + 1:]:
                g.start += delta
        self.carry += self.t.hesitate(0.2, 0.7)
        self.navigate(len(self.ed.buf))
        self.carry += self.t.hesitate(0.3, 0.9)

    # ---- main loop --------------------------------------------------------
    def build(self) -> None:
        text, rng, t = self.text, self.rng, self.t
        n = len(text)
        i = 0
        while i < n:
            ch = text[i]
            prev = text[i - 1] if i else ""
            at_word_start = ch.isascii() and ch.isalpha() and not (prev.isascii() and prev.isalpha()) and prev != "'"

            if ch == "\n" and self.pending and self._revise_now():
                self.revise()

            if at_word_start:
                m = _WORD_AT.match(text, i)
                word = m.group()
                end = m.end()
                nxt = text[end] if end < n else ""
                self.carry += t.thinking_pause() if prev in (" ", "") else 0.0
                lw = word.lower()

                # Leave out a small word now, insert it during revision.
                if (lw in OMITTABLE and nxt == " " and prev == " "
                        and rng.random() < self.omit_p):
                    self.add_fix(len(self.ed.buf), "", word + " ", "omit")
                    self.stats["omitted"] += 1
                    i = end + 1
                    continue

                alts = SYNONYMS.get(lw)
                if alts and nxt != "'":
                    # Rough phrasing: type a placeholder word, fix it later.
                    if rng.random() < self.rough_p:
                        alt = match_case(rng.choice(alts), word)
                        start = len(self.ed.buf)
                        self.type_clean(alt, i, note="rough")
                        self.add_fix(start, alt, word, "rough")
                        self.stats["rough"] += 1
                        i = end
                        continue
                    # Rethinking: type an alternative, delete it, type the real one.
                    if rng.random() < self.rethink_p:
                        alt = match_case(rng.choice(alts), word)
                        if rng.random() < 0.35 and len(alt) > 3:
                            alt = alt[: rng.randint(2, len(alt) - 1)]  # abandoned midway
                        elif nxt == " ":
                            alt += " "
                        self.type_clean(alt, i, note="rethink")
                        self.carry += t.hesitate(0.45, 1.4)
                        self.backspace(len(alt), note="rethink")
                        self.carry += t.hesitate(0.2, 0.6)
                        self.stats["rethinks"] += 1
                        # fall through and type the real word normally

            if typos.can_typo(ch) and rng.random() < self.s.typo_rate:
                i = self._typo(i)
                continue

            d = t.char_delay(i, ch, prev, self.burst[i])
            self.put(ch, d)
            self.carry += t.punctuation_pause(ch, text[i + 1] if i + 1 < n else "")
            i += 1

        self.revise()  # whatever is still pending
        if self.ed.text != text:
            raise PlanError("plan does not reproduce the text")

    def _revise_now(self) -> bool:
        when = self.s.revise_when
        if when == "At the end":
            return False
        if when == "After paragraphs":
            return True
        return self.rng.random() < 0.5

    def _typo(self, i: int) -> int:
        """Make a typo at text[i]; returns the next target index."""
        text, rng, t = self.text, self.rng, self.t
        ch = text[i]
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        swap_ok = typos.can_typo(nxt) and nxt.lower() != ch.lower()
        kind = typos.pick_kind(rng, swap_ok)
        wrong = typos.neighbor_of(ch, rng) if kind == "neighbor" else None
        if kind == "neighbor" and wrong is None:
            kind = "double"
        self.stats["typos"] += 1
        d = t.char_delay(i, ch, prev, False)

        # Typed characters for the mistake, and how many target chars they cover.
        if kind == "neighbor":
            typed, covers = wrong, 1
        elif kind == "double":
            typed, covers = ch + ch, 1
        else:
            typed, covers = nxt + ch, 2

        start = len(self.ed.buf)
        for k, c in enumerate(typed):
            self.put(c, d if k == 0 else t.quick_delay(), note="typo")

        if rng.random() < self.defer_share:
            # Leave it in; fix during a revision pass.
            if kind == "neighbor":
                self.add_fix(start, wrong, ch, "typo")
            elif kind == "double":
                self.add_fix(start + 1, ch, "", "typo")
            else:
                self.add_fix(start, typed, ch + nxt, "typo")
            self.stats["deferred"] += 1
            return i + covers

        # Caught: immediately, or after typing 1-3 more characters.
        self.stats["caught"] += 1
        j = i + covers
        extra = 0
        if rng.random() < 0.5:
            want = rng.randint(1, 3)
            while extra < want and j + extra < len(self.text) and self.text[j + extra] != "\n":
                extra += 1
        if extra:
            self.type_clean(self.text[j:j + extra], j, note="typo")
        self.carry += t.notice_delay() + (0.15 * extra)
        self.backspace(len(typed) + extra, note="fix")
        self.carry += t.hesitate(0.05, 0.25)
        self.type_clean(self.text[i:j + extra], i, note="fix")
        return j + extra


def _insert_breaks(actions: list[Action], every_s: float, length_s: float) -> float:
    """Insert break actions after roughly every `every_s` of typing time, at
    word boundaries. Returns total break time added."""
    if every_s <= 0 or length_s <= 0:
        return 0.0
    out: list[Action] = []
    since = 0.0
    total = 0.0
    last_value = ""
    for idx, a in enumerate(actions):
        boundary = a.kind == "char" and a.note == "type" and last_value in (" ", "enter")
        if since >= every_s and boundary and idx < len(actions) - 1:
            out.append(Action("break", "", length_s, note="break"))
            total += length_s
            since = 0.0
        out.append(a)
        since += a.delay
        last_value = a.value
    actions[:] = out
    return total


def build_plan(text: str, settings, seed: int | None = None) -> Plan:
    text = normalize_text(text)
    rng = random.Random(seed)
    b = _Builder(text, settings, rng)
    b.build()
    actions = b.actions
    typing = sum(a.delay for a in actions)

    every = settings.break_every_min * 60.0 if settings.break_enabled else 0.0
    blen = settings.break_length_min * 60.0 if settings.break_enabled else 0.0

    if settings.speed_mode == "duration" and typing > 0:
        target = max(1.0, settings.target_minutes * 60.0)
        # Solve scale so that typing*scale + breaks(typing*scale) == target.
        nbreaks = 0
        for _ in range(8):
            avail = target - nbreaks * blen
            if avail <= 1.0:
                avail = max(1.0, target * 0.5)
            scale = avail / typing
            new_n = int((typing * scale) // every) if every > 0 else 0
            if new_n == nbreaks:
                break
            nbreaks = new_n
        for a in actions:
            a.delay = max(MIN_DELAY, a.delay * scale)
        typing = sum(a.delay for a in actions)

    break_total = _insert_breaks(actions, every, blen) if every > 0 else 0.0
    return Plan(text, actions, typing, break_total, b.stats)


def verify_plan(plan: Plan) -> bool:
    ed = VirtualEditor()
    for a in plan.actions:
        ed.apply(a)
    return ed.text == plan.text and ed.cursor == len(plan.text)
