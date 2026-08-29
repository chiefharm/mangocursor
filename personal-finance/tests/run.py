#!/usr/bin/env python3
"""Run tests without pytest if needed: python tests/run.py"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> int:
    import tests.test_parse as a
    import tests.test_store as b
    import tests.test_report as c

    failed = 0
    for mod in (a, b, c):
        for name in dir(mod):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                if "tmp_path" in fn.__code__.co_varnames:
                    import tempfile
                    fn(Path(tempfile.mkdtemp()))
                else:
                    fn()
                print(f"ok  {mod.__name__}.{name}")
            except Exception:
                failed += 1
                print(f"FAIL {mod.__name__}.{name}")
                traceback.print_exc()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
