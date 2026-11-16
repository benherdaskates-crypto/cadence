"""Make a new release of Cadence.

    python release.py 1.2.0                     # bump version, test, build
    python release.py 1.2.0 --repo you/cadence  # also set where updates come from
    python release.py 1.2.0 --skip-tests

Output goes to release/: the .exe to share and v<version>-notes.md, whose text
(including the sha256 line the updater checks) you paste into the GitHub release.
"""
from __future__ import annotations

import argparse
import hashlib
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", help="new version, e.g. 1.2.0")
    ap.add_argument("--repo", help='GitHub "owner/name" that holds the releases')
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
    built = ROOT / "dist" / "Cadence.exe"
    out_dir = ROOT / "release"
    out_dir.mkdir(exist_ok=True)
    exe = out_dir / f"Cadence-v{args.version}.exe"
    shutil.copy2(built, exe)
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    notes = out_dir / f"v{args.version}-notes.md"
    notes.write_text(f"## What's new\n\n- \n\nsha256: {digest}\n", encoding="utf-8")

    repo = version.UPDATE_REPO
    print(f"""
Done.
  File to share:   {exe}  ({exe.stat().st_size / 1e6:.1f} MB)
  Release notes:   {notes}
  sha256:          {digest}
""")
    if repo:
        print(f"""Publish the update:
  1. Open https://github.com/{repo}/releases/new
  2. Tag: v{args.version}   Title: Cadence {args.version}
  3. Paste the notes file's text (keep the sha256 line) and add what changed.
  4. Attach {exe.name} and click "Publish release".
Everyone's Cadence will offer the update within a day (or right away with "Check for updates").""")
    else:
        print('Updates are off: run again with --repo yourname/cadence once the GitHub repo exists.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
