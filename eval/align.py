#!/usr/bin/env python3
"""WP-M1-EVAL 对齐层：full-draft section → TP-MA-07 v2 语义节点。

对齐优先级（见 plans/mw_reboot_20261017/04_EVAL.md 与任务合同）：
1. section 自带 semantic_node_id（未来 SectionDraft schema）→ native；
2. eval/node_map.json 静态映射表（数据文件）按 (section_number, heading) 精确命中 → exact；
3. 仅 section_number 命中 → number_only（弱信号）；
4. 都未命中 → unmatched（semantic_node_id=None，计入对齐缺口）。

本模块不含任何具体药物/疾病/章号分支；映射关系全部在 node_map.json 数据文件里。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MATCH_NATIVE = "native"
MATCH_EXACT = "exact"
MATCH_APPROX = "approx"
MATCH_NUMBER_ONLY = "number_only"
MATCH_UNMATCHED = "unmatched"

VALID_MATCH_QUALITIES = {"exact", "approx"}


@dataclass(frozen=True)
class NodeMapEntry:
    section_number: str
    heading: str
    semantic_node_id: str
    match_quality: str  # 数据侧标注：exact | approx


class NodeMap:
    """eval/node_map.json 的加载与查询。"""

    def __init__(self, entries: list[NodeMapEntry], source_tree: Path | None = None):
        self.entries = entries
        self.source_tree = source_tree
        self._by_pair: dict[tuple[str, str], NodeMapEntry] = {
            (e.section_number, _norm_heading(e.heading)): e for e in entries
        }
        self._by_number: dict[str, NodeMapEntry] = {}
        for e in entries:
            self._by_number.setdefault(e.section_number, e)

    @classmethod
    def load(cls, path: Path) -> "NodeMap":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = [
            NodeMapEntry(
                section_number=str(item["section_number"]),
                heading=str(item["heading"]),
                semantic_node_id=str(item["semantic_node_id"]),
                match_quality=str(item.get("match_quality", "approx")),
            )
            for item in raw.get("entries", [])
        ]
        tree_ref = raw.get("source_tree")
        source_tree: Path | None = None
        if tree_ref:
            candidate = Path(tree_ref)
            if not candidate.is_absolute():
                # node_map.json 位于 eval/ 下，仓库根是其父目录的父目录
                candidate = Path(path).resolve().parent.parent / candidate
            source_tree = candidate if candidate.exists() else None
        return cls(entries, source_tree)

    def validate_against_tree(self) -> list[str]:
        """校验映射目标都存在于 TP-MA-07 v2 节点树；返回问题列表。"""
        if self.source_tree is None:
            return ["node_map.source_tree 文件不存在，跳过节点树校验"]
        tree = json.loads(self.source_tree.read_text(encoding="utf-8"))
        known = {n["id"] for n in tree.get("outlined_tree", {}).get("nodes", [])}
        problems = []
        for e in self.entries:
            if e.match_quality not in VALID_MATCH_QUALITIES:
                problems.append(f"条目 ({e.section_number}, {e.heading}) match_quality 非法")
            if e.semantic_node_id not in known:
                problems.append(f"条目 ({e.section_number}, {e.heading}) 指向未知节点 {e.semantic_node_id}")
        return problems

    def lookup(self, section_number: str, heading: str) -> tuple[str | None, str]:
        """返回 (semantic_node_id | None, match_quality)。match_quality 见模块 docstring。"""
        pair = self._by_pair.get((str(section_number), _norm_heading(heading)))
        if pair is not None:
            # 数据侧标注 approx 的条目，对齐类型沿用其近似标记
            kind = pair.match_quality if pair.match_quality in VALID_MATCH_QUALITIES else MATCH_EXACT
            return pair.semantic_node_id, kind
        number_only = self._by_number.get(str(section_number))
        if number_only is not None:
            return number_only.semantic_node_id, MATCH_NUMBER_ONLY
        return None, MATCH_UNMATCHED


def load_node_map(path: Path) -> NodeMap:
    """加载 eval/node_map.json 静态映射表（数据文件）。"""
    return NodeMap.load(path)


@dataclass(frozen=True)
class AlignmentRecord:
    section_id: str
    section_number: str
    heading: str
    semantic_node_id: str | None
    match_quality: str  # native | exact | approx | number_only | unmatched


def _norm_heading(heading: str) -> str:
    return " ".join(str(heading or "").split())


class Aligner:
    def __init__(self, node_map: NodeMap):
        self.node_map = node_map

    def align_sections(self, sections: list[dict]) -> list[AlignmentRecord]:
        records: list[AlignmentRecord] = []
        for s in sections:
            native = s.get("semantic_node_id")
            if native:
                records.append(
                    AlignmentRecord(
                        section_id=str(s.get("section_id", "")),
                        section_number=str(s.get("section_number", "")),
                        heading=str(s.get("heading", "")),
                        semantic_node_id=str(native),
                        match_quality=MATCH_NATIVE,
                    )
                )
                continue
            node_id, kind = self.node_map.lookup(s.get("section_number", ""), s.get("heading", ""))
            records.append(
                AlignmentRecord(
                    section_id=str(s.get("section_id", "")),
                    section_number=str(s.get("section_number", "")),
                    heading=str(s.get("heading", "")),
                    semantic_node_id=node_id,
                    match_quality=kind,
                )
            )
        return records
