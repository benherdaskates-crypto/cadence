"""Cadence: pywebview shell. The UI is web/ (HTML/CSS/JS); everything else
is Python, exposed to the page through the `Api` class (window.pywebview.api)."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, fields, replace
from pathlib import Path

import webview

from config import presets
import fileio
import installer
import updater
from version import UPDATE_REPO, VERSION
from config.settings import UI_SCALES, AppSettings, HumanizerSettings, WriterSettings, config_dir
from config.store import Drafts, History
from engine import sounds
from engine.planner import PlanError, build_plan
from engine.typer import TypingSession
from hotkeys import HotkeyListener
from humanizer import ollama, rules
from humanizer import style as style_mod
from humanizer.diff import change_ratio, word_diff

LIVE = {"countdown", "typing", "paused", "break", "resuming"}
MINI_FULL = (322, 178)


def resource(*parts) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base.joinpath(*parts))


def js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Clipboard (Win32, no extra dependencies)
# ---------------------------------------------------------------------------
def _clipboard_get() -> str:
    if sys.platform != "win32":
        return ""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not u.OpenClipboard(None):
        return ""
    try:
        h = u.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        p = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


def _clipboard_set(text: str) -> bool:
    if sys.platform != "win32":
        return False
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not u.OpenClipboard(None):
        return False
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k.GlobalUnlock(h)
        return bool(u.SetClipboardData(13, h))
    finally:
        u.CloseClipboard()


def _dark_title_bar(window) -> None:
    """Windows 10/11: make the native title bar dark to match the app."""
    try:
        hwnd = window.native.Handle.ToInt32()
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
        color = ctypes.c_int(0x000B0A0A)  # caption colour #0a0a0b (COLORREF is BGR)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class CadenceApp:
    def __init__(self):
        self.settings = AppSettings.load()
        self.api = Api(self)
        self.session: TypingSession | None = None
        self.seed = random.randrange(1 << 30)
        self.last_text = ""
        self.main = None
        self.mini = None
        self.in_mini = False
        self.mini_collapsed = False
        self._save_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._h_cancel: threading.Event | None = None
        self._events: queue.Queue[str] = queue.Queue()
        self._hotkeys = HotkeyListener(self._events, on_stop=self.stop)
        self._quitting = False
        self.ollama_status = None
        self.styles = style_mod.StyleStore(config_dir() / "styles.json")
        self.drafts = Drafts(config_dir() / "drafts.json")
        self.history = History(config_dir() / "history.json")
        self._migrate_voice_sample()

    def _migrate_voice_sample(self):
        """Older versions kept one 'Keep my voice' sample; turn it into a saved style."""
        hs = self.settings.humanizer
        if hs.voice_sample.strip() and not self.styles.items:
            try:
                item = self.styles.save("My voice", hs.voice_sample)
                hs.style_id = item.id
            except ValueError:
                pass
            hs.voice_sample = ""
            self.save_soon()

    # ---------------------------------------------------------------- windows
    def run(self, debug: bool = False):
        ui = self.settings.ui
        w, h, x, y = self._main_geometry()
        self.main = webview.create_window(
            "Cadence", url=resource("web", "index.html"), js_api=self.api, width=w, height=h, x=x, y=y,
            min_size=(int(980 * ui.scale), int(640 * ui.scale)), background_color="#0a0a0b")
        x, y = self._mini_xy()
        self.mini = webview.create_window(
            "Cadence mini", url=resource("web", "mini.html"), js_api=self.api,
            width=int(MINI_FULL[0] * ui.scale), height=int(MINI_FULL[1] * ui.scale), x=x, y=y,
            frameless=True, easy_drag=False,
            on_top=True, hidden=True, resizable=False, shadow=False, min_size=(80, 36),
            background_color="#141416", focus=False)
        self.main.events.shown += lambda: _dark_title_bar(self.main)
        self.main.events.closing += self._on_main_closing
        port = os.environ.get("CADENCE_REMOTE_DEBUG_PORT")     # only for automated end-to-end tests
        if port and port.isdigit():
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(port)
        webview.start(self._background, debug=debug, private_mode=True, icon=resource("assets", "cadence.ico"))

    def _main_geometry(self):
        """Last window size/position if it still fits on screen, else a default scaled to the UI size."""
        ui = self.settings.ui
        try:
            sw, sh = webview.screens[0].width, webview.screens[0].height
        except Exception:
            sw, sh = 1920, 1080
        if len(ui.window) == 4:
            w, h, x, y = (int(v) for v in ui.window)
            if 600 <= w <= sw + 50 and 400 <= h <= sh + 50 and -50 <= x <= sw - 200 and -10 <= y <= sh - 100:
                return w, h, x, y
        w = min(int(1300 * ui.scale), sw - 80)
        h = min(int(880 * ui.scale), sh - 100)
        return w, h, None, None

    def _remember_main_geometry(self):
        try:
            m = self.main
            if m and m.width and m.height and not self.in_mini:
                self.settings.ui.window = [int(m.width), int(m.height), int(m.x), int(m.y)]
        except Exception:
            pass

    def _mini_xy(self):
        if self.settings.mini_pos:
            return tuple(int(v) for v in self.settings.mini_pos)
        try:
            sw = webview.screens[0].width
        except Exception:
            sw = 1920
        return sw - MINI_FULL[0] - 24, 24

    def _background(self):
        try:
            self._hotkeys.start()
        except Exception:
            pass
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self._detect_ollama, daemon=True).start()
        threading.Thread(target=self._auto_update_check, daemon=True).start()

    def _auto_update_check(self):
        """At most about once a day, quietly look for a newer version and tell the page."""
        ui = self.settings.ui
        if not (ui.auto_update and UPDATE_REPO and installer.current_exe()):
            return
        if time.time() - ui.last_update_check < 20 * 3600:
            return
        time.sleep(8)                            # let startup finish first
        try:
            info = updater.check()
        except updater.UpdateError:
            return
        ui.last_update_check = time.time()
        self.save_soon()
        if info.get("available"):
            self.push(f"window.cadence.updateAvailable && window.cadence.updateAvailable({js(info)})")

    def _detect_ollama(self):
        """Checked in the background so a missing/slow Ollama never delays startup."""
        st = ollama.detect()
        self.ollama_status = {"running": st.running, "models": st.models, "default": st.default_model, "version": st.version}
        for _ in range(50):                      # wait until the page can receive it
            try:
                if self.main.evaluate_js("typeof window.cadence === 'object' && !!window.cadence.ollama"):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        self.push(f"window.cadence.ollama({js(self.ollama_status)})")

    def _on_main_closing(self):
        self._quitting = True
        self._remember_main_geometry()
        self.stop()
        self.save_now()
        self.drafts.flush()
        try:
            self._hotkeys.stop()
        except Exception:
            pass
        if self.mini:
            try:
                self.mini.destroy()
            except Exception:
                pass

    def push(self, script: str, mini: bool = False):
        for w in ((self.main, self.mini) if mini else (self.main,)):
            if w is not None:
                try:
                    w.run_js(script)
                except Exception:
                    pass

    # ---------------------------------------------------------------- settings
    def save_soon(self):
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.8, self.save_now)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save_now(self):
        try:
            self.settings.save()
        except OSError:
            pass

    # ---------------------------------------------------------------- typing
    def start_or_resume(self, text: str | None = None) -> dict:
        s = self.session
        if s and s.alive:
            if s.status.state == "paused":
                s.resume()
                return {"ok": True, "resumed": True}
            return {"ok": False, "error": "Already typing."}
        text = self.last_text if text is None else text
        if not text.strip():
            return {"ok": False, "error": "Paste or write some text to type first."}
        self.last_text = text
        ws = replace(self.settings.writer)
        try:
            plan = build_plan(text, ws, seed=self.seed)
        except PlanError as e:
            return {"ok": False, "error": f"Couldn't plan this text: {e}"}
        self.session = TypingSession(plan, ws, on_keystroke=sounds.click if ws.sounds else None)
        self.session.start()
        self.seed = random.randrange(1 << 30)
        return {"ok": True, "auto_mini": ws.auto_mini}

    def pause(self):
        if self.session and self.session.alive:
            self.session.pause("Paused. Press F8 to resume.")

    def resume(self):
        if self.session and self.session.alive:
            self.session.resume()

    def stop(self):
        if self.session:
            self.session.stop()

    def _hotkey_loop(self):
        while not self._quitting:
            try:
                ev = self._events.get(timeout=0.5)
            except queue.Empty:
                continue
            if ev == "start_resume":
                s = self.session
                if s and s.alive:
                    self.resume()
                else:
                    res = self.start_or_resume(None)
                    if res.get("ok") and res.get("auto_mini") and not self.in_mini:
                        self.push("window.cadence.enterMini && window.cadence.enterMini()")
                    elif not res.get("ok"):
                        self.push(f"window.cadence.toast && window.cadence.toast({js(res.get('error', ''))})")
            elif ev == "pause":
                self.pause()
            elif ev == "stop":
                self.stop()

    def _status_loop(self):
        samples: deque = deque()
        active = 0.0
        last_t = time.perf_counter()
        last_session = None
        finished_pushed = True
        while not self._quitting:
            time.sleep(0.1)
            s = self.session
            now = time.perf_counter()
            dt, last_t = now - last_t, now
            if s is None:
                continue
            if s is not last_session:
                last_session, samples, active, finished_pushed = s, deque(), 0.0, False
            st = s.status
            if st.state not in LIVE and finished_pushed:
                continue
            if st.state == "typing":
                active += dt
                samples.append((now, st.typed_chars))
            while samples and now - samples[0][0] > 3.0:
                samples.popleft()
            wpm = 0.0
            if st.state == "typing" and len(samples) >= 2 and samples[-1][0] - samples[0][0] > 0.5:
                (t0, c0), (t1, c1) = samples[0], samples[-1]
                wpm = max(0.0, (c1 - c0) / 5.0 / ((t1 - t0) / 60.0))
            avg = (st.typed_chars / 5.0) / (active / 60.0) if active > 5 else 0.0
            payload = {
                "state": st.state, "message": st.message, "progress": st.progress, "remaining": st.remaining,
                "total": s.plan.total_seconds, "countdown": st.countdown, "typed_chars": st.typed_chars,
                "total_chars": st.total_chars, "target_title": st.target_title, "wpm": round(wpm, 1),
                "avg_wpm": round(avg, 1),
            }
            self.push(f"window.cadence.status({js(payload)})", mini=True)
            if st.state not in LIVE:
                finished_pushed = True

    # ---------------------------------------------------------------- mini mode
    def _mini_hwnd(self) -> int:
        try:
            return int(self.mini.native.Handle.ToInt64())
        except Exception:
            return 0

    def enter_mini(self):
        self.in_mini = True
        hwnd = self._mini_hwnd()
        if hwnd:
            # pywebview's show() activates the window, which would steal keyboard
            # focus from the app being typed into. Show it without activating.
            ctypes.windll.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            self.mini.run_js("window.cadence.shown && window.cadence.shown()")
        if self.main:
            self.main.hide()

    def leave_mini(self):
        self.in_mini = False
        self._remember_mini_pos()
        if self.mini:
            self.mini.hide()
        if self.main:
            self.main.show()
            self.main.restore()
            self.push("window.cadence.restore && window.cadence.restore()")

    def _remember_mini_pos(self):
        try:
            if self.mini and self.mini.x is not None:
                self.settings.mini_pos = [int(self.mini.x), int(self.mini.y)]
                self.save_soon()
        except Exception:
            pass

    def mini_resize(self, w: int, h: int, radius: float = 20):
        """Size the mini window to the panel and clip it to the panel's rounded
        shape. Values are device pixels measured by the page itself."""
        if not self.mini or w < 60 or h < 30:   # ignore layouts measured while hidden
            return
        hwnd = self._mini_hwnd()
        if not hwnd:
            return
        pw, ph, d = int(w), int(h), max(2, round(2 * radius))
        # Not pywebview's resize(): it calls SetWindowPos without SWP_NOACTIVATE,
        # which would pull keyboard focus away from the window being typed into.
        SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x2, 0x4, 0x10
        ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, pw, ph, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, pw + 1, ph + 1, d, d)
        ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)   # the window owns rgn afterwards

    def quit(self):
        self._quitting = True
        self._remember_main_geometry()
        self.stop()
        self._remember_mini_pos()
        self.save_now()
        self.drafts.flush()
        for w in (self.mini, self.main):
            try:
                if w:
                    w.destroy()
            except Exception:
                pass

    # ---------------------------------------------------------------- humanizer
    def humanize(self, text: str, opts: dict) -> dict:
        if self._h_cancel is not None:
            return {"ok": False, "error": "Already rewriting."}
        engine = opts.get("engine", "rules")
        tone = opts.get("tone", "Neutral")
        strength = int(opts.get("strength", 1))
        tpl = self.styles.get(opts.get("style_id") or "")
        style_text = tpl.text if tpl else ""
        profile = style_mod.analyze(style_text) if style_text else None
        if not text.strip():
            return {"ok": False, "error": "Paste the text you want to humanize first."}
        if engine == "rules":
            seed = random.randrange(1 << 30)
            t0 = time.perf_counter()
            res = rules.humanize(text, strength, tone, seed=seed, style=profile)
            self.history.add(text, res.text, "rules", tone, strength, tpl.name if tpl else "")
            return {"ok": True, "text": res.text, "stats": res.stats, "elapsed": time.perf_counter() - t0,
                    "changed": change_ratio(text, res.text)}
        cancel = threading.Event()
        self._h_cancel = cancel
        model = opts.get("model") or ""

        def work():
            buf, last = {}, [time.perf_counter()]

            def flush(i=None):
                for k, v in list(buf.items()):
                    if v:
                        self.push(f"window.cadence.hDelta({k}, {js(v)})")
                buf.clear()
                last[0] = time.perf_counter()

            def on_delta(i, d):
                buf[i] = buf.get(i, "") + d
                if time.perf_counter() - last[0] > 0.06:
                    flush()

            def on_para(i, final):
                flush()
                self.push(f"window.cadence.hParagraph({i}, {js(final)})")

            t0 = time.perf_counter()
            try:
                res = ollama.humanize(text, model, tone, strength, opts.get("reading_level", "High school"),
                                      style_text, cancel=cancel,
                                      on_progress=lambda a, b: self.push(f"window.cadence.hProgress({a}, {b})"),
                                      on_delta=on_delta, on_paragraph=on_para)
                self.history.add(text, res["text"], "ollama", tone, strength, tpl.name if tpl else "")
                info = {"fallbacks": res["fallbacks"], "elapsed": time.perf_counter() - t0,
                        "changed": change_ratio(text, res["text"])}
                self.push(f"window.cadence.hDone({js(res['text'])}, {js(info)})")
            except ollama.OllamaError as e:
                self.push(f"window.cadence.hError({js(str(e))})")
            except Exception as e:  # pragma: no cover
                self.push(f"window.cadence.hError({js('Unexpected error: ' + str(e))})")
            finally:
                self._h_cancel = None
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "streaming": True}

    def cancel_humanize(self):
        if self._h_cancel is not None:
            self._h_cancel.set()


# ---------------------------------------------------------------------------
# JS API (window.pywebview.api.*). Only public methods are exposed.
# ---------------------------------------------------------------------------
class Api:
    def __init__(self, app: CadenceApp):
        self._app = app

    # ---- state
    def init_state(self):
        a = self._app
        ui = asdict(a.settings.ui)
        ui["scale"] = a.settings.ui.scale
        return {"writer": asdict(a.settings.writer), "preset": a.settings.last_preset,
                "humanizer": asdict(a.settings.humanizer), "presets": self.list_presets(),
                "ollama": a.ollama_status, "config_dir": str(config_dir()), "version": VERSION, "ui": ui,
                "sizes": list(UI_SCALES), "install": installer.status(),
                "updates": {"configured": bool(UPDATE_REPO), "repo": UPDATE_REPO},
                "styles": a.styles.list(), "drafts": a.drafts.get()}

    # ---- writer settings & presets
    def set_writer_setting(self, key, value):
        ws = self._app.settings.writer
        defaults = {f.name: f.default for f in fields(WriterSettings)}
        if key not in defaults:
            return False
        d = defaults[key]
        try:
            value = type(d)(value) if not isinstance(d, bool) else bool(value)
        except (TypeError, ValueError):
            return False
        setattr(ws, key, value)
        if key in presets.PRESET_FIELDS:
            self._app.settings.last_preset = "Custom"
        self._app.save_soon()
        return True

    def apply_preset(self, name):
        values = presets.get(name)
        if values:
            presets.apply(self._app.settings.writer, values)
            self._app.settings.last_preset = name
            self._app.save_soon()
        return asdict(self._app.settings.writer)

    def list_presets(self):
        out = []
        for n in presets.all_names():
            out.append({"name": n, "builtin": n in presets.BUILTIN, "values": presets.get(n)})
        return out

    def save_preset(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "Give the preset a name."}
        try:
            presets.save_as(name, self._app.settings.writer)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        self._app.settings.last_preset = name
        self._app.save_soon()
        return {"ok": True, "presets": self.list_presets()}

    def delete_preset(self, name):
        try:
            presets.delete(name)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "presets": self.list_presets()}

    # ---- writer
    def estimate(self, text):
        a = self._app
        a.last_text = text
        if not text.strip():
            return None
        try:
            plan = build_plan(text, replace(a.settings.writer), seed=a.seed)
        except PlanError:
            return None
        st = plan.stats
        return {"total": plan.total_seconds, "typing": plan.typing_seconds, "breaks": plan.break_seconds,
                "effective_wpm": plan.effective_wpm, "chars": len(plan.text),
                "mistakes": st["typos"] + st["rough"] + st["omitted"] + st["rethinks"],
                "revision_passes": st["revision_passes"]}

    def start_or_resume(self, text):
        return self._app.start_or_resume(text)

    def pause(self):
        self._app.pause()

    def resume(self):
        self._app.resume()

    def stop(self):
        self._app.stop()

    # ---- windows
    def enter_mini(self):
        self._app.enter_mini()

    def leave_mini(self):
        self._app.leave_mini()

    def mini_resize(self, w, h, radius=20):
        self._app.mini_resize(w, h, radius)

    def quit(self):
        threading.Thread(target=self._app.quit, daemon=True).start()

    # ---- clipboard & system
    def clipboard_text(self):
        return _clipboard_get()

    def copy_text(self, text):
        return _clipboard_set(text)

    def open_url(self, url):
        if url.startswith(("https://ollama.com", "https://github.com/ollama")):
            os.startfile(url)

    def open_config_dir(self):
        os.startfile(str(config_dir()))

    # ---- humanizer
    def set_humanizer_setting(self, key, value):
        hs = self._app.settings.humanizer
        if key not in {f.name for f in fields(HumanizerSettings)}:
            return False
        setattr(hs, key, value)
        self._app.save_soon()
        return True

    def ollama_status(self):
        return self._ollama_dict(ollama.detect())

    @staticmethod
    def _ollama_dict(st):
        return {"running": st.running, "models": st.models, "default": st.default_model, "version": st.version}

    def humanize(self, text, opts):
        return self._app.humanize(text, opts)

    def cancel_humanize(self):
        self._app.cancel_humanize()

    def diff(self, a, b):
        return word_diff(a, b)

    # ---- install & updates
    def install_status(self):
        return installer.status()

    def install_app(self, desktop=True, start_menu=True):
        """Install, then hand over to the installed copy and close this one."""
        try:
            exe = installer.install(desktop=bool(desktop), start_menu=bool(start_menu))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if installer.running_installed():
            return {"ok": True, "relaunch": False, "status": installer.status()}
        def handoff():
            time.sleep(0.6)
            _release_single_instance()
            installer.launch(exe)
            self._app.quit()
        threading.Thread(target=handoff, daemon=True).start()
        return {"ok": True, "relaunch": True}

    def add_desktop_shortcut(self):
        try:
            installer.add_desktop_shortcut()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "status": installer.status()}

    def uninstall_app(self):
        if not installer.running_installed():
            return {"ok": False, "error": "This copy isn't the installed one."}
        installer.uninstall()
        threading.Thread(target=lambda: (time.sleep(0.4), self._app.quit()), daemon=True).start()
        return {"ok": True}

    def check_updates(self):
        try:
            info = updater.check()
        except updater.UpdateError as e:
            return {"ok": False, "error": str(e), "configured": bool(UPDATE_REPO), "current": VERSION}
        self._app.settings.ui.last_update_check = time.time()
        self._app.save_soon()
        return {"ok": True, **info}

    def install_update(self, info):
        target = installer.current_exe()
        if target is None:
            return {"ok": False, "error": "Running from source: update with the project files instead."}
        def work():
            try:
                new = updater.download(info, progress=lambda g, t: self._app.push(f"window.cadence.updProgress({g}, {t})"))
            except updater.UpdateError as e:
                self._app.push(f"window.cadence.updError({js(str(e))})")
                return
            self._app.push("window.cadence.updReady()")
            time.sleep(0.8)
            updater.apply(new, target)
            self._app.quit()
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    # ---- appearance
    def get_ui(self):
        ui = asdict(self._app.settings.ui)
        ui["scale"] = self._app.settings.ui.scale
        return ui

    def set_ui(self, key, value):
        ui = self._app.settings.ui
        if key == "size" and value in UI_SCALES:
            ui.size = value
            self._app.push(f"window.cadence.uiScale && window.cadence.uiScale({ui.scale})", mini=True)
        elif key in ("motion", "stats", "install_prompt", "auto_update"):
            setattr(ui, key, bool(value))
            if key == "motion":
                self._app.push(f"window.cadence.uiMotion && window.cadence.uiMotion({js(bool(value))})", mini=True)
        elif key == "start_page" and value in ("writer", "humanizer", "last"):
            ui.start_page = value
        elif key == "last_page" and value in ("writer", "humanizer", "style", "presets", "settings"):
            ui.last_page = value
        elif key == "collapsed" and isinstance(value, list):
            ui.collapsed = [str(v) for v in value][:20]
        else:
            return False
        self._app.save_soon()
        return self.get_ui()

    # ---- drafts & history
    def save_draft(self, key, text):
        return self._app.drafts.set(key, text)

    def list_history(self):
        return self._app.history.list()

    def get_history(self, hid):
        item = self._app.history.get(hid)
        return {"input": item["input"], "output": item["output"]} if item else None

    def delete_history(self, hid):
        self._app.history.delete(hid)
        return self._app.history.list()

    def clear_history(self):
        self._app.history.clear()
        return []

    # ---- files
    def open_file(self):
        try:
            paths = self._app.main.create_file_dialog(
                webview.FileDialog.OPEN, file_types=("Text and Word files (*.txt;*.md;*.docx)", "All files (*.*)"))
        except Exception as e:
            return {"ok": False, "error": f"Couldn't open the file picker: {e}"}
        if not paths:
            return {"ok": False, "cancelled": True}
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        try:
            return {"ok": True, "name": Path(path).name, "text": fileio.read_path(path)}
        except (OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}

    def read_dropped(self, name, b64):
        try:
            return {"ok": True, "name": name, "text": fileio.read_b64(name, b64)}
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            return {"ok": False, "error": "Couldn't read that file."}

    def save_text_file(self, text, suggested="humanized.txt"):
        try:
            path = self._app.main.create_file_dialog(webview.FileDialog.SAVE, save_filename=suggested,
                                                     file_types=("Text file (*.txt)",))
        except Exception as e:
            return {"ok": False, "error": f"Couldn't open the save dialog: {e}"}
        if not path:
            return {"ok": False, "cancelled": True}
        path = path[0] if isinstance(path, (list, tuple)) else path
        if not str(path).lower().endswith(".txt"):
            path = f"{path}.txt"
        try:
            fileio.write_text(path, text)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "name": Path(path).name}

    # ---- typing preview
    PREVIEW_CHARS = 2500
    _NOTE = {"type": "t", "typo": "y", "fix": "f", "nav": "n", "revise": "r", "rethink": "k", "rough": "g", "break": "b"}

    def preview_plan(self, text):
        """A plan for (the start of) the text, for the in-app typing preview.
        Uses words-per-minute pacing even in duration mode, and no breaks."""
        if not text or not text.strip():
            return None
        truncated = False
        if len(text) > self.PREVIEW_CHARS:
            cut = text.rfind("\n", 0, self.PREVIEW_CHARS)
            if cut < self.PREVIEW_CHARS * 0.5:
                cut = text.rfind(" ", 0, self.PREVIEW_CHARS)
            text = text[: cut if cut > 0 else self.PREVIEW_CHARS]
            truncated = True
        ws = replace(self._app.settings.writer, break_enabled=False, speed_mode="wpm")
        try:
            plan = build_plan(text, ws, seed=self._app.seed)
        except PlanError as e:
            return {"error": str(e)}
        acts = [[0 if a.kind == "char" else 1, a.value, round(a.delay * 1000), 1 if a.ctrl else 0,
                 self._NOTE.get(a.note, "t")] for a in plan.actions if a.kind != "break"]
        return {"actions": acts, "text": plan.text, "truncated": truncated, "seconds": plan.typing_seconds,
                "stats": plan.stats, "duration_mode": self._app.settings.writer.speed_mode == "duration"}

    # ---- writing-style templates
    def list_styles(self):
        return self._app.styles.list()

    def analyze_style(self, text):
        prof = style_mod.analyze(text or "")
        return {"summary": prof.summary(), "sentences": prof.sentences,
                "words": len((text or "").split()), "min_words": style_mod.StyleStore.MIN_WORDS}

    def save_style(self, name, text, sid=None):
        try:
            item = self._app.styles.save(name or "", text or "", sid or None)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "id": item.id, "styles": self._app.styles.list()}

    def delete_style(self, sid):
        self._app.styles.delete(sid)
        hs = self._app.settings.humanizer
        if hs.style_id == sid:
            hs.style_id = ""
            self._app.save_soon()
        return {"ok": True, "styles": self._app.styles.list()}




def _already_running() -> bool:
    """One Cadence at a time: two copies would both grab F8-F10. If one is open,
    bring it to the front instead."""
    if sys.platform != "win32" or os.environ.get("CADENCE_CONFIG_DIR"):   # tests use isolated copies
        return False
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.CreateMutexW.restype = ctypes.c_void_p
    _already_running.handle = k32.CreateMutexW(None, False, "Local\\CadenceFree.SingleInstance")
    if k32.GetLastError() != 183:          # ERROR_ALREADY_EXISTS
        return False
    hwnd = u32.FindWindowW(None, "Cadence")
    if hwnd:
        u32.ShowWindow(hwnd, 9)            # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
    return True


def _release_single_instance():
    h = getattr(_already_running, "handle", None)
    if h:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
        _already_running.handle = None


def main():
    if _already_running():
        return
    CadenceApp().run(debug=os.environ.get("CADENCE_DEBUG") == "1")


if __name__ == "__main__":
    main()
