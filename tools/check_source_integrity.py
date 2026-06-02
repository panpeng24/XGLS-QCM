"""Check Python sources for accidentally pasted unified-diff markers.

This catches lines such as ``@@ -99,117 +100,120 @@`` that can be
introduced when a patch/diff is copied into a .py file instead of applying the
patch with git. Such markers make Python fail immediately with SyntaxError.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv"}
MARKERS = ("@@ ", "diff --git ", "<<<<<<< ", "=======", ">>>>>>> ")


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def find_markers(root: Path):
    findings = []
    for path in iter_python_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            findings.append((path, 0, f"<read error: {exc}>"))
            continue
        for lineno, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if any(stripped.startswith(marker) for marker in MARKERS):
                findings.append((path, lineno, line.rstrip()))
    return findings


def main() -> int:
    findings = find_markers(REPO_ROOT)
    if not findings:
        print("OK: no diff/merge-conflict markers found in Python sources.")
        return 0

    print("ERROR: found diff/merge-conflict markers in Python sources:", file=sys.stderr)
    for path, lineno, line in findings:
        rel_path = path.relative_to(REPO_ROOT)
        print(f"  {rel_path}:{lineno}: {line}", file=sys.stderr)
    print(
        "\nFix: replace the affected file with the clean repository file, or apply the "
        "patch with git instead of pasting the diff text into the .py file.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
