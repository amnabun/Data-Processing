"""Build a standalone executable on the target operating system.

Install requirements-dev.txt, then run: python build_executable.py
The result is dist/cw2 (dist/cw2.exe on Windows); it supports both CLI and GUI.
"""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "cw2",
            "--hidden-import",
            "matplotlib.backends.backend_tkagg",
            "--hidden-import",
            "matplotlib.backends.backend_agg",
            str(root / "cw2.py"),
        ],
        cwd=root,
        check=True,
    )
