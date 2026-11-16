"""Executes a Plan against the real keyboard on a background thread."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from dataclasses import dataclass

from .actions import Action, VirtualEditor
from .planner import Plan
from .revisions import plan_navigation

# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class KeyboardBackend:
    """Sends keystrokes to whatever window has focus.

    Characters are injected as Unicode (KEYEVENTF_UNICODE) so Caps Lock, the
    keyboard layout and dead keys can't change what gets typed. Special keys
    go through pynput.
    """

    def __init__(self):
        from pynput.keyboard import Controller, Key
        self._kb = Controller()
        self._Key = Key
        self._map = {
            "backspace": Key.backspace, "left": Key.left, "right": Key.right,
            "home": Key.home, "end": Key.end, "enter": Key.enter, "tab": Key.tab,
        }

    def char(self, c: str) -> None:
        _send_unicode(c)

    def key(self, name: str, ctrl: bool = False, shift: bool = False) -> None:
        k = self._map[name]
        mods = []
        if ctrl:
            mods.append(self._Key.ctrl)
        if shift:
            mods.append(self._Key.shift)
        for m in mods:
            self._kb.press(m)
        try:
            self._kb.press(k)
            self._kb.release(k)
        finally:
            for m in reversed(mods):
                self._kb.release(m)

    def release_all(self) -> None:
        for m in (self._Key.ctrl, self._Key.shift):
            try:
                self._kb.release(m)
            except Exception:
                pass


class VirtualBackend:
    """For tests and dry runs: types into a VirtualEditor."""

    def __init__(self):
        self.ed = VirtualEditor()

    def char(self, c: str) -> None:
        self.ed.apply(Action("char", c))

    def key(self, name: str, ctrl: bool = False, shift: bool = False) -> None:
        self.ed.apply(Action("key", name, ctrl=ctrl))

    def release_all(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004

    def _send_unicode(c: str) -> None:
        data = c.encode("utf-16-le")
        units = [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]
        events = []
        for u in units:
            for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
                inp = _INPUT(type=1)
                inp.u.ki = _KEYBDINPUT(0, u, flags, 0, 0)
                events.append(inp)
        arr = (_INPUT * len(events))(*events)
        _user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))

    def foreground_window() -> int:
        hwnd = _user32.GetForegroundWindow()
        root = _user32.GetAncestor(hwnd, 3)  # GA_ROOTOWNER
        return int(root or hwnd or 0)

    def window_pid(hwnd: int) -> int:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return pid.value

    def _timer_resolution(on: bool) -> None:
        """1 ms timer resolution while typing so short delays are accurate."""
        try:
            winmm = ctypes.WinDLL("winmm")
            (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
        except OSError:
            pass

    def window_title(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 256)
        return buf.value
else:  # pragma: no cover - Cadence targets Windows
    def _send_unicode(c: str) -> None:
        raise OSError("Unicode injection is only implemented on Windows")

    def foreground_window() -> int:
        return 0

    def window_pid(hwnd: int) -> int:
        return 0

    def window_title(hwnd: int) -> str:
        return ""

    def _timer_resolution(on: bool) -> None:
        pass


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Status:
    state: str = "idle"        # idle|countdown|typing|paused|break|resuming|done|stopped|error
    message: str = ""
    progress: float = 0.0      # 0..1 of planned time
    remaining: float = 0.0     # seconds of planned time left (incl. breaks)
    countdown: float = 0.0
    typed_chars: int = 0
    total_chars: int = 0
    target_title: str = ""


class TypingSession:
    """Runs a plan on a worker thread. All public methods are thread-safe."""

    RESUME_COUNTDOWN = 3.0

    def __init__(self, plan: Plan, settings, backend=None, focus_check: bool | None = None,
                 on_keystroke=None):
        self.plan = plan
        self.s = settings
        self.backend = backend or KeyboardBackend()
        self.focus_lock = settings.focus_lock if focus_check is None else focus_check
        self.on_keystroke = on_keystroke
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._resume = threading.Event()
        self._lock = threading.Lock()
        self._status = Status(total_chars=len(plan.text), remaining=plan.total_seconds)
        self._ed = VirtualEditor()      # mirror of the target document
        self._done_time = 0.0           # planned seconds already consumed
        self._target_hwnd = 0
        self._thread = threading.Thread(target=self._run, name="cadence-typer", daemon=True)

    # ---- control ----
    def start(self, countdown: float | None = None) -> None:
        self._countdown_s = float(self.s.countdown if countdown is None else countdown)
        self._thread.start()

    def pause(self, reason: str = "Paused") -> None:
        with self._lock:
            if self._status.state in ("typing", "break", "countdown", "resuming"):
                self._pause.set()
                self._resume.clear()
                self._set(state="paused", message=reason)

    def _force_pause(self, reason: str) -> None:
        with self._lock:
            self._pause.set()
            self._resume.clear()
            self._set(state="paused", message=reason)

    def resume(self) -> None:
        with self._lock:
            if self._status.state == "paused":
                self._resume.set()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()

    def join(self, timeout=None) -> None:
        self._thread.join(timeout)

    @property
    def status(self) -> Status:
        with self._lock:
            return Status(**self._status.__dict__)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    # ---- internals ----
    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self._status, k, v)

    def _update(self, **kw) -> None:
        with self._lock:
            self._set(**kw)

    def _sleep(self, seconds: float, counting: bool = True) -> bool:
        """Interruptible sleep that honours pause. Returns False if stopped."""
        end = time.perf_counter() + seconds
        while True:
            if self._stop.is_set():
                return False
            if self._pause.is_set():
                left = end - time.perf_counter()
                if not self._wait_resume():
                    return False
                end = time.perf_counter() + max(0.0, left)
                continue
            left = end - time.perf_counter()
            if left <= 0:
                return True
            if counting:
                self._update(remaining=max(0.0, self.plan.total_seconds - self._done_time - (seconds - left)))
            self._stop.wait(min(left, 0.05))

    def _wait_resume(self) -> bool:
        """Block while paused; run the resume countdown and focus check."""
        while True:
            self._resume.wait()
            if self._stop.is_set():
                return False
            self._resume.clear()
            with self._lock:
                self._set(state="resuming", message="Resuming — switch back with Alt+Tab or the taskbar")
            t_end = time.perf_counter() + self.RESUME_COUNTDOWN
            while (left := t_end - time.perf_counter()) > 0:
                if self._stop.is_set():
                    return False
                self._update(countdown=left)
                self._stop.wait(min(left, 0.05))
            self._update(countdown=0.0)
            problem = self._focus_problem()
            if problem:
                with self._lock:
                    self._set(state="paused", message=problem)
                continue
            if self.s.empty_doc:
                self._reanchor()
            with self._lock:
                self._pause.clear()
                self._set(state="typing", message="")
            return True

    def _focus_problem(self) -> str:
        hwnd = foreground_window()
        if hwnd and window_pid(hwnd) == os.getpid():
            return "Cadence has focus — click the target window, then press F8"
        if self.focus_lock and self._target_hwnd and hwnd != self._target_hwnd:
            return f"Focus moved away from “{self._status.target_title or 'the target window'}” — go back and press F8"
        return ""

    def _reanchor(self) -> None:
        """Ctrl+End to the end of the document, then walk back to our caret.
        Only valid when the document holds nothing but our text."""
        self.backend.key("end", ctrl=True)
        keys = plan_navigation(self._ed.buf, len(self._ed.buf), self._ed.cursor,
                               word_jumps=self.s.word_jumps, doc_anchors=False)
        for name, ctrl in keys:
            time.sleep(0.03)
            self.backend.key(name, ctrl=ctrl)

    def _run(self) -> None:
        _timer_resolution(True)
        try:
            self._update(state="countdown", message="Click into the target window")
            t_end = time.perf_counter() + self._countdown_s
            while (left := t_end - time.perf_counter()) > 0:
                if self._stop.is_set():
                    return self._finish("stopped", "Stopped")
                if self._pause.is_set():
                    if not self._wait_resume():
                        return self._finish("stopped", "Stopped")
                    break
                self._update(countdown=left)
                self._stop.wait(min(left, 0.05))
            self._update(countdown=0.0)

            hwnd = foreground_window()
            if hwnd and window_pid(hwnd) == os.getpid():
                with self._lock:
                    self._pause.set()
                    self._set(state="paused", message="Cadence has focus — click the target window, then press F8")
                if not self._wait_resume():
                    return self._finish("stopped", "Stopped")
                hwnd = foreground_window()
            self._target_hwnd = hwnd
            self._update(state="typing", message="", target_title=window_title(hwnd))

            for a in self.plan.actions:
                if a.kind == "break":
                    self._update(state="break", message="On a break")
                    if not self._sleep(a.delay):
                        return self._finish("stopped", "Stopped")
                    self._done_time += a.delay
                    problem = self._focus_problem()
                    if problem:
                        self._force_pause(problem)
                        if not self._sleep(0):
                            return self._finish("stopped", "Stopped")
                    self._update(state="typing", message="")
                    continue

                if not self._sleep(a.delay):
                    return self._finish("stopped", "Stopped")
                # Focus lock: re-check right before every keystroke.
                problem = self._focus_problem()
                while problem:
                    self._force_pause(problem)
                    if not self._sleep(0):
                        return self._finish("stopped", "Stopped")
                    problem = self._focus_problem()
                if self._stop.is_set():
                    return self._finish("stopped", "Stopped")

                if a.kind == "char":
                    self.backend.char(a.value)
                else:
                    self.backend.key(a.value, ctrl=a.ctrl, shift=a.shift)
                self._ed.apply(a)
                if self.on_keystroke and (a.kind == "char" or a.value in ("enter", "backspace", "tab")):
                    self.on_keystroke()
                self._done_time += a.delay
                total = self.plan.total_seconds or 1.0
                self._update(progress=min(1.0, self._done_time / total),
                             remaining=max(0.0, total - self._done_time),
                             typed_chars=len(self._ed.buf))
            self._finish("done", "Finished")
        except Exception as e:  # never leave a modifier held down
            self._finish("error", f"Error: {e}")
        finally:
            self.backend.release_all()
            _timer_resolution(False)

    def _finish(self, state: str, msg: str) -> None:
        with self._lock:
            self._set(state=state, message=msg, countdown=0.0)
            if state == "done":
                self._set(progress=1.0, remaining=0.0)
