import base64
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import fileio
from config.settings import WriterSettings
from config.store import Drafts, History
from engine.actions import Action, VirtualEditor
from engine.planner import build_plan
from tests.test_engine import SAMPLE

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- drafts & history

def test_drafts_persist_and_reject_unknown_keys(tmp_path):
    d = Drafts(tmp_path / "drafts.json")
    assert d.set("writer_text", "hello") and d.set("h_out", "x")
    assert not d.set("evil", "nope")
    d.flush()
    again = Drafts(tmp_path / "drafts.json").get()
    assert again == {"writer_text": "hello", "h_in": "", "h_out": "x"}


def test_history_add_dedupe_limit_delete(tmp_path):
    h = History(tmp_path / "h.json")
    for i in range(35):
        h.add(f"in {i}", f"out {i}", "rules", "Neutral", 1)
    assert len(h.list()) == History.LIMIT and h.list()[0]["preview"] == "out 34"
    h.add("in 34", "out again", "rules", "Casual", 2)              # same input -> replaces
    lst = History(tmp_path / "h.json").list()
    assert len(lst) == History.LIMIT and lst[0]["preview"] == "out again"
    assert sum(1 for i in lst if i["preview"].startswith("out 34")) == 0
    first = lst[0]["id"]
    assert h.get(first)["input"] == "in 34"
    h.delete(first)
    assert h.get(first) is None
    assert h.add("", "x", "rules", "Neutral", 1) == {}
    h.clear()
    assert History(tmp_path / "h.json").list() == []


# ---------------------------------------------------------------- files

def _docx(paragraphs):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r>'
        + ('<w:r><w:tab/><w:t>tabbed</w:t></w:r>' if "TAB" in p else "")
        + "</w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_paragraphs_and_tabs():
    text = fileio.read_any("essay.docx", _docx(["First paragraph.", "Second with TAB", "Café “quotes” — ok"]))
    assert text == "First paragraph.\nSecond with TAB\ttabbed\nCafé “quotes” — ok"


def test_txt_encodings():
    assert fileio.read_any("a.txt", "héllo\r\nworld".encode("utf-8")) == "héllo\nworld"
    assert fileio.read_any("a.txt", "﻿bom".encode("utf-8")) == "bom"
    assert fileio.read_any("a.txt", "café".encode("cp1252")) == "café"
    assert fileio.read_any("a.md", "x".encode("utf-16")) == "x"


def test_bad_files():
    with pytest.raises(ValueError, match="can open"):
        fileio.read_any("pic.png", b"\x89PNG")
    with pytest.raises(ValueError, match="Word file"):
        fileio.read_any("broken.docx", b"not a zip")


def test_b64_and_write_roundtrip(tmp_path):
    data = _docx(["Hello there."])
    assert fileio.read_b64("x.docx", base64.b64encode(data).decode()) == "Hello there."
    f = tmp_path / "out.txt"
    fileio.write_text(str(f), "a\nb")
    assert f.read_bytes() == b"a\r\nb" and fileio.read_path(str(f)) == "a\nb"


# ---------------------------------------------------------------- typing preview

class _FakeApp:
    def __init__(self, ws):
        from config.settings import AppSettings
        self.settings = AppSettings()
        self.settings.writer = ws
        self.seed = 7


def _api(ws=None):
    import app
    a = app.Api.__new__(app.Api)
    a._app = _FakeApp(ws or WriterSettings(typo_rate=0.08, revision_amount="Many"))
    return a


def _replay_py(actions):
    ed = VirtualEditor()
    for kind, v, _d, ctrl, _n in actions:
        ed.apply(Action("char" if kind == 0 else "key", v, ctrl=bool(ctrl)))
    return ed.text


def test_preview_plan_replays_to_the_text():
    res = _api().preview_plan(SAMPLE)
    assert not res["truncated"] and _replay_py(res["actions"]) == res["text"]
    notes = {a[4] for a in res["actions"]}
    assert {"t", "y", "f"} <= notes


def test_preview_truncates_long_text_at_a_boundary():
    long = (SAMPLE + "\n") * 20
    res = _api().preview_plan(long)
    assert res["truncated"] and len(res["text"]) <= 2500 and long.startswith(res["text"])
    assert _replay_py(res["actions"]) == res["text"]


def test_preview_in_duration_mode_and_empty():
    res = _api(WriterSettings(speed_mode="duration", target_minutes=600, break_enabled=True)).preview_plan(SAMPLE)
    assert res["duration_mode"] and res["seconds"] < 600          # paced by wpm, not stretched
    assert _api().preview_plan("   ") is None


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_js_preview_editor_matches_python(seed, tmp_path):
    plan = build_plan(SAMPLE * 2, WriterSettings(typo_rate=0.1, revision_amount="Many", empty_doc=seed == 3), seed=seed)
    acts = [[0 if a.kind == "char" else 1, a.value, 0, 1 if a.ctrl else 0, ""] for a in plan.actions if a.kind != "break"]
    (tmp_path / "acts.json").write_text(json.dumps(acts), encoding="utf-8")
    script = f"""
const m = require({json.dumps(str(ROOT / 'web' / 'js' / 'preview-model.js'))});
const acts = JSON.parse(require('fs').readFileSync({json.dumps(str(tmp_path / 'acts.json'))}, 'utf8'));
const ed = new m.PreviewEditor(); for (const a of acts) ed.apply(a);
process.stdout.write(JSON.stringify({{text: ed.text, cursor: ed.cursor}}));"""
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert out["text"] == plan.text and out["cursor"] == len(plan.text)


# ---------------------------------------------------------------- appearance settings

def test_ui_settings_roundtrip_and_validation(tmp_path):
    from config.settings import UI_SCALES, AppSettings
    s = AppSettings()
    assert s.ui.size == "Compact" and s.ui.scale == UI_SCALES["Compact"] < 1      # smaller by default
    assert set(s.ui.collapsed) >= {"Revise later", "Sessions"}                      # advanced sections folded
    s.ui.size, s.ui.motion, s.ui.window = "Large", False, [1000, 700, 10, 20]
    s.save(tmp_path / "s.json")
    t = AppSettings.load(tmp_path / "s.json")
    assert t.ui.size == "Large" and t.ui.scale == UI_SCALES["Large"] and t.ui.motion is False and t.ui.window == [1000, 700, 10, 20]


def test_set_ui_api_validates():
    import app
    from config.settings import AppSettings

    class FakeApp:
        settings = AppSettings()
        pushed = []
        def push(self, script, mini=False): self.pushed.append(script)
        def save_soon(self): pass
    a = app.Api.__new__(app.Api)
    a._app = FakeApp()
    assert a.set_ui("size", "Extra large")["scale"] > 1.2
    assert "uiScale" in a._app.pushed[-1]
    assert a.set_ui("size", "Gigantic") is False
    assert a.set_ui("start_page", "humanizer")["start_page"] == "humanizer"
    assert a.set_ui("start_page", "nowhere") is False
    assert a.set_ui("collapsed", ["Sessions"])["collapsed"] == ["Sessions"]
    assert a.set_ui("nonsense", 1) is False
