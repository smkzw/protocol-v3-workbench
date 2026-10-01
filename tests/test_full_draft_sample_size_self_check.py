"""NEW-14/44 内容族③（R27 第3轮修订）反例：统计章样本量算术自洽校验。

现场（OAB）：生成链首次写出了统计数字，但 δ=1.5、SD=3.2、双侧α=0.05、
90%把握度声明每组60例——按 n≥2(z_α+z_β)²SD²/δ² 复算约需96例/组，60例
只兼容 SD≈2.5，三处一致地错且无任何校验。期望：校验器按声明参数复算，
不一致即判「样本量要素未齐」；参数缺失也判未齐；完全一致判自洽。
"""
from __future__ import annotations

from services.api.app.medical_writing_full_draft import (
    sample_size_consistency_check,
)

OAB_TEXT = (
    "样本量：基于主要终点（24小时排尿次数较基线变化）的组间差异 δ=1.5 次/24小时，"
    "标准差 SD=3.2，双侧 α=0.05，把握度 90%，估算每组需 60 例，共 180 例"
    "（考虑 20% 脱落率）。"
)

CONSISTENT_TEXT = OAB_TEXT.replace("每组需 60 例", "每组需 96 例").replace("共 180 例", "共 288 例")

MISSING_SD_TEXT = (
    "样本量：基于主要终点组间差异 δ=1.5 次/24小时，双侧 α=0.05，把握度 90%，"
    "估算每组需 60 例。"
)


def test_oab_declared_sample_size_is_flagged_inconsistent():
    result = sample_size_consistency_check(OAB_TEXT)
    assert result is not None
    assert result["status"] == "样本量要素未齐"
    assert result["declared_per_group"] == 60
    # 复算值：2×(1.959964+1.281552)²×3.2²/1.5² ≈ 95.6 → 96
    assert result["required_per_group"] == 96
    assert "不自洽" in result["detail"] or "不一致" in result["detail"]


def test_consistent_declared_size_passes():
    result = sample_size_consistency_check(CONSISTENT_TEXT)
    assert result is not None
    assert result["status"] == "自洽"
    assert result["required_per_group"] == 96


def test_missing_parameter_counts_as_not_ready():
    result = sample_size_consistency_check(MISSING_SD_TEXT)
    assert result is not None
    assert result["status"] == "样本量要素未齐"
    assert "SD" in result["detail"] or "标准差" in result["detail"]


def test_text_without_sample_size_claims_returns_none():
    assert sample_size_consistency_check("本章描述统计分析的一般原则。") is None
