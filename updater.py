"""Updates from GitHub Releases.

check()    asks GitHub for the latest release of version.UPDATE_REPO
download() fetches its .exe asset and verifies it (Windows exe header, size,
           and SHA-256 when the release notes contain "sha256: <hash>")
apply()    once Cadence exits, swaps the new exe in and starts it again
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import version

API = "https://api.github.com"
USER_AGENT = "CadenceFree-updater"          # generic: nothing about the user is sent
CREATE_NO_WINDOW = 0x08000000


class UpdateError(Exception):
    pass


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def _api_base() -> str:
    return os.environ.get("CADENCE_UPDATE_API", API).rstrip("/")


# ---------------------------------------------------------------------------
# Transport. The shared .exe leaves out OpenSSL to stay small (a placeholder
# `ssl` module satisfies pywebview's import), so HTTPS there goes through
# Windows' own .NET stack, which is already bundled for the app window.
# ---------------------------------------------------------------------------
class _HttpError(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _tls_available() -> bool:
    if os.environ.get("CADENCE_FORCE_NET_HTTP"):          # lets tests exercise the .NET path
        return False
    try:
        import ssl
    except ImportError:
        return False
    return not getattr(ssl, "CADENCE_STUB", False)


def _open(url: str, headers: dict, timeout: float):
    """Returns (content_length, read(n) -> bytes, close())."""
    if url.lower().startswith("https://") and not _tls_available():
        return _net_open(url, headers, timeout)
    req = urllib.request.Request(url, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise _HttpError(e.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise _HttpError(0)
    return int(r.headers.get("Content-Length") or 0), r.read, r.close


def _net_open(url: str, headers: dict, timeout: float):
    try:
        import clr  # noqa: F401  (pythonnet)
        from System import Array, Byte
        from System.Net import SecurityProtocolType, ServicePointManager, WebException, WebRequest
    except Exception:
        raise UpdateError("Secure downloads aren't available on this PC.")
    proto = ServicePointManager.SecurityProtocol | SecurityProtocolType.Tls12
    if hasattr(SecurityProtocolType, "Tls13"):
        proto = proto | SecurityProtocolType.Tls13
    ServicePointManager.SecurityProtocol = proto
    req = WebRequest.Create(url)
    req.Timeout = req.ReadWriteTimeout = int(timeout * 1000)
    req.UserAgent = headers.get("User-Agent", USER_AGENT)
    if "Accept" in headers:
        req.Accept = headers["Accept"]
    try:
        resp = req.GetResponse()
    except WebException as e:
        r = e.Response
        raise _HttpError(int(r.StatusCode) if r is not None else 0)
    except Exception:
        raise _HttpError(0)
    stream = resp.GetResponseStream()
    buf = Array.CreateInstance(Byte, 256 * 1024)

    def read(n: int = 256 * 1024) -> bytes:
        k = stream.Read(buf, 0, min(n, buf.Length))
        return bytes(buf)[:k] if k > 0 else b""
    length = int(resp.ContentLength) if resp.ContentLength >= 0 else 0
    return length, read, resp.Close


def _get_json(url: str, timeout: float = 10) -> dict:
    try:
        _len, read, close = _open(url, {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}, timeout)
    except _HttpError as e:
        if e.code == 404:
            raise UpdateError("No releases found yet for this app.")
        if e.code == 403:
            raise UpdateError("GitHub is rate-limiting update checks. Try again in a while.")
        if e.code == 0:
            raise UpdateError("Couldn't reach GitHub. Check your internet connection.")
        raise UpdateError(f"Update check failed ({e.code}).")
    try:
        chunks = []
        while True:
            c = read(256 * 1024)
            if not c:
                break
            chunks.append(c)
        return json.loads(b"".join(chunks).decode("utf-8"))
    except ValueError:
        raise UpdateError("Got an unreadable answer from GitHub.")
    except (OSError, TimeoutError):
        raise UpdateError("Couldn't reach GitHub. Check your internet connection.")
    finally:
        close()


def check(repo: str | None = None, current: str | None = None) -> dict:
    repo = (repo if repo is not None else version.UPDATE_REPO).strip()
    current = current or version.VERSION
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo or ""):
        return {"configured": False, "current": current}
    rel = _get_json(f"{_api_base()}/repos/{repo}/releases/latest")
    tag = rel.get("tag_name") or rel.get("name") or ""
    exe = next((a for a in rel.get("assets", []) if str(a.get("name", "")).lower().endswith(".exe")), None)
    notes = (rel.get("body") or "").strip()
    m = re.search(r"sha-?256[^0-9a-fA-F]{0,12}([0-9a-fA-F]{64})", notes)
    return {"configured": True, "current": current, "latest": tag.lstrip("vV"), "available": bool(exe) and is_newer(tag, current),
            "notes": re.sub(r"(?im)^.*sha-?256.*$", "", notes).strip()[:1500], "page": rel.get("html_url", ""),
            "url": exe.get("browser_download_url") if exe else "", "size": int(exe.get("size", 0)) if exe else 0,
            "sha256": m.group(1).lower() if m else ""}


def _allowed_download(url: str, repo: str) -> bool:
    if os.environ.get("CADENCE_UPDATE_API"):              # tests use a local fake server
        return url.startswith(os.environ["CADENCE_UPDATE_API"])
    return url.lower().startswith(f"https://github.com/{repo.lower()}/releases/download/")


def download(info: dict, repo: str | None = None, progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> Path:
    repo = (repo if repo is not None else version.UPDATE_REPO).strip()
    url = info.get("url", "")
    if not url or not _allowed_download(url, repo):
        raise UpdateError("The update link doesn't point at this app's GitHub releases; not downloading it.")
    dest = Path(tempfile.mkdtemp(prefix="cadence_update_")) / "Cadence.exe"
    h, got, total = hashlib.sha256(), 0, int(info.get("size") or 0)
    try:
        length, read, close = _open(url, {"User-Agent": USER_AGENT}, 30)
    except _HttpError as e:
        raise UpdateError("Download failed: couldn't reach GitHub." if e.code == 0 else f"Download failed ({e.code}).")
    try:
        with open(dest, "wb") as f:
            total = total or length
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Cancelled.")
                chunk = read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if total and got > total * 1.01 + 1024:
                    raise UpdateError("The download is bigger than expected; stopped.")
                if progress:
                    progress(got, total)
    except (TimeoutError, OSError) as e:
        raise UpdateError(f"Download failed: {e}")
    finally:
        close()
    if total and got != total:
        raise UpdateError("The download was incomplete. Try again.")
    with open(dest, "rb") as f:
        if f.read(2) != b"MZ":
            raise UpdateError("The downloaded file isn't a Windows program; not installing it.")
    if info.get("sha256") and h.hexdigest() != info["sha256"]:
        raise UpdateError("The download doesn't match the checksum in the release notes; not installing it.")
    return dest


def swap_script(pid: int, new_exe: Path, target: Path) -> str:
    """Wait for Cadence (pid) to exit, replace the exe, start the new one, delete itself."""
    return (f'@echo off\r\nchcp 65001 >nul\r\n{wait_for_exit(pid)}'
            f'set tries=0\r\n:move\r\nmove /Y "{new_exe}" "{target}" >nul 2>&1 || '
            f'(set /a tries+=1 & {SLEEP1} & if %tries% LSS 15 goto move)\r\n'
            f'start "" "{target}"\r\n(goto) 2>nul & del "%~f0"\r\n')


# Windows tools by full path: on PCs with Git's Unix tools on PATH, a bare "find"
# would run the Unix find, the wait would silently be skipped and the exe replaced
# while Cadence is still running.
SLEEP1 = r'"%SystemRoot%\System32\timeout.exe" /t 1 /nobreak >nul'


def wait_for_exit(pid: int) -> str:
    return (f':wait\r\n"%SystemRoot%\\System32\\tasklist.exe" /FI "PID eq {pid}" /NH 2>nul | '
            f'"%SystemRoot%\\System32\\find.exe" "{pid}" >nul && ({SLEEP1} & goto wait)\r\n')


def apply(new_exe: Path, target: Path) -> None:
    script = new_exe.parent / "apply_update.cmd"
    script.write_text(swap_script(os.getpid(), new_exe, target), encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=CREATE_NO_WINDOW, close_fds=True)
