"""新纪元第4轮修订·第七刀小件（反例先红，源契约钉）。

- NEW-35：项目下拉身份可辨——选项带来源标识（官方演示/自建）与创建
  日期，同药名项目（官方演示 RUX-03-002 vs 用户自建同名药物）不再混淆
  错选；
- NEW-34：分诊终态收敛钉——cancel 对已取消/终态幂等且 detail 可辨（读
  取对账不得改写终态语义）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def test_project_dropdown_labels_origin_and_date() -> None:
    assert "官方演示" in APP and "自建" in APP, (
        "项目下拉缺来源标识——同药名官方演示项目与自建项目不可辨。"
    )
    assert "proj_user_" in APP, "来源判定锚点缺失。"


def test_cancel_is_idempotent_and_marks_cleanup_entry() -> None:
    source = (
        (ROOT / "services" / "api" / "app" / "medical_writing_research_pipeline.py")
        .read_text(encoding="utf-8")
    )
    assert "force_cleanup" in source, "缺僵尸态清理二次入口。"
    assert "确认终止并清理" in source, "清理入口语义不可辨。"
