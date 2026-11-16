"""Global hotkeys (work even when Cadence isn't focused).

F8  start / resume
F9  pause
F10 emergency stop

The three keys are swallowed so they don't also reach the target app (in Word,
for instance, F8 turns on "extend selection" and F10 activates the ribbon,
which would wreck typing). Callbacks run on pynput's hook thread, so they only
push events onto a queue that the UI drains on its own thread; emergency stop
additionally calls `on_stop` directly so it can't be delayed by a busy UI.
"""
from __future__ import annotations

import queue
import sys

from pynput import keyboard

VK_ACTIONS = {0x77: "start_resume", 0x78: "pause", 0x79: "stop"}  # F8, F9, F10
KEY_ACTIONS = {keyboard.Key.f8: "start_resume", keyboard.Key.f9: "pause", keyboard.Key.f10: "stop"}
_KEYDOWN = (0x0100, 0x0104)  # WM_KEYDOWN, WM_SYSKEYDOWN


class HotkeyListener:
    def __init__(self, events: "queue.Queue[str]", on_stop=None):
        self.events = events
        self.on_stop = on_stop
        self._listener: keyboard.Listener | None = None
        self._down: set[int] = set()

    def _fire(self, action: str) -> None:
        if action == "stop" and self.on_stop:
            try:
                self.on_stop()
            except Exception:
                pass
        self.events.put(action)

    # Windows: handle and suppress inside the low-level hook filter.
    def _win32_filter(self, msg, data):
        vk = data.vkCode
        if vk not in VK_ACTIONS:
            return True
        if msg in _KEYDOWN:
            if vk not in self._down:       # ignore auto-repeat
                self._down.add(vk)
                self._fire(VK_ACTIONS[vk])
        else:
            self._down.discard(vk)
        self._listener.suppress_event()
        return False

    # Other platforms: plain listener (keys are not suppressed).
    def _on_press(self, key) -> None:
        action = KEY_ACTIONS.get(key)
        if action:
            self._fire(action)

    def start(self) -> None:
        if sys.platform == "win32":
            self._listener = keyboard.Listener(win32_event_filter=self._win32_filter)
        else:
            self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
