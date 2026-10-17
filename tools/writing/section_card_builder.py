"""SectionCard 生成器骨架（WP-M3-LINT）。

从冻结章节合同（ChapterContractV2，111 份，存于
config/medical_writing/protocol_v3/templates/tp_ma_07_v2/chapter_contracts/）
压缩生成 SectionCard（schema 见 eval/SCHEMAS.md 第 7 节）。

首版边界（如实声明）：
- tier 分类规则来自数据文件 node_tiers.json；只对能明确分类的节点出卡，
  分不了（无规则命中或命中多个互斥 tier）的节点标 needs_review 进统计，不硬分类。
- purpose 首版用模板节点标题充当（≤80 字），不是人工撰写目的。
- consumes_clause_ids 首版恒为空：ClauseBank 属 M2 语料依赖，尚未建成。
- length_range_chars / style_example_budget 用 schema 默认值，尚无逐节篇幅证据。
- risk_level 首版启发式：合同含条件适用性规则（内容随研究设计分叉）→ high，
  否则 → medium。该启发式写入 stats，供后续替换。

产物写 runtime/（gitignore 覆盖，不进 git）：
    runtime/section_cards/cards.jsonl
    runtime/section_cards/build_stats.json

CLI：
    python3 tools/writing/section_card_builder.py            # 全量构建 + 打印统计
    python3 tools/writing/section_card_builder.py --help     # 覆盖输入输出路径
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TIER_VALUES = ("D", "C", "N")
DEFAULT_LENGTH_RANGE = [200, 1200]
DEFAULT_STYLE_EXAMPLE_BUDGET = 3
PURPOSE_MAX_CHARS = 80

# schema 未见逐节篇幅证据前的默认值；如实写进 stats.heuristics。
HEURISTICS = {
    "purpose": "模板节点标题截断到80字，非人工目的",
    "length_range_chars": "默认值",
    "style_example_budget": "默认值",
    "risk_level": "合同含 conditional_applicability_rules → high，否则 medium",
    "consumes_clause_ids": "恒空，等待 M2 ClauseBank",
}


def default_template_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
    )


def default_out_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime/section_cards"


def load_node_tiers(path: Path) -> Dict[str, Any]:
    """加载 tier 分类表并校验 tier 取值。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    by_keyword = {
        tier: [str(kw) for kw in keywords]
        for tier, keywords in (raw.get("tier_by_title_keyword") or {}).items()
    }
    by_node_id = {
        tier: [str(node_id) for node_id in node_ids]
        for tier, node_ids in (raw.get("tier_by_node_id") or {}).items()
    }
    unknown = (set(by_keyword) | set(by_node_id)) - set(TIER_VALUES)
    if unknown:
        raise ValueError(f"node_tiers.json 出现未知 tier：{sorted(unknown)}")
    return {"tier_by_title_keyword": by_keyword, "tier_by_node_id": by_node_id}


def load_node_titles(root: Path) -> Dict[str, str]:
    """语义节点 ID -> 中文标题（同 template_runtime 的标题合成口径）。"""
    tree = json.loads((root / "node_tree.json").read_text(encoding="utf-8"))
    titles = {
        node["id"]: " ".join(
            filter(None, (node.get("section_number"), node["title_zh"]))
        )
        for key in ("heading_style_tree", "outlined_tree")
        for node in tree[key]["nodes"]
    }
    titles.setdefault("v2_front_block", "封面与方案基本信息")
    return titles


def classify(
    node_id: str,
    title: str,
    rules: Dict[str, Any],
) -> Tuple[Optional[str], str]:
    """返回 (tier | None, reason)。None 表示 needs_review，不硬分类。"""
    for tier, node_ids in rules["tier_by_node_id"].items():
        if node_id in node_ids:
            return tier, "node_id_override"
    matched = {
        tier
        for tier, keywords in rules["tier_by_title_keyword"].items()
        if any(keyword and keyword in title for keyword in keywords)
    }
    if len(matched) == 1:
        return matched.pop(), "title_keyword"
    if not matched:
        return None, "no_rule_match"
    return None, "ambiguous_rule_match:" + ",".join(sorted(matched))


def _unique(values: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def build_card(contract: Dict[str, Any], tier: str, title: str) -> Dict[str, Any]:
    """按 eval/SCHEMAS.md 第 7 节压缩一份合同为 SectionCard。"""
    node_id = str(contract["semantic_node_id"])
    content = contract.get("substantive_content") or {}
    required_elements = _unique(
        [f"claim:{item['claim_type']}"
         for item in content.get("claim_requirements") or []
         if item.get("obligation") == "required"]
        + [f"fact:{item['fact_path']}"
           for item in content.get("fact_requirements") or []
           if item.get("obligation") == "required"]
        + [f"structural:{item['object_kind']}"
           for item in content.get("structural_object_obligations") or []]
    )
    consumes_fact_paths = _unique(
        [str(item["fact_path"]) for item in content.get("fact_requirements") or []]
        + [str(path)
           for rule in contract.get("conditional_applicability_rules") or []
           for path in rule.get("triggering_fact_paths") or []]
        + [str(path)
           for rule in contract.get("conditional_applicability_rules") or []
           for path in rule.get("required_when_active_fact_paths") or []]
    )
    return {
        "card_id": f"card_{node_id}",
        "semantic_node_id": node_id,
        "tier": tier,
        "purpose": title[:PURPOSE_MAX_CHARS],
        "required_elements": required_elements,
        "consumes_fact_paths": consumes_fact_paths,
        "consumes_clause_ids": [],
        "style_example_budget": DEFAULT_STYLE_EXAMPLE_BUDGET,
        "length_range_chars": list(DEFAULT_LENGTH_RANGE),
        "risk_level": (
            "high" if contract.get("conditional_applicability_rules") else "medium"
        ),
    }


def build_all(
    root: Path,
    tiers_rules: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """读取 root 下全部冻结合同，产出 (cards, stats)。"""
    root = Path(root)
    titles = load_node_titles(root)
    cards: List[Dict[str, Any]] = []
    needs_review: List[Dict[str, str]] = []
    tier_counts = {tier: 0 for tier in TIER_VALUES}
    risk_counts = {"high": 0, "medium": 0, "low": 0}
    total = 0
    for path in sorted((root / "chapter_contracts").glob("*.json")):
        contract = json.loads(path.read_text(encoding="utf-8"))
        node_id = str(contract["semantic_node_id"])
        total += 1
        title = titles.get(node_id, "")
        tier, reason = classify(node_id, title, tiers_rules)
        if tier is None:
            needs_review.append(
                {"node_id": node_id, "title": title, "reason": reason}
            )
            continue
        card = build_card(contract, tier, title)
        cards.append(card)
        tier_counts[tier] += 1
        risk_counts[card["risk_level"]] += 1
    stats = {
        "template_root": str(root),
        "total_contracts": total,
        "cards_emitted": len(cards),
        "tier_counts": tier_counts,
        "risk_counts": risk_counts,
        "needs_review_count": len(needs_review),
        "needs_review_nodes": needs_review,
        "heuristics": HEURISTICS,
    }
    return cards, stats


def write_outputs(
    out_dir: Path,
    cards: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "cards.jsonl").open("w", encoding="utf-8") as handle:
        for card in cards:
            handle.write(json.dumps(card, ensure_ascii=False) + "\n")
    (out_dir / "build_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="由冻结章节合同生成 SectionCard")
    parser.add_argument("--template-root", type=Path, default=default_template_root())
    parser.add_argument("--node-tiers", type=Path, default=None,
                        help="tier 分类表（默认随附 node_tiers.json）")
    parser.add_argument("--out-dir", type=Path, default=default_out_dir())
    args = parser.parse_args(argv)

    contracts_dir = args.template_root / "chapter_contracts"
    if not contracts_dir.is_dir():
        print(f"合同目录不存在：{contracts_dir}", file=sys.stderr)
        return 2
    tiers_path = args.node_tiers or (
        Path(__file__).resolve().parent / "node_tiers.json"
    )
    cards, stats = build_all(args.template_root, load_node_tiers(tiers_path))
    write_outputs(args.out_dir, cards, stats)
    summary = {key: stats[key] for key in (
        "total_contracts", "cards_emitted", "tier_counts",
        "risk_counts", "needs_review_count",
    )}
    summary["output"] = str(args.out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
