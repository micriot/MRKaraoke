"""Local release checks that never read or print configured credentials."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    for module in (
        "singws_live_test_runner.domain",
        "singws_live_test_runner.preflight",
        "singws_live_test_runner.api",
        "singws_live_test_runner.diagnostics",
    ):
        importlib.import_module(module)
    print("Release checks passed: local modules import; credentials are runtime-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
