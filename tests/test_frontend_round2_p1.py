"""新纪元第2轮修订 P1 前端四件（NEW-7/NEW-4/NEW-8/NEW-6）反例先红。

- NEW-7：构建漂移指引残留越权文案（'请重启…'）——测试者无服务重启权限
  （红线3），指引改为'服务同步中，请稍后刷新或联系集成人'；
- NEW-4：全局项目选择器刷新即丢——sessionStorage 已落盘但加载路径从不
  认领（App.jsx 加载效果把 fallback 传空串），'本会话内会被记住'承诺不
  成立；修=加载后把本会话持久值作为 fallback 传入解析器（解析器自带
  存在性校验，非本会话/不在列表则不认领，保持 NEW-P0-27 反误入守卫）；
- NEW-8：研究分期下拉缺 Ib期/IIa期/IIb期（基准方案 MY009 即 Ib/IIa，
  每轮必撞）；两处新建项目表单分支同步；
- NEW-6：工作副本状态条保存徽章 nowrap 溢出遮挡相邻按钮列——status-main
  子元素加 overflow 裁剪，按钮列抬 z-index 兜底。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
READINESS = (
    ROOT / "frontend" / "src" / "runtimeReadiness.js"
).read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
SYNOPSIS_INTAKE = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "MedicalWritingSynopsisProjectIntake.jsx"
).read_text(encoding="utf-8")
JOURNEY_SETUP = (
    ROOT / "frontend" / "src" / "features" / "medical-writing"
    / "MedicalWritingAuthoringJourneySetup.jsx"
).read_text(encoding="utf-8")


def test_drift_hint_does_not_command_user_to_restart() -> None:
    assert "请重启" not in READINESS, (
        "漂移指引指挥用户重启服务——测试者无此权限（越权提示）。"
    )
    assert "服务同步中" in READINESS
    assert "联系集成人" in READINESS


def test_project_load_adopts_session_persisted_selection_with_validation() -> None:
    load_region = APP[APP.index("setActiveProjectId((current) => {"):]
    load_region = load_region[: load_region.index("setProjectsLoaded(true);")]
    assert "readPersistedMonitoringProjectId()" in load_region, (
        "项目列表加载效果未把本会话持久选择作为 fallback 传入解析器——"
        "刷新即丢选择，'本会话内会被记住'承诺不成立。"
    )


def test_phase_options_include_ib_iia_iib_everywhere() -> None:
    """三处分期选项源（新建项目表单/梗概导入/写作旅程第一步）同步补齐
    Ib期/IIa期/IIb期——基准方案 MY009 即 Ib/IIa，每轮必撞。"""
    option_sets = APP.split("<label>研究分期<select")[1:]
    assert option_sets, "新建项目表单缺分期下拉"
    for index, chunk in enumerate(option_sets, start=1):
        options = chunk[: chunk.index("</select>")]
        for phase in ("Ib期", "IIa期", "IIb期"):
            assert f'value="{phase}"' in options, (
                f"新建项目分期下拉第{index}分支缺 {phase}。"
            )
    for name, source in (
        ("梗概导入", SYNOPSIS_INTAKE),
        ("写作旅程第一步", JOURNEY_SETUP),
    ):
        for phase in ("Ib期", "IIa期", "IIb期"):
            assert f'"{phase}"' in source, f"{name}的分期选项缺 {phase}。"


def test_status_bar_badge_cannot_cover_action_buttons() -> None:
    save_state_block = STYLES.split(
        ".working-copy-status-main .working-copy-save-state {", 1
    )[1].split("}", 1)[0]
    assert "overflow: hidden" in save_state_block, (
        "保存徽章 nowrap 溢出无裁剪——会盖住相邻按钮列。"
    )
    assert "text-overflow: ellipsis" in save_state_block
    actions_block = STYLES.split(".working-copy-actions {", 1)[1].split("}", 1)[0]
    assert "z-index" in actions_block and "position: relative" in actions_block, (
        "按钮列未抬层——溢出徽章仍可能拦截指针。"
    )


if __name__ == "__main__":
    unittest.main()
