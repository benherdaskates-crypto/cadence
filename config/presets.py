"""Built-in and user presets for the Writer. Custom presets live in
%APPDATA%\\Cadence\\presets.json."""
from __future__ import annotations

import json
import os

from .settings import PRESET_FIELDS, WriterSettings, config_dir

BUILTIN: dict[str, dict] = {
    "Natural": dict(wpm=55, speed_variance=0.30, typo_rate=0.03, revise_enabled=True,
                    revision_amount="Some", revise_when="Mixed", rethink_enabled=True,
                    punct_pause_scale=1.0, thinking_freq=0.04, burst_enabled=True, fatigue_enabled=True),
    "Fast & Clean": dict(wpm=95, speed_variance=0.15, typo_rate=0.005, revise_enabled=False,
                         revision_amount="Few", revise_when="After paragraphs", rethink_enabled=False,
                         punct_pause_scale=0.5, thinking_freq=0.01, burst_enabled=True, fatigue_enabled=False),
    "Casual": dict(wpm=70, speed_variance=0.35, typo_rate=0.05, revise_enabled=True,
                   revision_amount="Few", revise_when="After paragraphs", rethink_enabled=True,
                   punct_pause_scale=0.8, thinking_freq=0.03, burst_enabled=True, fatigue_enabled=False),
    "Slow & Careful": dict(wpm=32, speed_variance=0.25, typo_rate=0.015, revise_enabled=True,
                           revision_amount="Many", revise_when="At the end", rethink_enabled=True,
                           punct_pause_scale=1.6, thinking_freq=0.08, burst_enabled=True, fatigue_enabled=True),
}


def _path():
    return config_dir() / "presets.json"


def load_custom() -> dict[str, dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def save_custom(presets: dict[str, dict]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(presets, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def all_names() -> list[str]:
    return list(BUILTIN) + sorted(n for n in load_custom() if n not in BUILTIN)


def get(name: str) -> dict | None:
    if name in BUILTIN:
        return BUILTIN[name]
    return load_custom().get(name)


def apply(settings: WriterSettings, values: dict) -> None:
    for k in PRESET_FIELDS:
        if k in values:
            setattr(settings, k, values[k])


def snapshot(settings: WriterSettings) -> dict:
    return {k: getattr(settings, k) for k in PRESET_FIELDS}


def save_as(name: str, settings: WriterSettings) -> None:
    if name in BUILTIN:
        raise ValueError("That name belongs to a built-in preset.")
    data = load_custom()
    data[name] = snapshot(settings)
    save_custom(data)


def delete(name: str) -> None:
    if name in BUILTIN:
        raise ValueError("Built-in presets can't be deleted.")
    data = load_custom()
    data.pop(name, None)
    save_custom(data)
