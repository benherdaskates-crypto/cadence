"""Small JSON stores in the settings folder: auto-saved drafts and Humanizer history."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Drafts:
    """Text boxes that survive a restart. Writes are coalesced (at most ~1/s)."""
    KEYS = ("writer_text", "h_in", "h_out")
    MAX_CHARS = 2_000_000

    def __init__(self, path: Path):
        self.path = path
        data = _read_json(path, {})
        self.data = {k: v for k, v in data.items() if k in self.KEYS and isinstance(v, str)} if isinstance(data, dict) else {}
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def get(self) -> dict:
        return {k: self.data.get(k, "") for k in self.KEYS}

    def set(self, key: str, text: str) -> bool:
        if key not in self.KEYS or not isinstance(text, str) or len(text) > self.MAX_CHARS:
            return False
        with self._lock:
            self.data[key] = text
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(1.0, self.flush)
            self._timer.daemon = True
            self._timer.start()
        return True

    def flush(self) -> None:
        with self._lock:
            try:
                _write_json(self.path, self.data)
            except OSError:
                pass


class History:
    """Most recent Humanizer runs, newest first."""
    LIMIT = 30

    def __init__(self, path: Path):
        self.path = path
        data = _read_json(path, [])
        self.items: list[dict] = [d for d in data if isinstance(d, dict) and "id" in d] if isinstance(data, list) else []

    def add(self, input_text: str, output_text: str, engine: str, tone: str, strength: int, style: str = "") -> dict:
        if not input_text.strip() or not output_text.strip():
            return {}
        # Re-running the same input replaces its older entry instead of piling up.
        self.items = [i for i in self.items if i.get("input") != input_text]
        item = {"id": uuid.uuid4().hex[:10], "ts": time.time(), "engine": engine, "tone": tone,
                "strength": int(strength), "style": style, "input": input_text, "output": output_text}
        self.items.insert(0, item)
        del self.items[self.LIMIT:]
        self._save()
        return item

    def list(self) -> list[dict]:
        out = []
        for i in self.items:
            out.append({k: i.get(k) for k in ("id", "ts", "engine", "tone", "strength", "style")} |
                       {"preview": " ".join(i.get("output", "").split())[:140],
                        "words": len(i.get("output", "").split())})
        return out

    def get(self, hid: str) -> dict | None:
        return next((i for i in self.items if i.get("id") == hid), None)

    def delete(self, hid: str) -> None:
        self.items = [i for i in self.items if i.get("id") != hid]
        self._save()

    def clear(self) -> None:
        self.items = []
        self._save()

    def _save(self) -> None:
        try:
            _write_json(self.path, self.items)
        except OSError:
            pass
