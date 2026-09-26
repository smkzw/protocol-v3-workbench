"""A10 import-time binding: inside a pytest session, app.main's module-level
RUNTIME_DIR (services/api/app/main.py:543-545) and the writing-reference
repository binding (main.py:1473) must resolve to a PRIVATE runtime dir, never
the repo-root ``runtime/`` live path.

main.py reads WORKBENCH_RUNTIME_DIR once at first import; 97 test files import
``services.api.app.main`` (TestClient(app)), so the root tests/conftest.py has
to point that variable at a session-private dir before any test module import.
This module must stay alphabetically first among the acceptance tests so its
import is the session's first app.main import (mirroring the full-suite risk).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_app_runtime_binds_private_under_pytest_session():
    from services.api.app import main as app_main

    runtime = Path(str(app_main.RUNTIME_DIR))
    live_path = (REPO_ROOT / "runtime").resolve()
    private_root = Path(tempfile.gettempdir()).resolve()
    assert runtime != live_path, (
        f"app runtime bound to live repo path {runtime}; "
        "tests/conftest.py must set WORKBENCH_RUNTIME_DIR before app imports"
    )
    assert str(runtime).startswith(str(private_root)), (
        f"app runtime {runtime} is not under private temp root {private_root}"
    )
