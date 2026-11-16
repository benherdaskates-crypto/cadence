"""Persistent settings stored as JSON under %APPDATA%\\CadenceFree."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("CADENCE_CONFIG_DIR") or os.path.join(os.environ.get("APPDATA") or str(Path.home()), "CadenceFree")
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class WriterSettings:
    # Speed
    speed_mode: str = "wpm"           # "wpm" | "duration"
    wpm: float = 55.0                 # 15-150
    target_minutes: float = 30.0
    speed_variance: float = 0.30
    # Mistakes
    typo_rate: float = 0.03           # 0-0.10, per letter
    # Revise later
    revise_enabled: bool = True
    revision_amount: str = "Some"     # Few | Some | Many
    revise_when: str = "Mixed"        # After paragraphs | At the end | Mixed
    rethink_enabled: bool = True
    # Pauses & rhythm
    punct_pause_scale: float = 1.0
    thinking_freq: float = 0.04
    burst_enabled: bool = True
    fatigue_enabled: bool = True
    # Sessions
    break_enabled: bool = False
    break_every_min: float = 10.0
    break_length_min: float = 2.0
    # Safety & convenience
    countdown: int = 5
    focus_lock: bool = True
    sounds: bool = False
    auto_mini: bool = True
    word_jumps: bool = True
    empty_doc: bool = False
    shift_enter: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "WriterSettings":
        names = {f.name: f.type for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


PRESET_FIELDS = (
    "wpm", "speed_variance", "typo_rate", "revise_enabled", "revision_amount",
    "revise_when", "rethink_enabled", "punct_pause_scale", "thinking_freq",
    "burst_enabled", "fatigue_enabled",
)


@dataclass
class HumanizerSettings:
    engine: str = "auto"              # auto | ollama | rules
    ollama_model: str = ""
    tone: str = "Neutral"
    strength: int = 1                 # 0 light, 1 moderate, 2 heavy
    reading_level: str = "High school"
    voice_sample: str = ""            # legacy; migrated into a saved style on first run
    style_id: str = ""                # saved writing-style template to follow ("" = none)
    show_changes: bool = False


UI_SCALES = {"Compact": 0.86, "Comfortable": 1.0, "Large": 1.12, "Extra large": 1.25}
ADVANCED_SECTIONS = ["Revise later", "Pauses & rhythm", "Sessions", "Safety & convenience"]


@dataclass
class UISettings:
    size: str = "Compact"             # key of UI_SCALES
    motion: bool = True               # animations on/off
    stats: bool = True                # stat pills at the top of pages
    start_page: str = "writer"        # writer | humanizer | last
    last_page: str = "writer"
    collapsed: list = field(default_factory=lambda: list(ADVANCED_SECTIONS))   # folded Writer sections
    window: list = field(default_factory=list)    # [width, height, x, y] in logical px
    install_prompt: bool = True       # offer to install when run from Downloads etc.
    auto_update: bool = True          # check GitHub for a newer version about once a day
    last_update_check: float = 0.0

    @property
    def scale(self) -> float:
        return UI_SCALES.get(self.size, UI_SCALES["Compact"])


@dataclass
class AppSettings:
    writer: WriterSettings = field(default_factory=WriterSettings)
    humanizer: HumanizerSettings = field(default_factory=HumanizerSettings)
    ui: UISettings = field(default_factory=UISettings)
    last_preset: str = "Natural"
    mini_pos: list = field(default_factory=list)   # [x, y] where the user last dragged the mini panel

    @classmethod
    def load(cls, path: Path | None = None) -> "AppSettings":
        path = path or config_dir() / "settings.json"
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        s = cls()
        s.writer = WriterSettings.from_dict(d.get("writer", {}))
        hn = {f.name for f in fields(HumanizerSettings)}
        s.humanizer = HumanizerSettings(**{k: v for k, v in d.get("humanizer", {}).items() if k in hn})
        s.last_preset = d.get("last_preset", s.last_preset)
        un = {f.name for f in fields(UISettings)}
        try:
            s.ui = UISettings(**{k: v for k, v in d.get("ui", {}).items() if k in un})
        except TypeError:
            s.ui = UISettings()
        mp = d.get("mini_pos")
        s.mini_pos = mp if isinstance(mp, list) and len(mp) == 2 else []
        return s

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "settings.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
