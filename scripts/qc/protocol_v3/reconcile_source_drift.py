"""R.2 source-only observation; never import or mutate the live application."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT.parent / "workbench"
BASELINE = ROOT / "tests/fixtures/protocol_v3/mutable_source_baseline.json"
HISTORICAL = BASELINE.with_name("mutable_source_baseline_20260809.json")
OLD_SHA = "32e274b47ec14a40f0bcaa280b4e8b81ccf06f61b3ee0c0606055d4d54f27d67"
MATERIAL = ("sha256", "type", "size", "mode", "resolved_sha256", "link_target")


def classification(path):
    if any(token in path for token in ("medical_monitoring", "medical-monitoring", "monitoring_", "/monitoring/")):
        return "monitoring_protected"
    if any(token in path for token in ("medical_writing", "medical-writing", "protocol_workflow", "protocol_v3")):
        return "medical_writing_review"
    return "shared_manual_review"


def compare_entries(left, right):
    left = {e["path"]: e for e in left}
    right = {e["path"]: e for e in right}
    rows = []
    for path in sorted(left.keys() | right.keys()):
        a, b = left.get(path), right.get(path)
        if a is not None and b is not None and all(a.get(k) == b.get(k) for k in MATERIAL):
            continue
        rows.append({"path": path, "classification": classification(path),
                     "change": "right_only" if a is None else "left_only" if b is None else "changed",
                     "left_sha256": a.get("sha256") if a else None,
                     "right_sha256": b.get("sha256") if b else None})
    return rows


def git(root, *args):
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def observe():
    spec = importlib.util.spec_from_file_location("baseline_reader", Path(__file__).with_name("build_source_baseline.py"))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    head_before = git(LIVE, "rev-parse", "HEAD")
    status_before = git(LIVE, "status", "--porcelain")
    live = builder.build_manifest(LIVE, "mw_protocol_v3_phaseR_20260905")
    isolated = builder.build_manifest(ROOT, "mw_protocol_v3_phaseR_20260905")
    # Reobserve to reject a changing input snapshot rather than bless mixed bytes.
    live_after = builder.build_manifest(LIVE, "mw_protocol_v3_phaseR_20260905")
    if (live["content_fingerprint"] != live_after["content_fingerprint"]
            or git(LIVE, "rev-parse", "HEAD") != head_before
            or git(LIVE, "status", "--porcelain") != status_before):
        raise ValueError("live source changed during read-only observation")
    old_bytes = HISTORICAL.read_bytes() if HISTORICAL.exists() else BASELINE.read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != OLD_SHA:
        raise ValueError("historical baseline hash mismatch")
    old = json.loads(old_bytes)
    rows = compare_entries(isolated["entries"], live["entries"])
    live.update({"source_commit": head_before, "supersedes_baseline_sha256": OLD_SHA,
                 "historical_baseline": str(HISTORICAL.relative_to(ROOT)),
                 "observation_scope": "source-only allowlist; not runtime or clinical acceptance"})
    report = {
        "schema_version": 1, "live_head": head_before, "live_status": status_before,
        "isolated_head": git(ROOT, "rev-parse", "HEAD"),
        "live_unchanged_during_observation": True,
        "live_entry_count": live["entry_count"], "isolated_entry_count": isolated["entry_count"],
        "live_fingerprint": live["content_fingerprint"],
        "diff_counts": dict(Counter(row["classification"] for row in rows)), "differences": rows,
        "old_isolated_vs_current_live": compare_entries(old["entries"], live["entries"]),
        "classification_caveat": "Path-based triage, not attribution. Shared files require semantic review; no files merged.",
        "scope_exclusions": ["runtime", "records", "logs", "evidence", "packages outside packages/contracts (including medical_monitoring)"]
    }
    return builder, old_bytes, live, isolated, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="Write only declared isolated R.2 artifacts")
    args = parser.parse_args()
    builder, old_bytes, live, isolated, report = observe()
    if args.record:
        output = ROOT / "runs/mw_protocol_v3_phaseR_20260905"
        if output.exists():
            raise ValueError("R.2 evidence destination already exists; never overwrite")
        if not HISTORICAL.exists():
            HISTORICAL.write_bytes(old_bytes)
        elif HISTORICAL.read_bytes() != old_bytes:
            raise ValueError("historical baseline conflict")
        output.mkdir()
        builder._write_json_atomic(output / "source_drift.json", report)
        builder._write_json_atomic(output / "isolated_source_observation.json", isolated)
        builder._write_json_atomic(output / "live_source_observation.json", live)
        builder._write_json_atomic(BASELINE, live)
    print(json.dumps({k: v for k, v in report.items() if k not in {"differences", "old_isolated_vs_current_live"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
