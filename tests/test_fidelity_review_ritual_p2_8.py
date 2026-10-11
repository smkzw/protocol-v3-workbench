"""新纪元第1轮末修订（P2-8/NEW-5残根）：忠实度仪式瘦身——从'手写'降为
'核对改签'（20261004a 人工负担量方向）。

owner 方向：高置信自动放行、只拦真正可疑项、人工介入压缩为批量确认。
批量确认已落地（旧纪元R2）；本批收残根：
T1 阻断码默认全选：打开单段确认面板时全部忠实度阻断码预勾选，作者只需
   取消不符项（此前必须逐项手点全部勾选）；
T2 核对意见预填机器草稿结论：通过=『已对照原文逐项核对…未发现偏差』；
   有残留码=逐码点名+『已核实为真实残留而非机器误报，残留可接受』的可
   编辑草稿——作者改签后提交，不再从空白手写；
T3 结论仍为可编辑 textarea（行为契约保持：准入门槛条件不变——残留须
   全选后才可准入）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = (
    ROOT / "frontend" / "src" / "features" / "writing-reference"
    / "WritingReferencePanel.jsx"
).read_text(encoding="utf-8")


def test_failure_codes_default_to_all_checked() -> None:
    """T1：选择译文时阻断码预填全集（勾选=取消不符项的改签语义）。"""
    assert "setAcknowledgedFidelityCodes([...codes])" in PANEL, (
        "阻断码仍默认空集（逐项手点仪式未瘦身）；应预填全部阻断码供改签。"
    )


def test_review_comment_prefilled_with_machine_draft_conclusion() -> None:
    """T2：核对意见预填机器草稿结论（通过/残留两形态），不再是空白。"""
    assert "draftAuthorReviewComment" in PANEL
    assert "未发现偏差" in PANEL
    assert "真实残留而非机器误报" in PANEL
    assert "setReviewComment(draftAuthorReviewComment(selectedTranslation))" in PANEL


def test_review_textarea_stays_editable_and_gates_unchanged() -> None:
    """T3：textarea 仍绑定 reviewComment 可编辑；准入门槛条件保持。"""
    assert (
        'value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} '
        'placeholder="对照原文记录医学含义、数字、时间窗及否定关系的核对结论。"'
    ) in PANEL
    assert (
        "acknowledgedFidelityCodes.length !== (selectedTranslation.fidelity_failure_codes || []).length"
    ) in PANEL
