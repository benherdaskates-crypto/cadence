"""Tiny synthesized keyboard click sounds (no audio files shipped)."""
from __future__ import annotations

import math
import random
import struct
import sys
import tempfile
import wave
from pathlib import Path

_files: list[str] = []


def _make_click(path: Path, seed: int) -> None:
    rng = random.Random(seed)
    rate = 22050
    n = int(rate * 0.028)
    freq = rng.uniform(1700, 2600)
    frames = bytearray()
    for i in range(n):
        env = math.exp(-i / (rate * 0.004))
        noise = rng.uniform(-1, 1) * 0.6
        tone = math.sin(2 * math.pi * freq * i / rate) * 0.4
        v = int(max(-1, min(1, (noise + tone) * env)) * 9000)
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def _ensure() -> None:
    if _files:
        return
    d = Path(tempfile.gettempdir()) / "cadence_clicks"
    d.mkdir(exist_ok=True)
    for k in range(4):
        p = d / f"click{k}.wav"
        if not p.exists():
            _make_click(p, k)
        _files.append(str(p))


def click() -> None:
    if sys.platform != "win32":
        return
    import winsound
    try:
        _ensure()
        winsound.PlaySound(random.choice(_files),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass
