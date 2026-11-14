"""``python -m pars_erp`` entry point."""

from __future__ import annotations

import sys

from pars_erp.cli import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
