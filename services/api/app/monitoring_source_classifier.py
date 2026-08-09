from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Tuple


COMPARISON_NAME_MARKERS = ("comparison", "compare", "对比报告", "比较报告")
PROCESSED_NAME_MARKERS = (
    "处理后",
    "附量表",
)
RESTORED_NAME_MARKERS = ("自动还原", "已还原")
COMPARISON_SHEET_MARKERS = ("报告总结", "数据对比报告")
MIXED_SHEET_MARKERS = ("量表间评分比较", "量表间评分变化比较", "评分变化比较")
TECHNICAL_WARNING_PREFIXES = ("worksheet_dimension_reset:",)


@dataclass(frozen=True)
class MonitoringSourceClassification:
    source_class: str
    technical_status: str
    content_warnings: Tuple[str, ...]
    facts: Tuple[str, ...]
    baseline_eligible_after_confirmation: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_monitoring_listing(
    filename: str,
    sheets: Sequence[Any],
) -> MonitoringSourceClassification:
    display_name = Path(filename or "listing").name
    lowered_name = display_name.lower()
    sheet_names = tuple(str(sheet.sheet_name).strip() for sheet in sheets)
    warnings = sorted(
        {
            str(warning).strip()
            for sheet in sheets
            for warning in getattr(sheet, "parser_warnings", ())
            if str(warning).strip()
        }
    )
    total_rows = sum(len(getattr(sheet, "rows", ())) for sheet in sheets)
    facts = [
        f"filename={display_name}",
        f"sheet_count={len(sheets)}",
        f"row_count={total_rows}",
    ]

    if not sheets or total_rows == 0:
        return MonitoringSourceClassification(
            source_class="unknown_blocked",
            technical_status="failed",
            content_warnings=("文件未解析出可用 data listing 记录。",),
            facts=tuple(facts),
            baseline_eligible_after_confirmation=False,
        )

    comparison_columns = _sheets_with_manual_comparison_status(sheets)
    comparison_sheets = sorted(
        name for name in sheet_names if any(marker in name for marker in COMPARISON_SHEET_MARKERS)
    )
    mixed_sheets = sorted(
        name for name in sheet_names if any(marker in name for marker in MIXED_SHEET_MARKERS)
    )
    has_comparison_name = any(marker in lowered_name for marker in COMPARISON_NAME_MARKERS)
    has_processed_name = any(marker in display_name for marker in PROCESSED_NAME_MARKERS)
    has_restored_name = any(marker in display_name for marker in RESTORED_NAME_MARKERS)
    has_dimension_recovery = any(
        warning.startswith(TECHNICAL_WARNING_PREFIXES)
        for warning in warnings
    )

    if has_comparison_name or comparison_columns or comparison_sheets:
        facts.extend(
            [
                f"manual_status_sheets={len(comparison_columns)}",
                f"comparison_summary_sheets={','.join(comparison_sheets)}",
            ]
        )
        return MonitoringSourceClassification(
            source_class="comparison_workbook",
            technical_status="passed",
            content_warnings=(
                "检测到人工比较状态或比较汇总；系统只可重算差异，不得把来源比较结果当作原始事实。",
            ),
            facts=tuple(facts),
            baseline_eligible_after_confirmation=False,
        )

    if mixed_sheets:
        facts.append(f"derived_comparison_sheets={','.join(mixed_sheets)}")
        return MonitoringSourceClassification(
            source_class="mixed_monitoring_workbook",
            technical_status="passed",
            content_warnings=(
                "工作簿混有人工量表比较或派生结果表；需隔离原始域后方可继续使用。",
            ),
            facts=tuple(facts),
            baseline_eligible_after_confirmation=False,
        )

    if has_dimension_recovery:
        facts.append("worksheet_dimension_metadata_recovered=true")
        return MonitoringSourceClassification(
            source_class="raw_snapshot_with_format_defect",
            technical_status="passed",
            content_warnings=(
                "原工作簿声明的工作区范围不正确；系统已按底层工作表 XML 读取，但需保存父文件及守恒验证。",
            ),
            facts=tuple(facts),
            baseline_eligible_after_confirmation=False,
        )

    if has_restored_name:
        return MonitoringSourceClassification(
            source_class="restored_transitional",
            technical_status="passed",
            content_warnings=(
                "文件名显示其经过还原；缺少父文件、转换版本和守恒记录时不能作为正式全量基线。",
            ),
            facts=tuple(facts),
            baseline_eligible_after_confirmation=False,
        )

    if has_processed_name:
        return MonitoringSourceClassification(
            source_class="processed_full_snapshot",
            technical_status="passed",
            content_warnings=(
                "文件名显示其经过处理；需补充父文件 SHA、处理规则和结构/内容守恒记录。",
            ),
            facts=tuple(facts),
            baseline_eligible_after_confirmation=False,
        )

    return MonitoringSourceClassification(
        source_class="raw_full_snapshot_candidate",
        technical_status="passed",
        content_warnings=tuple(warnings),
        facts=tuple(facts),
        baseline_eligible_after_confirmation=True,
    )


def _sheets_with_manual_comparison_status(sheets: Iterable[Any]) -> list[str]:
    matches = []
    for sheet in sheets:
        rows = list(getattr(sheet, "rows", ()) or ())
        if not rows:
            continue
        headers = {str(key).strip() for key in rows[0]}
        if "状态" not in headers:
            continue
        sample_values = {
            str(row.get("状态") or "").strip().lower()
            for row in rows[:50]
            if isinstance(row, Mapping)
        }
        if sample_values & {"new", "changed", "unchanged", "removed", "新增", "变化", "无变化"}:
            matches.append(str(sheet.sheet_name).strip())
    return sorted(matches)
