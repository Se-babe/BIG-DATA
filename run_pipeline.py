"""Run end-to-end: clean.py → load.py → analyze.py.

Extra CLI flags are forwarded only to clean.py (for example `--sample 25000`).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    py = sys.executable
    clean_args = sys.argv[1:]
    subprocess.run([py, str(ROOT / "scripts" / "clean.py"), *clean_args], cwd=ROOT, check=True)
    subprocess.run([py, str(ROOT / "scripts" / "load.py")], cwd=ROOT, check=True)
    subprocess.run([py, str(ROOT / "scripts" / "analyze.py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
