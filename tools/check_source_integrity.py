"""Check Python sources for accidentally pasted patch or revision text.

This catches lines such as ``@@ -99,117 +100,120 @@`` and bare
revision/hash fragments such as ``dc9ceaaf753ae1809d0f715fae5b.`` that can be
introduced when PR text, a patch, or a commit identifier is copied into a .py
file instead of applying the patch with git. Such artifacts make Python fail
immediately with SyntaxError.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv"}
MARKERS = ("@@ ", "diff --git ", "<<<<<<< ", "=======", ">>>>>>> ")
BARE_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,64}\.?$")


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def find_source_artifacts(root: Path):
    findings = []
    for path in iter_python_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            findings.append((path, 0, f"<read error: {exc}>"))
            continue
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            token = stripped.rstrip()
            if any(stripped.startswith(marker) for marker in MARKERS) or BARE_HASH_RE.fullmatch(token):
                findings.append((path, lineno, line.rstrip()))
    return findings


def main() -> int:
    findings = find_source_artifacts(REPO_ROOT)
    if not findings:
        print("OK: no pasted patch/revision artifacts found in Python sources.")
        return 0

    print("ERROR: found pasted patch/revision artifacts in Python sources:", file=sys.stderr)
    for path, lineno, line in findings:
        rel_path = path.relative_to(REPO_ROOT)
        print(f"  {rel_path}:{lineno}: {line}", file=sys.stderr)
    print(
        "\nFix: remove the reported artifact or replace the affected file with the clean "
        "repository file. Apply patches with git instead of pasting PR/diff text "
        "or commit hashes into the .py file.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
