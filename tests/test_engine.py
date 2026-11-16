import random
import string
from dataclasses import replace

import pytest

from config.settings import WriterSettings
from engine.actions import Action, VirtualEditor
from engine.planner import build_plan, verify_plan
from engine.revisions import plan_navigation, safe_ctrl_left, safe_ctrl_right
from engine import typos

SAMPLE = (
    "The quick brown fox jumps over the lazy dog. However, it's important to note\n"
    "that many people find this very difficult — especially at first. “Smart quotes”\n"
    "and accents like café, naïve, and résumé must survive.\tTabs too!\n\n"
    "A second paragraph: numbers 3.14, e.g. abbreviations, and CAPITALS. Done? Yes 😀."
)


# ---------------------------------------------------------------- typos

def test_neighbors_are_adjacent_keys():
    assert set("qwsz") <= set(typos.NEIGHBORS["a"])
    assert "p" not in typos.NEIGHBORS["a"]
    rng = random.Random(1)
    for _ in range(50):
        w = typos.neighbor_of("G", rng)
        assert w.isupper() and w.lower() in typos.NEIGHBORS["g"]


# ---------------------------------------------------------------- editor

def test_virtual_editor_basics():
    ed = VirtualEditor()
    for c in "hello world":
        ed.apply(Action("char", c))
    ed.apply(Action("key", "left", ctrl=True))
    assert ed.cursor == 6
    ed.apply(Action("key", "backspace"))
    assert ed.text == "helloworld"
    ed.apply(Action("key", "end", ctrl=True))
    ed.apply(Action("key", "enter"))
    assert ed.text == "helloworld\n" and ed.cursor == 11


# ---------------------------------------------------------------- navigation

def _alt_ctrl_left(buf, p):
    """A different editor's idea of Ctrl+Left/Right: apostrophes and accented
    letters are part of words, each punctuation mark is its own stop, and
    Ctrl+Right from whitespace behaves like the Win32 EDIT control."""
    def word(c):
        return c.isalnum() or c == "'"
    q = p
    while q > 0 and buf[q - 1].isspace():
        q -= 1
    if q > 0 and not word(buf[q - 1]):
        return q - 1
    while q > 0 and word(buf[q - 1]):
        q -= 1
    return q


def _alt_ctrl_right(buf, p):
    def word(c):
        return c.isalnum() or c == "'"
    n = len(buf)
    q = p
    if q < n and buf[q].isspace():
        # Win32 EDIT quirk (measured): starting on whitespace skips the next word too.
        while q < n and buf[q].isspace():
            q += 1
        while q < n and word(buf[q]):
            q += 1
    elif q < n and not word(buf[q]):
        q += 1
    else:
        while q < n and word(buf[q]):
            q += 1
    while q < n and buf[q].isspace():
        q += 1
    return q


def _random_buffer(rng, n):
    alphabet = string.ascii_letters + "     ,.'!-\n" + "éü’—" + string.digits
    return [rng.choice(alphabet) for _ in range(n)]


@pytest.mark.parametrize("seed", range(40))
def test_navigation_lands_exactly_under_two_editor_models(seed):
    rng = random.Random(seed)
    buf = _random_buffer(rng, rng.randint(5, 120))
    for _ in range(30):
        a, b = rng.randint(0, len(buf)), rng.randint(0, len(buf))
        keys = plan_navigation(buf, a, b, word_jumps=True)
        p_model = p_alt = a
        for name, ctrl in keys:
            if ctrl:
                if name == "left":
                    assert safe_ctrl_left(buf, p_model) is not None
                    p_model = safe_ctrl_left(buf, p_model)
                    p_alt = _alt_ctrl_left(buf, p_alt)
                else:
                    assert safe_ctrl_right(buf, p_model) is not None
                    p_model = safe_ctrl_right(buf, p_model)
                    p_alt = _alt_ctrl_right(buf, p_alt)
            else:
                d = -1 if name == "left" else 1
                p_model += d
                p_alt += d
        assert p_model == b
        assert p_alt == b, "a plan only works in one editor model"


def test_word_jumps_save_keystrokes():
    buf = list("one two three four five six seven eight nine ten")
    jumps = plan_navigation(buf, len(buf), 4)
    arrows = plan_navigation(buf, len(buf), 4, word_jumps=False)
    assert len(arrows) == len(buf) - 4
    assert len(jumps) < len(arrows) / 3


def test_ctrl_jumps_never_cross_punctuation_or_leave_our_text():
    buf = list("don't, stop")
    # From the end, jumping to "stop" is fine; jumping across ", " is not.
    assert safe_ctrl_left(buf, len(buf)) == 7
    assert safe_ctrl_left(buf, 7) is None
    # Never Ctrl+Right into the end of our buffer (unknown text may follow).
    assert safe_ctrl_right(list("hello world"), 6) is None
    # Never Ctrl+Left to index 0 (unknown text may precede).
    assert safe_ctrl_left(list("hello"), 5) is None


def test_doc_anchors_used_only_when_allowed():
    buf = list("x" * 300)
    without = plan_navigation(buf, 300, 2, doc_anchors=False)
    assert all(name != "home" for name, _ in without)
    with_ = plan_navigation(buf, 300, 2, doc_anchors=True)
    assert with_[0] == ("home", True) and len(with_) == 3


# ---------------------------------------------------------------- plans

HEAVY = WriterSettings(typo_rate=0.10, revise_enabled=True, revision_amount="Many",
                       rethink_enabled=True, thinking_freq=0.2, fatigue_enabled=True)

COMBOS = [
    WriterSettings(),
    HEAVY,
    replace(HEAVY, revise_when="At the end"),
    replace(HEAVY, revise_when="After paragraphs", word_jumps=False),
    replace(HEAVY, empty_doc=True),
    replace(HEAVY, revise_enabled=False),
    WriterSettings(typo_rate=0, revise_enabled=False, rethink_enabled=False),
]


@pytest.mark.parametrize("settings", COMBOS)
@pytest.mark.parametrize("seed", range(12))
def test_plan_reproduces_text_exactly(settings, seed):
    plan = build_plan(SAMPLE, settings, seed=seed)
    assert verify_plan(plan)


@pytest.mark.parametrize("seed", range(25))
def test_random_texts_survive_heavy_revisions(seed):
    rng = random.Random(1000 + seed)
    words = ["the", "important", "very", "big", "really", "however", "café", "it's",
             "people", "a", "difficult", "quickly", "x", "show", "—", "end."]
    paras = []
    for _ in range(rng.randint(1, 4)):
        paras.append(" ".join(rng.choice(words) for _ in range(rng.randint(3, 40))))
    text = "\n".join(paras)
    plan = build_plan(text, HEAVY, seed=seed)
    assert verify_plan(plan)


def test_mistakes_and_revisions_actually_happen():
    text = (SAMPLE + "\n") * 6
    plan = build_plan(text, HEAVY, seed=7)
    st = plan.stats
    assert st["typos"] > 20 and st["caught"] > 5 and st["deferred"] > 5
    assert st["revision_passes"] >= 1
    notes = {a.note for a in plan.actions}
    assert {"typo", "fix", "nav", "revise"} <= notes


def test_clean_settings_type_text_verbatim():
    s = WriterSettings(typo_rate=0, revise_enabled=False, rethink_enabled=False)
    plan = build_plan(SAMPLE, s, seed=3)
    chars = [a for a in plan.actions if a.kind == "char"]
    keys = [a for a in plan.actions if a.kind == "key"]
    assert all(k.value in ("enter", "tab") for k in keys)
    assert len(chars) + len(keys) == len(SAMPLE)


def test_newline_as_shift_enter():
    s = WriterSettings(typo_rate=0, revise_enabled=False, rethink_enabled=False, shift_enter=True)
    plan = build_plan("a\nb", s, seed=1)
    enter = [a for a in plan.actions if a.value == "enter"][0]
    assert enter.shift


# ---------------------------------------------------------------- timing

def test_higher_wpm_is_faster():
    slow = build_plan(SAMPLE, WriterSettings(wpm=30), seed=5).total_seconds
    fast = build_plan(SAMPLE, WriterSettings(wpm=120), seed=5).total_seconds
    assert fast < slow * 0.6


def test_estimate_includes_pauses_and_mistakes():
    base = WriterSettings(wpm=60, typo_rate=0, revise_enabled=False, rethink_enabled=False, fatigue_enabled=False,
                          punct_pause_scale=0, thinking_freq=0, speed_variance=0, burst_enabled=False)
    plan = build_plan("hello world " * 20, base, seed=1)
    # 240 chars at 60 wpm = 0.2 s/char => 48 s
    assert plan.total_seconds == pytest.approx(48, rel=0.02)
    messy = build_plan("hello world " * 20, replace(base, typo_rate=0.1, punct_pause_scale=2, thinking_freq=0.2), seed=1)
    assert messy.total_seconds > plan.total_seconds * 1.2


def test_target_duration_mode_hits_target():
    s = WriterSettings(speed_mode="duration", target_minutes=12)
    plan = build_plan(SAMPLE * 3, s, seed=2)
    assert plan.total_seconds == pytest.approx(12 * 60, rel=0.01)
    assert verify_plan(plan)


def test_break_mode_inserts_breaks_and_counts_them():
    s = WriterSettings(speed_mode="duration", target_minutes=30, break_enabled=True,
                       break_every_min=5, break_length_min=1)
    plan = build_plan(SAMPLE * 4, s, seed=4)
    breaks = [a for a in plan.actions if a.kind == "break"]
    assert 3 <= len(breaks) <= 5
    assert plan.break_seconds == pytest.approx(60 * len(breaks))
    assert plan.total_seconds == pytest.approx(30 * 60, rel=0.04)


def test_fatigue_slows_the_end():
    s = WriterSettings(typo_rate=0, revise_enabled=False, rethink_enabled=False, punct_pause_scale=0,
                       thinking_freq=0, fatigue_enabled=True, speed_variance=0, burst_enabled=False)
    plan = build_plan("abcd " * 200, s, seed=1)
    first = sum(a.delay for a in plan.actions[:100])
    last = sum(a.delay for a in plan.actions[-100:])
    assert last > first * 1.2


def test_same_seed_same_plan():
    a = build_plan(SAMPLE, HEAVY, seed=9)
    b = build_plan(SAMPLE, HEAVY, seed=9)
    assert [(x.kind, x.value, x.delay) for x in a.actions] == [(x.kind, x.value, x.delay) for x in b.actions]


# ---------------------------------------------------------------- session

def _fast_plan(text, **kw):
    s = WriterSettings(wpm=150, punct_pause_scale=0, thinking_freq=0, typo_rate=0.08,
                       revision_amount="Many", **kw)
    plan = build_plan(text, s, seed=11)
    for a in plan.actions:
        a.delay = 0.0005
    return plan, s


def test_session_types_through_virtual_backend(monkeypatch):
    import engine.typer as typer
    monkeypatch.setattr(typer, "foreground_window", lambda: 1234)
    monkeypatch.setattr(typer, "window_pid", lambda h: -1)
    plan, s = _fast_plan(SAMPLE)
    be = typer.VirtualBackend()
    sess = typer.TypingSession(plan, s, backend=be)
    sess.start(countdown=0)
    sess.join(10)
    assert sess.status.state == "done"
    assert be.ed.text == plan.text


def test_session_stop_is_immediate_even_mid_pause(monkeypatch):
    import time
    import engine.typer as typer
    monkeypatch.setattr(typer, "foreground_window", lambda: 1)
    monkeypatch.setattr(typer, "window_pid", lambda h: -1)
    plan, s = _fast_plan("hello world")
    plan.actions[3].delay = 60.0  # a long "thinking" pause
    sess = typer.TypingSession(plan, s, backend=typer.VirtualBackend())
    sess.start(countdown=0)
    time.sleep(0.2)
    t = time.perf_counter()
    sess.stop()
    sess.join(2)
    assert not sess.alive and time.perf_counter() - t < 0.3
    assert sess.status.state == "stopped"


def test_focus_lock_pauses_and_resume_continues(monkeypatch):
    import time
    import engine.typer as typer
    current = {"hwnd": 1}
    monkeypatch.setattr(typer, "foreground_window", lambda: current["hwnd"])
    monkeypatch.setattr(typer, "window_pid", lambda h: -1)
    monkeypatch.setattr(typer.TypingSession, "RESUME_COUNTDOWN", 0.05)
    plan, s = _fast_plan(SAMPLE)
    for a in plan.actions:
        a.delay = 0.002
    be = typer.VirtualBackend()
    sess = typer.TypingSession(plan, s, backend=be)
    sess.start(countdown=0)
    time.sleep(0.1)
    current["hwnd"] = 2                      # user switched windows
    time.sleep(0.15)
    st = sess.status
    assert st.state == "paused" and "Focus" in st.message
    typed = len(be.ed.buf)
    time.sleep(0.1)
    assert len(be.ed.buf) == typed           # nothing typed into the wrong window
    sess.resume()                            # still wrong window -> stays paused
    time.sleep(0.2)
    assert sess.status.state == "paused"
    current["hwnd"] = 1
    sess.resume()
    sess.join(10)
    assert sess.status.state == "done" and be.ed.text == plan.text
