import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import installer
import updater

EXE_BYTES = b"MZ" + b"\x00" * 5000 + b"cadence"


class FakeGitHub(BaseHTTPRequestHandler):
    release = {}
    payload = EXE_BYTES

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/repos/"):
            if not self.release:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(self.release).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/dl/"):
            self.send_response(200); self.send_header("Content-Length", str(len(self.payload))); self.end_headers()
            self.wfile.write(self.payload)


@pytest.fixture
def gh(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setenv("CADENCE_UPDATE_API", base)
    FakeGitHub.payload = EXE_BYTES
    FakeGitHub.release = {
        "tag_name": "v9.1.0", "html_url": "https://github.com/me/cadence/releases/tag/v9.1.0",
        "body": f"## What's new\n- Faster\n\nsha256: {hashlib.sha256(EXE_BYTES).hexdigest()}",
        "assets": [{"name": "notes.txt", "browser_download_url": f"{base}/dl/notes.txt", "size": 3},
                   {"name": "Cadence-v9.1.0.exe", "browser_download_url": f"{base}/dl/app.exe", "size": len(EXE_BYTES)}],
    }
    yield base
    srv.shutdown()


def test_version_compare():
    assert updater.is_newer("v1.10.0", "1.9.9") and updater.is_newer("2.0", "1.99.99")
    assert not updater.is_newer("v1.1.0", "1.1.0") and not updater.is_newer("1.0.9", "1.1.0")


def test_unconfigured_repo_does_nothing():
    assert updater.check(repo="", current="1.0.0") == {"configured": False, "current": "1.0.0"}
    assert updater.check(repo="not a repo", current="1.0.0")["configured"] is False


def test_check_finds_newer_release(gh):
    info = updater.check(repo="me/cadence", current="1.1.0")
    assert info["available"] and info["latest"] == "9.1.0"
    assert info["url"].endswith("/dl/app.exe") and info["size"] == len(EXE_BYTES)
    assert info["sha256"] == hashlib.sha256(EXE_BYTES).hexdigest()
    assert "Faster" in info["notes"] and "sha256" not in info["notes"]
    assert not updater.check(repo="me/cadence", current="9.1.0")["available"]


def test_no_releases_yet(gh):
    FakeGitHub.release = {}
    with pytest.raises(updater.UpdateError, match="No releases"):
        updater.check(repo="me/cadence", current="1.0.0")


def test_download_verifies(gh):
    info = updater.check(repo="me/cadence", current="1.0.0")
    path = updater.download(info, repo="me/cadence")
    assert path.read_bytes() == EXE_BYTES

    bad = dict(info, sha256="0" * 64)
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(bad, repo="me/cadence")

    FakeGitHub.payload = b"<html>not an exe</html>"
    with pytest.raises(updater.UpdateError):
        updater.download(dict(info, sha256="", size=0), repo="me/cadence")


def test_download_refuses_foreign_links(monkeypatch):
    monkeypatch.delenv("CADENCE_UPDATE_API", raising=False)
    with pytest.raises(updater.UpdateError, match="doesn't point"):
        updater.download({"url": "https://evil.example.com/Cadence.exe"}, repo="me/cadence")
    with pytest.raises(updater.UpdateError, match="doesn't point"):
        updater.download({"url": "https://github.com/someone-else/x/releases/download/v1/a.exe"}, repo="me/cadence")


def test_scripts_mention_the_right_things(tmp_path):
    s = updater.swap_script(1234, tmp_path / "new.exe", tmp_path / "Cadence.exe")
    assert 'PID eq 1234' in s and str(tmp_path / "new.exe") in s and 'start ""' in s and "chcp 65001" in s
    u = installer.uninstall_script(4321)
    assert "PID eq 4321" in u and "rmdir /s /q" in u


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_swap_script_really_waits_replaces_and_starts(tmp_path):
    """Run the real updater script against a dummy 'Cadence' process and dummy exes."""
    target = tmp_path / "target.exe"
    new = tmp_path / "new.exe"
    marker = tmp_path / "started.txt"
    # The "new version" is a copy of a harmless system tool; starting it just runs and exits.
    shutil.copy(os.path.join(os.environ["SystemRoot"], "System32", "hostname.exe"), new)
    target.write_bytes(b"MZ old version")
    dummy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    script = tmp_path / "swap.cmd"
    body = updater.swap_script(dummy.pid, new, target).replace('start "" ', f'echo started> "{marker}" & start "" /b ')
    script.write_text(body, encoding="utf-8")
    proc = subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000)
    time.sleep(0.8)
    assert target.read_bytes() == b"MZ old version"            # still waiting for "Cadence" to exit
    dummy.wait(10)
    proc.wait(20)
    assert target.read_bytes()[:2] == b"MZ" and target.read_bytes() != b"MZ old version"
    assert not new.exists() and marker.exists() and not script.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_install_copies_exe_and_makes_shortcuts(tmp_path, monkeypatch):
    monkeypatch.setenv("CADENCE_INSTALL_DIR", str(tmp_path / "Programs" / "Cadence"))
    monkeypatch.setenv("CADENCE_DESKTOP_DIR", str(tmp_path / "Desktop"))
    monkeypatch.setenv("CADENCE_PROGRAMS_DIR", str(tmp_path / "StartMenu"))
    src = tmp_path / "Downloads" / "Cadence.exe"
    src.parent.mkdir()
    shutil.copy(os.path.join(os.environ["SystemRoot"], "System32", "hostname.exe"), src)   # a real, valid exe
    exe = installer.install(source=src)
    assert exe.read_bytes() == src.read_bytes() and exe.parent == tmp_path / "Programs" / "Cadence"
    assert (tmp_path / "Desktop" / "Cadence.lnk").exists()
    assert (tmp_path / "StartMenu" / "Cadence.lnk").exists()
    st = installer.status()
    assert st["installed"] and st["desktop_shortcut"] and st["start_menu_shortcut"] and not st["frozen"]
    with pytest.raises(RuntimeError, match="source"):
        installer.install()                                     # not frozen: refuses


def test_release_script_sets_version(tmp_path, monkeypatch):
    import release
    (tmp_path / "version.py").write_text('VERSION = "1.0.0"\nUPDATE_REPO = ""\n', encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    release.set_version("1.4.2", "me/cadence-free")
    text = (tmp_path / "version.py").read_text(encoding="utf-8")
    assert 'VERSION = "1.4.2"' in text and 'UPDATE_REPO = "me/cadence-free"' in text
    release.set_version("1.4.3", None)
    assert 'UPDATE_REPO = "me/cadence-free"' in (tmp_path / "version.py").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_install_removes_old_cadence_free_install(tmp_path, monkeypatch):
    monkeypatch.setenv("CADENCE_INSTALL_DIR", str(tmp_path / "Programs" / "Cadence"))
    monkeypatch.setenv("CADENCE_DESKTOP_DIR", str(tmp_path / "Desktop"))
    monkeypatch.setenv("CADENCE_PROGRAMS_DIR", str(tmp_path / "StartMenu"))
    old_dir = tmp_path / "Programs" / "Cadence Free"
    old_dir.mkdir(parents=True)
    (old_dir / "Cadence Free.exe").write_bytes(b"MZ old")
    for d in ("Desktop", "StartMenu"):
        (tmp_path / d).mkdir(exist_ok=True)
        (tmp_path / d / "Cadence Free.lnk").write_bytes(b"old shortcut")
    src = tmp_path / "Cadence.exe"
    shutil.copy(os.path.join(os.environ["SystemRoot"], "System32", "hostname.exe"), src)
    installer.install(source=src)
    assert not old_dir.exists()
    assert not (tmp_path / "Desktop" / "Cadence Free.lnk").exists()
    assert not (tmp_path / "StartMenu" / "Cadence Free.lnk").exists()
    assert (tmp_path / "Desktop" / "Cadence.lnk").exists()
