"""新纪元第3轮修订：复测N2 + 第四步（NEW-28/29）反例先红（源契约钉）。

- 复测N2：工作副本已存在但初始保存未完成（尚无版本1）时，「创建工作
  副本」入口幂等不得'放行即终点'——必须标记待保存并指引『保存版本』
  完成初始化（消除与幂等继承死路同族的入口死路）。
- NEW-28：封面申办者不得回退硬编码公司名——从项目记录/信息包映射，
  无来源留白+待确认（导出上下文构建处）。
- NEW-29：内部锚点可回验化——溯源串不得把'§x.y'裸引用与'内部IB v\d'
  直出正文；导出禁语检查补这两族。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
MAIN = (ROOT / "services" / "api" / "app" / "main.py").read_text(encoding="utf-8")
EXPORTER = (
    ROOT / "services" / "api" / "app" / "medical_writing_document_exporter.py"
).read_text(encoding="utf-8")


def test_create_entry_completes_interrupted_initial_save() -> None:
    start = APP.index("const createWorkingCopy = () => {")
    body = APP[start: APP.index("const updateWorkingCopyDraft", start)]
    assert "workingCopyRevision < 1" in body, (
        "入口幂等不区分'已存在但初始保存未完成'——保存中断即死路。"
    )
    assert "setWorkingCopyDirty(true)" in body, "初始保存出路必须标记待保存。"
    assert "初始保存" in body, "必须给用户可执行的完成指引。"


def test_cover_sponsor_has_no_hardcoded_fallback() -> None:
    assert "_CMS_SPONSOR_NAME" not in EXPORTER or (
        "_CMS_SPONSOR_NAME" in EXPORTER
        and "sponsor = " in EXPORTER
        and "_CMS_SPONSOR_NAME" not in EXPORTER.split("sponsor = ")[1].split("\n")[0]
    ), "封面 sponsor 仍回退硬编码公司名（NEW-28）。"


def test_export_forbidden_phrases_cover_internal_anchors() -> None:
    for phrase in ("§", "内部IB v"):
        assert phrase in MAIN.split("_EXPORT_FORBIDDEN_PHRASES = (")[1].split(")\n")[0], (
            f"导出禁语表缺内部锚点族：{phrase}（NEW-29）。"
        )


if __name__ == "__main__":
    unittest.main()
