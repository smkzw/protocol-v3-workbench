"""提示分层 lint（WP-M3-LINT）。

检查 L0 系统层 / L1 章节卡层提示文本是否违反分层纪律
（plans/mw_reboot_20261017/03_WRITING_SYSTEM.md「提示分层与预算」）：

- 出现具体药物名 / 疾病名 / 量表名（词表来自 lint_terms.json 数据文件，不写死在代码）；
- 出现缺陷编号（P0-xx / NEW-xx / R\\d+）；
- 出现轮次字样（第\\d+轮 / round）；
- 超出层预算（L0 ≤800 字，L1 ≤400 字，可由数据文件覆盖）。

输出 JSON 违规清单，每条形如 {"rule", "span", "hit"}。

CLI：
    python3 tools/writing/prompt_lint.py --layer L0 --file some_prompt.txt
    echo "提示文本" | python3 tools/writing/prompt_lint.py --layer L1 --stdin

退出码：0 = 通过；1 = 存在违规；2 = 用法/读取错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_LAYERS = ("L0", "L1")

# 预算兜底值；数据文件 lint_terms.json 的 layer_budgets 可覆盖。
LAYER_BUDGET_FALLBACK: Dict[str, int] = {"L0": 800, "L1": 400}

# 词表类别 -> 违规规则名。具体术语全部来自数据文件。
TERM_CATEGORIES = (
    ("drugs", "drug_name"),
    ("diseases", "disease_name"),
    ("scales", "scale_name"),
)

# 通用机制正则（不含量名）：缺陷编号与轮次字样。
FIXED_RULES = (
    ("defect_id", re.compile(r"P0-\d+|NEW-\d+|(?<![A-Za-z0-9])R\d+")),
    ("round_wording", re.compile(r"第\d+轮|\bround\b", re.IGNORECASE)),
)

_CONTEXT_WIDTH = 20


def default_terms_path() -> Path:
    return Path(__file__).resolve().parent / "lint_terms.json"


def load_terms(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载术语数据文件并做结构归一。"""
    raw = json.loads(Path(path or default_terms_path()).read_text(encoding="utf-8"))
    budgets = {
        key: int(value)
        for key, value in (raw.get("layer_budgets") or {}).items()
        if key in VALID_LAYERS
    }
    return {
        "drugs": [str(term) for term in raw.get("drugs", [])],
        "diseases": [str(term) for term in raw.get("diseases", [])],
        "scales": [str(term) for term in raw.get("scales", [])],
        "allowlist": [str(term) for term in raw.get("allowlist", [])],
        "layer_budgets": {**LAYER_BUDGET_FALLBACK, **budgets},
    }


def _context(text: str, start: int, end: int) -> str:
    left = text[max(0, start - _CONTEXT_WIDTH):start]
    right = text[end:end + _CONTEXT_WIDTH]
    return f"…{left}【{text[start:end]}】{right}…"


def _allowlisted(span_text: str, allowlist: List[str]) -> bool:
    folded = span_text.casefold()
    for entry in allowlist:
        folded_entry = entry.casefold()
        if folded in folded_entry or folded_entry in folded:
            return True
    return False


def lint_prompt(
    text: str,
    layer: str,
    terms_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """对一段提示文本执行分层 lint，返回可 JSON 序列化的报告。"""
    if layer not in VALID_LAYERS:
        raise ValueError(f"layer 必须是 {VALID_LAYERS} 之一，收到：{layer!r}")
    config = terms_config or load_terms()
    allowlist = [str(item) for item in config.get("allowlist", [])]
    budgets = {**LAYER_BUDGET_FALLBACK}
    budgets.update(
        {key: int(value) for key, value in (config.get("layer_budgets") or {}).items()
         if key in VALID_LAYERS}
    )
    budget = budgets[layer]

    violations: List[Dict[str, str]] = []

    char_count = len(text)
    if char_count > budget:
        violations.append({
            "rule": f"budget_{layer}",
            "span": f"全文{char_count}字",
            "hit": f"{layer}层预算{budget}字，实际{char_count}字",
        })

    for category, rule_name in TERM_CATEGORIES:
        for term in config.get(category, []):
            if not term:
                continue
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            for match in pattern.finditer(text):
                if _allowlisted(match.group(0), allowlist):
                    continue
                violations.append({
                    "rule": rule_name,
                    "span": match.group(0),
                    "hit": _context(text, match.start(), match.end()),
                })

    for rule_name, pattern in FIXED_RULES:
        for match in pattern.finditer(text):
            if _allowlisted(match.group(0), allowlist):
                continue
            violations.append({
                "rule": rule_name,
                "span": match.group(0),
                "hit": _context(text, match.start(), match.end()),
            })

    return {
        "layer": layer,
        "pass": not violations,
        "char_count": char_count,
        "budget": budget,
        "violations": violations,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="提示分层 lint（L0/L1）")
    parser.add_argument("--layer", required=True, choices=VALID_LAYERS)
    parser.add_argument("--terms", type=Path, default=None,
                        help="术语数据文件路径（默认随附 lint_terms.json）")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--text")
    source.add_argument("--stdin", action="store_true")
    args = parser.parse_args(argv)

    try:
        text = (
            args.file.read_text(encoding="utf-8")
            if args.file is not None
            else sys.stdin.read() if args.stdin else args.text or ""
        )
        report = lint_prompt(text, args.layer, load_terms(args.terms))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
