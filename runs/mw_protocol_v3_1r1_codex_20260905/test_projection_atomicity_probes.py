"""Additional acceptance checks for compound DELETE/INSERT projection operations.

Authored independently while repair runs; execute only against returned/frozen candidate.
"""
import runpy
import sqlite3
from pathlib import Path

import pytest

from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory

fixtures = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tests/protocol_v3/test_repository_backends.py"))


@pytest.mark.parametrize("projection", ["decision", "coverage"])
def test_caught_projection_insert_failure_preserves_previous_projection(tmp_path, projection):
    path = tmp_path / "projection.sqlite"
    factory = build_unit_of_work_factory({"backend": "sqlite", "path": path})
    if projection == "decision":
        table, key_column = "read_decision_graph", "decision_key"
        replace_method, get_method, make = "replace_decision_graph", "get_decision_graph", fixtures["_decision"]
    else:
        table, key_column = "read_chapter_coverage", "semantic_node_id"
        replace_method, get_method, make = "replace_chapter_coverage", "get_chapter_coverage", fixtures["_coverage"]
    project, scope = fixtures["_PROJ_A"], "synthetic:scope:1"
    old = make("old:a")
    with factory() as uow:
        getattr(uow.read_model_repository, replace_method)(project, scope, (old,))
    with sqlite3.connect(path) as conn:
        # Identifiers are fixed test constants above, never external input.
        conn.execute(f"CREATE TRIGGER synthetic_projection_failure BEFORE INSERT ON {table} "
                     f"WHEN NEW.{key_column} = 'new:b' BEGIN SELECT RAISE(FAIL, 'synthetic projection failure'); END")
    with factory() as uow:
        with pytest.raises(sqlite3.IntegrityError):
            getattr(uow.read_model_repository, replace_method)(project, scope, (make("new:a"), make("new:b")))
    with factory() as check:
        assert getattr(check.read_model_repository, get_method)(project, scope) == (old,), "failed replacement changed prior projection"
