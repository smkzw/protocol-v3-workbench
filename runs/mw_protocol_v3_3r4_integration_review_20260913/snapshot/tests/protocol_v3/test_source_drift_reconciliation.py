"""R.2 source drift must remain visible, including protected/shared changes."""
import importlib.util
from pathlib import Path


def module():
    spec = importlib.util.spec_from_file_location(
        "source_drift", Path(__file__).resolve().parents[2] /
        "scripts/qc/protocol_v3/reconcile_source_drift.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_diff_retains_monitoring_shared_added_and_removed():
    left = [{"path": "frontend/src/App.jsx", "sha256": "old"},
            {"path": "services/api/app/monitoring_engine.py", "sha256": "old"},
            {"path": "services/api/app/medical_writing_legacy.py", "sha256": "old"}]
    right = [{"path": "frontend/src/App.jsx", "sha256": "new"},
             {"path": "services/api/app/monitoring_engine.py", "sha256": "new"},
             {"path": "services/api/app/medical_writing_new.py", "sha256": "new"}]
    rows = module().compare_entries(left, right)
    assert len(rows) == 4
    assert {r["classification"] for r in rows} == {
        "monitoring_protected", "shared_manual_review", "medical_writing_review"
    }
    assert {r["change"] for r in rows} == {"changed", "left_only", "right_only"}
    assert module().compare_entries(left, left) == []


def test_mode_and_symlink_target_drift_are_not_hidden():
    left = [{"path": "scripts/a.py", "sha256": "same", "mode": 420}]
    right = [{"path": "scripts/a.py", "sha256": "same", "mode": 493}]
    assert len(module().compare_entries(left, right)) == 1


def test_baseline_observation_does_not_call_snapshot_or_mutator():
    source = (Path(__file__).resolve().parents[2] /
              "scripts/qc/protocol_v3/reconcile_source_drift.py").read_text()
    assert "build_manifest(" in source
    assert "build_snapshot(" not in source
    assert "apply_hygiene(" not in source
