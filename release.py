"""Make a new release of Cadence.

    python release.py 1.2.0 --notes "What changed" --publish

1. bumps version.py (and UPDATE_REPO with --repo yourname/cadence)
2. runs the tests and builds dist/Cadence.exe
3. puts the app at the top of the repo as Cadence.exe, next to latest.json
   (version, size, sha256, notes). That's what people download, and what
   every installed Cadence checks for updates.
4. with --publish: commits those two files and pushes to GitHub.

Without --publish, commit and push them yourself when you're ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def set_version(ver: str, repo: str | None) -> None:
    p = ROOT / "version.py"
    s = p.read_text(encoding="utf-8")
    s = re.sub(r'VERSION = "[^"]*"', f'VERSION = "{ver}"', s)
    if repo is not None:
        s = re.sub(r'UPDATE_REPO = "[^"]*"', f'UPDATE_REPO = "{repo}"', s)
    p.write_text(s, encoding="utf-8")


def write_latest(exe: Path, ver: str, notes: str) -> dict:
    data = exe.read_bytes()
    info = {"version": ver, "file": exe.name, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "notes": notes.strip()}
    (exe.parent / "latest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def git(*args: str) -> int:
    return subprocess.run(["git", *args], cwd=ROOT).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="new version, e.g. 1.2.0")
    ap.add_argument("--repo", help='GitHub "owner/name" people download from and check for updates')
    ap.add_argument("--notes", default="", help="what changed (shown in the update prompt)")
    ap.add_argument("--publish", action="store_true", help="commit Cadence.exe + latest.json and push")
    ap.add_argument("--skip-tests", action="store_true")
    args = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        sys.exit("Version must look like 1.2.0")
    if args.repo is not None and args.repo and not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", args.repo):
        sys.exit('Repo must look like "yourname/cadence"')

    set_version(args.version, args.repo)
    sys.path.insert(0, str(ROOT))
    import version  # noqa: E402  (fresh values)

    if not args.skip_tests:
        print("Running tests...")
        if subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT).returncode:
            sys.exit("Tests failed; nothing was built.")

    print("Building...")
    if subprocess.run(["cmd", "/c", str(ROOT / "build.bat")], cwd=ROOT).returncode:
        sys.exit("Build failed.")
    exe = ROOT / "Cadence.exe"
    shutil.copy2(ROOT / "dist" / "Cadence.exe", exe)
    info = write_latest(exe, args.version, args.notes)
    print(f"\nBuilt Cadence {args.version}: {exe} ({info['size'] / 1e6:.1f} MB)\nsha256 {info['sha256']}")

    repo = version.UPDATE_REPO
    if not args.publish:
        print("\nNext: commit Cadence.exe, latest.json and version.py, then push (or rerun with --publish).")
        return 0
    if git("add", "Cadence.exe", "latest.json", "version.py") or \
       git("commit", "-m", f"Release Cadence {args.version}", "-m", args.notes or "New build.") or \
       git("push"):
        sys.exit("Couldn't commit/push; the files are built, so you can do it by hand.")
    if repo:
        print(f"\nPublished. Download link: https://github.com/{repo}/raw/main/Cadence.exe\n"
              "Everyone's Cadence will offer the update within a day (or right away with Settings > Check now).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
