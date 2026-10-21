"""PyInstaller entry point.

Kept tiny on purpose: frozen builds need a real script path, not ``-m``.
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from myai.app import main

    sys.exit(main())
