"""Chapter-CLI spawn environment propagation (ledger E2, 2026-10-08).

The chapter assembly/lint CLI subprocesses import third-party runtime
dependencies (pydantic) through the interpreter's site-packages. Depending
on the install layout those packages live either in the interpreter's own
site-packages (homebrew ``/opt/homebrew/lib/python3.x/site-packages``, a
venv) or in the PEP 370 user site (``~/Library/Python/3.x/...``). The
hermetic CLI env keeps ``PYTHONNOUSERSITE=1`` for determinism, which hides
the user site from the child process — the 2026-10-08 full-gate red
(``ModuleNotFoundError: No module named 'pydantic'`` raised by
``scripts/qc/protocol_v3/assemble_chapter_registry.py`` under
``tests/protocol_v3/test_chapter_batch1.py``) was exactly that layout
mismatch: the parent pytest interpreter resolved pydantic from the user
site, the spawned CLI could not.

Propagating the parent interpreter's effective site-package directories
explicitly onto the child ``PYTHONPATH`` makes the spawn immune to
homebrew / user-site / venv layout differences without reopening the
environment to ambient variables (PATH, HOME, proxy vars, ... stay
minimal). Repo-relative entries keep precedence because callers prepend
their own ``PYTHONPATH`` entries before the propagated ones.
"""
from __future__ import annotations

import os
import site


def propagated_site_path_entries() -> str:
    """Site-package dirs visible to THIS interpreter, os.pathsep-joined.

    Order mirrors the interpreter's own resolution order (interpreter
    sites first, user site last); empty or nonexistent dirs are skipped so
    venv, homebrew and user-site layouts all work. Returns an empty string
    when nothing propagates, which keeps callers' ``os.pathsep.join``
    harmless.
    """
    entries: list[str] = []
    candidates: list[str] = []
    try:
        candidates.extend(site.getsitepackages())
    except Exception:  # pragma: no cover - exotic embedded interpreters
        pass
    if site.ENABLE_USER_SITE:
        candidates.append(site.getusersitepackages())
    for candidate in candidates:
        if candidate and os.path.isdir(candidate) and candidate not in entries:
            entries.append(candidate)
    return os.pathsep.join(entries)


def with_propagated_site_path(base_pythonpath: str) -> str:
    """Extend a repo-relative ``PYTHONPATH`` with the propagated site dirs."""
    propagated = propagated_site_path_entries()
    if not propagated:
        return base_pythonpath
    return base_pythonpath + os.pathsep + propagated
