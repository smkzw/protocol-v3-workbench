#!/usr/bin/env python3.14
"""G1 step6 drift-family sampler: run one representative per family in BOTH
the live repo and the 53feb06 export tree, compare first-failure fingerprints
and messages, emit machine JSON for caveat classification."""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313")
EXPORT = Path("/tmp/headcheck_0926v1")
OUT = REPO / "runs/requirements_v2_20260919/t17_round18_0926v1/g1_step6_drift_samples.json"

sys.path.insert(0, str(REPO / "tools/acceptance"))
import run_acceptance_gate as g  # noqa: E402

drift = json.loads((REPO / "runs/requirements_v2_20260919/t17_round18_0926v1/g1_step6_drift_nodeids.json").read_text())
families: dict[str, list[str]] = {}
for n in drift:
    families.setdefault(n.split("::")[0], []).append(n)

# the six chapter_batch CLI tests form one mechanism family
reps = {}
for fam, nodes in families.items():
    key = "tests/protocol_v3/test_chapter_batch* (cli subprocess family)" if fam.startswith("tests/protocol_v3/test_chapter_batch") else fam
    reps.setdefault(key, nodes[0])

results = []
for fam, nodeid in reps.items():
    entry = {"family": fam, "representative": nodeid, "family_size": sum(len(v) for k, v in families.items() if (k if not k.startswith("tests/protocol_v3/test_chapter_batch") else "tests/protocol_v3/test_chapter_batch* (cli subprocess family)") == fam)}
    for label, root in (("live", REPO), ("export53feb06", EXPORT)):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                junit = Path(tmp) / "r.xml"
                g.run_pytest(root, junit, 240, [nodeid])
                rep = g.parse_junit(junit, root)
            bad = rep["failures"] + rep["errors"]
            if bad:
                entry[label] = {"verdict": "FAILED", "fingerprint": bad[0]["fingerprint"],
                                "message": bad[0]["message"][:300]}
            elif rep.get("ok") and rep["total"] > 0:
                entry[label] = {"verdict": "PASSED", "total": rep["total"]}
            else:
                entry[label] = {"verdict": "NO_REPORT"}
        except Exception as exc:  # noqa: BLE001
            entry[label] = {"verdict": "ERROR", "detail": f"{type(exc).__name__}: {exc}"[:200]}
    if entry.get("live", {}).get("fingerprint") and entry.get("export53feb06", {}).get("fingerprint"):
        entry["fingerprint_match"] = entry["live"]["fingerprint"] == entry["export53feb06"]["fingerprint"]
    results.append(entry)
    print(f"done: {fam} live={entry['live']['verdict']} export={entry['export53feb06']['verdict']}", flush=True)

OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print("WROTE", OUT)
