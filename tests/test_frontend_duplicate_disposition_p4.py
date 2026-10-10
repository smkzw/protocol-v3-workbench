"""新纪元第4轮修订·第三刀：前端采纳面板接逐节重复处置（反例先红）。

现场（深度分析·第3轮）：后端已落逐节处置契约（duplicate_dispositions 参数
+ FullDraftDuplicateSectionsError 结构化载荷），但前端未接线——采纳请求体
仅 confirmed_section_ids（App.jsx:10807），界面用户无法逐节处置重复，
后端契约空转。

契约（红先修后，源契约钉）：
T1 采纳请求体携带 duplicate_dispositions；
T2 存在重复对处置状态（面板数据源）与三选一处置函数（跳过/仍要采纳/
   重生成）；
T3 采纳失败路径解析结构化重复对（code=full_draft_duplicate_sections）
   并进入处置面板（展示节号+标题+共享片段长度，禁内部 section_id 直出）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
MAIN = (ROOT / "services" / "api" / "app" / "main.py").read_text(encoding="utf-8")


def test_adopt_request_carries_duplicate_dispositions() -> None:
    adopt_start = APP.index("const adoptFullDraft = () => {")
    body = APP[adopt_start: APP.index("const toggleFullDraftSectionConfirmation", adopt_start)]
    assert "duplicate_dispositions" in body, (
        "采纳请求体未携带逐节重复处置表——后端契约空转。"
    )


def test_duplicate_disposition_state_and_three_choices_exist() -> None:
    assert "FullDraftDuplicateDispositions" in APP or (
        "fullDraftDuplicateDispositions" in APP
    ), "缺重复处置状态（面板数据源）。"
    for action in ("skip", "adopt_with_gap", "regenerate"):
        assert f'"{action}"' in APP, f"缺三选一处置值：{action}。"


def test_duplicate_error_parses_structured_pairs() -> None:
    assert "full_draft_duplicate_sections" in APP, (
        "采纳失败路径未解析结构化重复对（code=full_draft_duplicate_sections）。"
    )
    assert "duplicate_pairs" in APP, "重复对载荷未进前端。"
    assert "shared_fragment_chars" in APP, "共享片段长度未进前端展示。"


def test_backend_route_returns_structured_duplicate_payload() -> None:
    assert "FullDraftDuplicateSectionsError" in MAIN, (
        "后端采纳路由未捕获结构化重复异常（409 detail 仍是裸字符串）。"
    )
