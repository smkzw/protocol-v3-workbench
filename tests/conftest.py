"""Root test-session sandbox (0927V1 three-lane plan, A10/F02).

services/api/app/main.py binds RUNTIME_DIR once at import time
(main.py:543-545) and the writing-reference repository with it
(main.py:1473). Without this file, the first test importing app.main under a
bare ``pytest`` run bound the whole session to the repo-root ``runtime/``
live path (97 test files use TestClient(app)).

This conftest must run before ANY test module import, so it acts at import
time (conftest load) rather than via a fixture: every pytest session gets a
fresh private runtime dir. The acceptance-gate whitelist strips
WORKBENCH_RUNTIME_DIR from gate-spawned children anyway, so nested sessions
each create their own private dir.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# app.main mixes absolute ``from app...`` imports (main.py:205 and others)
# with the services.api.app package path; the acceptance gate provides
# services/api via PYTHONPATH (HANDOFF R11/R15) — bare pytest gets the same
# treatment here so both invocation layouts behave identically (R1).
for _extra in (str(_REPO_ROOT / "services" / "api"), str(_REPO_ROOT)):
    if _extra not in sys.path:
        sys.path.append(_extra)

_RUNTIME_DIR = tempfile.mkdtemp(prefix="wb_runtime_session_")
atexit.register(shutil.rmtree, _RUNTIME_DIR, ignore_errors=True)
os.environ["WORKBENCH_RUNTIME_DIR"] = _RUNTIME_DIR
