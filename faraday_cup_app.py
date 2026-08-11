"""Robust launcher for the Faraday Cup TOF analyzer app.

The preferred UI is the PyQt/pyqtgraph implementation in
``faraday_cup_qt_app.py``.  Some Windows virtual environments can have a broken
PyQt5 installation that raises ``ImportError: DLL load failed while importing
QtCore`` before the window is created.  This launcher catches that startup
failure and falls back to a Tkinter UI that only depends on Python's standard
library plus the numeric analysis dependencies.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from faraday_cup_qt_app import main as qt_main
    except ImportError as exc:
        print("PyQt GUI startup failed; falling back to Tkinter UI.")
        print(f"PyQt import error: {exc}")
        print(
            "If you want the PyQt UI on Windows, reinstall Qt bindings in the active venv, for example:\n"
            "  python -m pip uninstall -y PyQt5 PyQt5-Qt5 PyQt5-sip pyqtgraph\n"
            "  python -m pip install PyQt5 pyqtgraph\n"
        )
        from faraday_cup_tk_app import main as tk_main

        return tk_main()
    return qt_main()


if __name__ == "__main__":
    raise SystemExit(main())
