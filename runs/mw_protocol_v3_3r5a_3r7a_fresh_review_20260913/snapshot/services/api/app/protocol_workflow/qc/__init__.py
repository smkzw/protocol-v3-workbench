"""Protocol v3 QC check packages.

3R.5A adds the R03 QC-table criteria checks in :mod:`.r03`.  These checks are
pure typed-input/typed-output functions reusing the existing
``CheckerFinding`` / ``FixtureCheckResult`` semantics; no product consumers
(generation model, Word export, UI) are wired yet.
"""
from . import r03

__all__ = ["r03"]
