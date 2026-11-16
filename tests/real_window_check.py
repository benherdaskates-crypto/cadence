"""Manual end-to-end check: types a plan full of typos and keyboard-navigated
revisions into a real Windows text control, then compares the result.

    python -m tests.real_window_check [textbox|richtextbox] [--seed N]

It opens a small WinForms window, takes focus for a few seconds, and closes it.
Don't touch the keyboard/mouse while it runs (focus lock pauses it if you do).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import WriterSettings  # noqa: E402
from engine.planner import build_plan, verify_plan  # noqa: E402
from engine import typer  # noqa: E402

TEXT = (
    "The quick brown fox jumps over the lazy dog. However, it's important to note\n"
    "that many people find this very difficult — especially at first. “Smart quotes”\n"
    "and accents like café and naïve must survive.\tTabs too!\n"
    "A second paragraph: numbers 3.14, e.g. abbreviations, and CAPITALS. Done? Yes 😀."
)

PS = r"""
param([string]$Kind, [string]$Out, [string]$Flag, [string]$HwndFile)
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$f.Text = "Cadence test target"; $f.Width = 900; $f.Height = 420; $f.TopMost = $true
$f.StartPosition = "CenterScreen"
if ($Kind -eq "richtextbox") { $t = New-Object System.Windows.Forms.RichTextBox }
else { $t = New-Object System.Windows.Forms.TextBox; $t.Multiline = $true; $t.AcceptsReturn = $true }
$t.AcceptsTab = $true; $t.Dock = "Fill"; $t.WordWrap = $true
$t.Font = New-Object System.Drawing.Font("Segoe UI", 11)
$f.Controls.Add($t)
$timer = New-Object System.Windows.Forms.Timer; $timer.Interval = 150
$timer.Add_Tick({ if (Test-Path $Flag) {
    [System.IO.File]::WriteAllText($Out, $t.Text, [System.Text.Encoding]::UTF8); $f.Close() } })
$f.Add_Shown({ $f.Activate(); $t.Focus();
    [System.IO.File]::WriteAllText($HwndFile, [string]$f.Handle) ; $timer.Start() })
[void]$f.ShowDialog()
"""


def run(kind: str, seed: int, word_jumps: bool = True) -> bool:
    tmp = Path(tempfile.mkdtemp(prefix="cadence_check_"))
    script, out, flag, hwnd_file = tmp / "t.ps1", tmp / "out.txt", tmp / "done.flag", tmp / "hwnd.txt"
    script.write_text(PS, encoding="utf-8")
    proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                             kind, str(out), str(flag), str(hwnd_file)])
    try:
        for _ in range(100):
            if hwnd_file.exists() and hwnd_file.read_text().strip():
                break
            time.sleep(0.1)
        hwnd = int(hwnd_file.read_text().strip())
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        if typer.foreground_window() != hwnd:
            print("Could not focus the test window; click it within 3 seconds...")
            time.sleep(3)

        s = WriterSettings(typo_rate=0.08, revise_enabled=True, revision_amount="Many",
                           revise_when="Mixed", rethink_enabled=True, word_jumps=word_jumps)
        plan = build_plan(TEXT, s, seed=seed)
        assert verify_plan(plan)
        for a in plan.actions:  # fast but not inhumanly so
            a.delay = 0.03 if a.kind == "key" and a.value in ("left", "right") and a.ctrl else 0.015
        ctrl_jumps = sum(1 for a in plan.actions if a.ctrl)
        sess = typer.TypingSession(plan, s)
        sess.start(countdown=0.3)
        while sess.alive:
            st = sess.status
            if st.state == "paused":
                print("Paused:", st.message)
                sess.stop()
            time.sleep(0.1)
        time.sleep(0.4)
        flag.write_text("1")
        proc.wait(10)
        got = out.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        ok = got == plan.text
        print(f"[{kind}] seed={seed} word_jumps={word_jumps} actions={len(plan.actions)} "
              f"ctrl_jumps={ctrl_jumps} stats={plan.stats} -> {'OK' if ok else 'MISMATCH'}")
        if not ok:
            import difflib
            for line in difflib.unified_diff(plan.text.splitlines(), got.splitlines(), lineterm=""):
                print("   ", line)
        return ok
    finally:
        if proc.poll() is None:
            flag.write_text("1")
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kinds", nargs="*", default=["textbox", "richtextbox"])
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    results = [run(k, args.seed) for k in args.kinds]
    sys.exit(0 if all(results) else 1)
