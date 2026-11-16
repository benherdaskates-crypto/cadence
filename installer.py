"""Self-install for the single-file exe: copy to %LOCALAPPDATA%\\Programs, add
Start menu / desktop shortcuts, and uninstall. Per-user only: no admin rights,
no registry changes. Settings in %APPDATA%\\CadenceFree are left alone."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Cadence"
EXE_NAME = "Cadence.exe"
LEGACY_NAMES = ("Cadence Free",)       # earlier product name
CREATE_NO_WINDOW = 0x08000000


def _programs_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs"


def install_dir() -> Path:
    override = os.environ.get("CADENCE_INSTALL_DIR")
    if override:
        return Path(override)
    return _programs_root() / APP_NAME


def legacy_dirs() -> list[Path]:
    base = Path(os.environ["CADENCE_INSTALL_DIR"]).parent if os.environ.get("CADENCE_INSTALL_DIR") else _programs_root()
    return [base / n for n in LEGACY_NAMES]


def remove_legacy() -> None:
    """Remove shortcuts and the install folder of the old 'Cadence Free' name."""
    for name in LEGACY_NAMES:
        for folder in ("Desktop", "Programs"):
            d = _known_folder(folder)
            lnk = d / f"{name}.lnk" if d else None
            if lnk and lnk.exists():
                try:
                    lnk.unlink()
                except OSError:
                    pass
    me = current_exe()
    for d in legacy_dirs():
        if not d.exists():
            continue
        if me and me.parent == d.resolve():
            _remove_after_exit(d)           # we're running from it: delete once we've closed
        else:
            shutil.rmtree(d, ignore_errors=True)


def _remove_after_exit(d: Path) -> None:
    from updater import wait_for_exit
    script = Path(os.environ.get("TEMP", str(d.parent))) / "cadence_cleanup.cmd"
    script.write_text(f'@echo off\r\nchcp 65001 >nul\r\n{wait_for_exit(os.getpid())}rmdir /s /q "{d}"\r\n'
                      f'(goto) 2>nul & del "%~f0"\r\n', encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=CREATE_NO_WINDOW, close_fds=True)


def current_exe() -> Path | None:
    """The running exe, or None when running from source."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def installed_exe() -> Path:
    return install_dir() / EXE_NAME


def running_installed() -> bool:
    exe = current_exe()
    return bool(exe) and exe.parent == install_dir().resolve()


def _known_folder(name: str) -> Path | None:
    """Desktop / Programs (Start menu) folder via PowerShell; honours OneDrive redirection."""
    override = os.environ.get(f"CADENCE_{name.upper()}_DIR")
    if override:
        return Path(override)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"],
                             capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        p = out.stdout.strip()
        return Path(p) if p else None
    except (OSError, subprocess.SubprocessError):
        return None


def shortcut_paths() -> dict[str, Path | None]:
    desk, progs = _known_folder("Desktop"), _known_folder("Programs")
    return {"desktop": desk / f"{APP_NAME}.lnk" if desk else None,
            "start_menu": progs / f"{APP_NAME}.lnk" if progs else None}


def make_shortcut(lnk: Path, target: Path) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CAD_LNK); "
          "$s.TargetPath = $env:CAD_TARGET; $s.WorkingDirectory = $env:CAD_DIR; "
          "$s.IconLocation = $env:CAD_TARGET + ',0'; $s.Description = 'Cadence'; $s.Save()")
    env = dict(os.environ, CAD_LNK=str(lnk), CAD_TARGET=str(target), CAD_DIR=str(target.parent))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, timeout=30,
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not lnk.exists():
        # Windows refuses to save if it can't read the icon; try again with the default icon.
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps.replace("$s.IconLocation = $env:CAD_TARGET + ',0'; ", "")],
                           env=env, timeout=30, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not lnk.exists():
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError("Couldn't create the shortcut" + (f": {detail[0]}" if detail else "."))


def status() -> dict:
    sc = shortcut_paths()
    return {"frozen": current_exe() is not None, "installed": installed_exe().exists(),
            "running_installed": running_installed(), "install_dir": str(install_dir()),
            "running_from": str(current_exe() or ""),
            "desktop_shortcut": bool(sc["desktop"] and sc["desktop"].exists()),
            "start_menu_shortcut": bool(sc["start_menu"] and sc["start_menu"].exists())}


def install(source: Path | None = None, desktop: bool = True, start_menu: bool = True) -> Path:
    """Copy the exe into the install folder and create shortcuts. Returns the installed exe."""
    source = source or current_exe()
    if source is None:
        raise RuntimeError("Installing works from the .exe, not when running from source.")
    target = installed_exe()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        tmp = target.with_suffix(".new")
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
    sc = shortcut_paths()
    remove_legacy()
    if start_menu and sc["start_menu"]:
        make_shortcut(sc["start_menu"], target)
    if desktop and sc["desktop"]:
        make_shortcut(sc["desktop"], target)
    return target


def add_desktop_shortcut() -> Path:
    target = installed_exe() if installed_exe().exists() else current_exe()
    if target is None:
        raise RuntimeError("Shortcuts work from the .exe, not when running from source.")
    lnk = shortcut_paths()["desktop"]
    if lnk is None:
        raise RuntimeError("Couldn't find the Desktop folder.")
    make_shortcut(lnk, target)
    return lnk


def uninstall_script(pid: int) -> str:
    """A small batch file that waits for Cadence to close, then removes the install folder."""
    from updater import wait_for_exit
    d = install_dir()
    return (f'@echo off\r\nchcp 65001 >nul\r\n{wait_for_exit(pid)}'
            f'rmdir /s /q "{d}"\r\n(goto) 2>nul & del "%~f0"\r\n')


def uninstall() -> None:
    """Remove shortcuts now; the install folder is removed right after Cadence exits."""
    for lnk in shortcut_paths().values():
        if lnk and lnk.exists():
            try:
                lnk.unlink()
            except OSError:
                pass
    if install_dir().exists():
        script = Path(os.environ.get("TEMP", str(install_dir().parent))) / "cadence_uninstall.cmd"
        script.write_text(uninstall_script(os.getpid()), encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=CREATE_NO_WINDOW, close_fds=True)


def launch(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True,
                     creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
