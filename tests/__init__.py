"""Process-scoped runtime isolation for the unittest package.

Tests that import ``services.api.app.main`` must never instantiate mutable stores
under the real workbench runtime directory. An explicit caller override still wins.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


if not os.environ.get("WORKBENCH_RUNTIME_DIR", "").strip():
    _TEST_RUNTIME_DIR = Path(
        tempfile.mkdtemp(prefix="medical-workbench-test-runtime-")
    ).resolve()
    os.environ["WORKBENCH_RUNTIME_DIR"] = str(_TEST_RUNTIME_DIR)
    atexit.register(
        lambda: shutil.rmtree(_TEST_RUNTIME_DIR, ignore_errors=True)
    )
