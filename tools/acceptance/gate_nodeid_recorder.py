"""pytest plugin: record exact native nodeids + per-phase outcomes for the G0
acceptance gate (A04/A05).

Pure stdlib pytest hook API, zero dependencies. The plugin only writes a file
when ``--nodeid-report=PATH`` is given; loading it without that option is a
no-op, so ordinary runs are unaffected.

Why: junit xml loses the setup/call split and xfail markers, and the old
gate-side ``_case_key`` stripped class/param segments, so a skipped required
test, a same-leaf test on another class, or a different parametrize bracket
could all masquerade as required coverage. This plugin records
``{nodeid, when, outcome, wasxfail}`` for every runtest report so the gate
can demand: exact nodeid, setup passed, call passed, no xfail marker.
"""
from __future__ import annotations

import json
import os


_RECORDS: list[dict] = []
_REPORT_PATH: str | None = None


def pytest_addoption(parser):
    group = parser.getgroup("gate")
    group.addoption(
        "--nodeid-report", dest="nodeid_report", default=None,
        help="write JSON {records: [{nodeid, when, outcome, wasxfail}]} for the acceptance gate",
    )


def pytest_configure(config):
    global _REPORT_PATH
    _REPORT_PATH = config.getoption("nodeid_report")
    _RECORDS.clear()


def pytest_runtest_logreport(report):
    # pytest >= 9 TestReport carries no .config; the plugin module is imported
    # once per pytest process, so module-level state is the session store.
    _RECORDS.append({
        "nodeid": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
        "wasxfail": bool(getattr(report, "wasxfail", None)),
    })


def pytest_sessionfinish(session, exitstatus):
    if not _REPORT_PATH:
        return
    doc = {"records": list(_RECORDS)}
    tmp = f"{_REPORT_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, _REPORT_PATH)
