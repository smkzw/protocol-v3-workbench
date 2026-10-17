"""WP-M3-LINT 自测：对既有 _instruction() 提示文本跑分层 lint。

只读 services/api/app/medical_writing_full_draft.py（不修改），在运行时调用其
_instruction() 拿到真实下发文本，按 L0 层跑 prompt_lint，将违规清单写入
tools/writing/lint_baseline_report.json。

该提示文本含轮次补丁（NEW-37/NEW-27、第7轮）与适应症专属规则（具体量表名），
正是分层 lint 应当抓出的证据。DoD：抓出 ≥3 类（个 rule）违规。

    python3 tools/writing/run_baseline_check.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for path in (str(REPO_ROOT / "services/api"), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import prompt_lint  # noqa: E402

SOURCE_FILE = REPO_ROOT / "services/api/app/medical_writing_full_draft.py"
MIN_RULE_CATEGORIES = 3


def main() -> int:
    from app.medical_writing_full_draft import MedicalWritingFullDraftService

    text = MedicalWritingFullDraftService._instruction(
        [{"section_id": "SELFTEST_BASELINE"}],
        {"minimum_body_chars": 500, "decision_path_owners": {}},
    )
    report = prompt_lint.lint_prompt(text, "L0")

    counts = Counter(v["rule"] for v in report["violations"])
    categories = sorted(counts)
    baseline = {
        "purpose": "WP-M3-LINT 基线：既有 _instruction() 文本应被 lint 抓出违规",
        "source": str(SOURCE_FILE.relative_to(REPO_ROOT)),
        "layer": report["layer"],
        "char_count": report["char_count"],
        "budget": report["budget"],
        "pass": report["pass"],
        "rule_categories_flagged": categories,
        "rule_category_count": len(categories),
        "violation_counts_by_rule": dict(counts),
        "total_violations": len(report["violations"]),
        "violations": report["violations"],
        "terms_file": str((HERE / "lint_terms.json").relative_to(REPO_ROOT)),
    }
    (HERE / "lint_baseline_report.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(
        {k: baseline[k] for k in (
            "source", "char_count", "budget", "pass",
            "rule_categories_flagged", "violation_counts_by_rule",
            "total_violations",
        )},
        ensure_ascii=False, indent=2,
    ))
    if len(categories) < MIN_RULE_CATEGORIES:
        print(f"DoD 未满足：违规类别 {len(categories)} < {MIN_RULE_CATEGORIES}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
