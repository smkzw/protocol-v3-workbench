"""An exact table/column-name clone is not an owned constrained schema."""
import hashlib
import sqlite3

import pytest

from app.protocol_workflow.storage.sqlite import SqliteStorageError, build_unit_of_work_factory


def test_same_names_without_product_constraints_are_rejected(tmp_path):
    source, target = tmp_path / "product.sqlite", tmp_path / "foreign.sqlite"
    build_unit_of_work_factory({"backend": "sqlite", "path": source})
    with sqlite3.connect(target) as conn:
        conn.execute("ATTACH DATABASE ? AS product", (str(source),))
        tables = conn.execute("SELECT name FROM product.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        for (name,) in tables:
            # Names originate from this test's newly-created product schema.
            conn.execute(f'CREATE TABLE "{name}" AS SELECT * FROM product."{name}"')
        assert all(row[5] == 0 for row in conn.execute("PRAGMA table_info(event_stream)")), "fixture must remove product primary key"
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(SqliteStorageError):
        build_unit_of_work_factory({"backend": "sqlite", "path": target})
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
