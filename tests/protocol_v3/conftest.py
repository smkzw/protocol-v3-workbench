"""Make bare sibling-test imports resolvable in the protocol_v3 test tree.

Integration tests import helpers from the parent directory by bare module
name (``from test_clinical_design_worker import ...``) and sibling modules
inside ``integration/``. Under pytest's default ``prepend`` import mode those
names only resolve once the owning directory is on ``sys.path``, and
collection order (``integration/`` sorts before ``test_*.py``) decides who
gets inserted first — the source of the historic "collection error, exit 2,
failed=0" false-green class (F08). Inserting both directories up front makes
every bare sibling import resolvable under any runner and any collection
order.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TESTS = _HERE.parent
for _candidate in (_HERE, _HERE / "integration", _TESTS):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
