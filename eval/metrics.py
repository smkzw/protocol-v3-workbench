#!/usr/bin/env python3
"""WP-M1-EVAL 指标层：给定 full-draft 产物 sections 与对齐记录，计算首版指标。

指标口径（任务合同 + plans/mw_reboot_20261017/04_EVAL.md）：
- 覆盖率：适用节点（本文档有对齐目标的 section）中有实质正文的比例。
  实质正文 = 中文字符数 ≥ MIN_BODY_CJK_CHARS 且不含占位标记。
  占位判定 = 含【待补齐】/待确认/TBD（不区分大小写）或正文中文字符 < MIN_BODY_CJK_CHARS。
- 占位数：占位标记出现总次数与含占位章节数。
- 泄漏：正文出现竞品药名（StyleKit 提供）的节比例；无竞品词表时标记未计算。
- 耗时：由 job 记录的 created/finished 推（run 层取数，本层只做换算）。
- 事实冲突：首版空实现，保留接口（返回空列表，computed=False）。

本模块不含任何具体药物/疾病/量表名/章号分支。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 占位标记（泛化：通用写作占位词，非项目专属）
PLACEHOLDER_MARKERS = ("【待补齐】", "待确认", "TBD")
MIN_BODY_CJK_CHARS = 100

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def cjk_char_count(text: str) -> int:
    return len(_CJK_RE.findall(text or ""))


def has_placeholder_marker(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)


def is_substantive(text: str) -> bool:
    """实质正文：非占位且中文字符数达标。"""
    return cjk_char_count(text) >= MIN_BODY_CJK_CHARS and not has_placeholder_marker(text)


def coverage(sections: list[dict], aligned_records: list[dict]) -> dict:
    """覆盖率。适用节点 = 对齐成功的 section（semantic_node_id 非空）。

    aligned_records: align.Aligner.align_sections() 输出转 dict，
    至少含 section_id / semantic_node_id。
    """
    text_by_sid = {str(s.get("section_id", "")): (s.get("proposal_text") or "") for s in sections}
    applicable_sids = [
        r["section_id"] for r in aligned_records if r.get("semantic_node_id")
    ]
    covered_sids = [
        sid for sid in applicable_sids if is_substantive(text_by_sid.get(sid, ""))
    ]
    uncovered = [
        r for r in aligned_records
        if r.get("semantic_node_id") and r["section_id"] not in set(covered_sids)
    ]
    applicable = len(applicable_sids)
    return {
        "applicable": applicable,
        "covered": len(covered_sids),
        "ratio": (len(covered_sids) / applicable) if applicable else None,
        "uncovered": [
            {
                "section_id": r["section_id"],
                "section_number": r.get("section_number", ""),
                "heading": r.get("heading", ""),
            }
            for r in uncovered
        ],
    }


def placeholder_counts(sections: list[dict]) -> dict:
    marker_count = 0
    section_count = 0
    for s in sections:
        text = s.get("proposal_text") or ""
        lowered = text.lower()
        hits = sum(lowered.count(marker.lower()) for marker in PLACEHOLDER_MARKERS)
        if hits:
            section_count += 1
            marker_count += hits
    return {"marker_count": marker_count, "section_count": section_count}


def leak_ratio(sections: list[dict], competitor_terms: list[str] | None) -> dict:
    """泄漏率：出现竞品词的节比例。无 StyleKit 竞品词表时返回未计算。"""
    if not competitor_terms:
        return {"computed": False, "section_leak_ratio": None, "leaked_sections": []}
    leaked = []
    terms = [t.lower() for t in competitor_terms if t]
    for s in sections:
        text = (s.get("proposal_text") or "").lower()
        if any(term in text for term in terms):
            leaked.append(str(s.get("section_id", "")))
    total = len(sections)
    return {
        "computed": True,
        "section_leak_ratio": (len(leaked) / total) if total else None,
        "leaked_sections": leaked,
    }


@dataclass(frozen=True)
class FactConflict:
    section_id: str
    fact_path: str
    detail: str


def fact_conflicts(
    sections: list[dict],
    study_definition: dict | None = None,
) -> list[FactConflict]:
    """事实冲突：正文与 StudyDefinition 矛盾。首版空实现，保留接口。"""
    _ = sections, study_definition
    return []


def duration_minutes(created_at: str | None, finished_at: str | None) -> dict:
    """由 job 的 created/finished 时间戳（ISO 8601）推全文生成墙钟时间。"""
    if not created_at or not finished_at:
        return {"computed": False, "minutes": None, "created_at": created_at, "finished_at": finished_at}
    from datetime import datetime

    def _parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    seconds = (_parse(finished_at) - _parse(created_at)).total_seconds()
    return {
        "computed": seconds >= 0,
        "minutes": round(seconds / 60.0, 1) if seconds >= 0 else None,
        "created_at": created_at,
        "finished_at": finished_at,
    }
