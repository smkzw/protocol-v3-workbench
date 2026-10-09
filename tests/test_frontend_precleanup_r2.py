"""前端预清理批 r2（用户指令20261003b 复验 + 20261008a 尺）——工程化语言
清扫与换行卫生的反例先红测试。

背景：r1 预清理被 owner 裁定'小修小补'（fe_cleanup_r1 仅 4 张截图）；
本批把浏览器实测到的三处工程化语言直出与两处不和谐换行钉进契约。

反例（2026-10-08 真机截图/探针实测，1728×1031 视口）：
- 项目总看板阻断面板直出 'HTTP 503 · code=monitoring_principal_unavailable'
  （App.jsx MonitoringReadUnavailable 的 info.technical 行）；
- 写作平台顶部横幅直出构建哈希 'api-ec7573a032e0a0bc…(5301)'
  （runtimeReadiness.js warning 拼接）；
- 顶栏 AI 状态胶囊直出内部模型 ID 'AI 设置 · mtplx ·
  mtplx-flash-next-optimized-speed'（App.jsx compact 胶囊）；
- 写作页保存状态直出内部术语'绿地候选基线'（greenfield 工程词）；
- 1440 视口下顶栏指标胶囊中文断词换行（'未读决/策''高风险开/放'，
  fe_cleanup_r1/before_dashboard_1440.png 实证）；侧栏导航
  '安全信号与PV协/同''证据调研与方案/设计'断词换行。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
READINESS = (
    ROOT / "frontend" / "src" / "runtimeReadiness.js"
).read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")


# ── ③ 工程化语言：错误码/内部 ID/工程术语不得直出 ─────────────────────────


def test_monitoring_block_panel_does_not_render_raw_error_code() -> None:
    """读取阻断面板的人话文案下不得再直出 'HTTP 503 · code=xxx' 技术行。

    data-read-code 等机器属性保留（测试/支持排障用），但视觉文本不直出。
    """
    panel_start = APP.index("function MonitoringReadUnavailable(")
    panel_end = APP.index("const writingSections", panel_start)
    panel = APP[panel_start:panel_end]
    assert "{info.technical && <small>{info.technical}</small>}" not in panel, (
        "阻断面板把原始错误码行直出给医学用户；技术细节应收进悬浮提示，"
        "不能作为可见文本。"
    )


def test_raw_monitoring_error_toast_does_not_append_technical_line() -> None:
    """setRawMonitoringError 不再把 '（HTTP 503 · code=xxx）' 拼进人话提示。"""
    assert "（${info.technical}）" not in APP, (
        "原始错误串拼接进用户提示；错误码不得直出。"
    )


def test_build_drift_warning_hides_build_hashes() -> None:
    """构建漂移横幅给处置指引，不展示构建指纹哈希与内部端口。

    既有 vitest 契约要求 warning 含'构建不一致'（runtimeReadiness.test.jsx），
    本契约追加：正文不得内插 expectedBackendBuildId/backend_build_id 哈希，
    指引不再带 '(5301)' 端口号。
    """
    assert "构建不一致" in READINESS
    assert "${expectation.expectedBackendBuildId}" not in READINESS, (
        "横幅正文内插构建哈希（api-xxxx）——内部 ID 不得直出。"
    )
    assert "${payload.backend_build_id" not in READINESS
    assert "(5301)" not in READINESS, "横幅指引直出内部端口号。"


def test_ai_status_pill_hides_raw_provider_and_model_ids() -> None:
    """顶栏 AI 胶囊对全部用户可见，不得直出 'mtplx · mtplx-flash-…' 内部 ID。

    'AI 设置' 文案保留（test_frontend_ai_role_settings_contract 钉住）；
    provider/model 细节收进悬浮提示（title）与设置弹窗。
    """
    assert "AI 设置" in APP
    pill_start = APP.index("function AiGatewayPanel(")
    pill_end = APP.index("function AiSettingsDialog", pill_start) if "function AiSettingsDialog" in APP[pill_start:] else len(APP)
    pill = APP[pill_start:pill_end]
    assert "`AI 设置 · ${providerLabel} · ${modelLabel}`" not in pill, (
        "胶囊可见文本内插内部 provider/model ID。"
    )
    assert "`${providerLabel} · ${modelLabel}`" not in pill, (
        "非压缩态胶囊同样内插内部 ID；细节应进 title/设置弹窗。"
    )


def test_greenfield_jargon_not_shown_in_writing_ui() -> None:
    """写作页用户可见文本不得出现工程术语'绿地'（greenfield）。

    改用'新建方案'人话表述；后端测试夹具（tests/*greenfield*）不在此列。
    """
    assert "绿地候选基线" not in APP
    assert "从当前绿地候选章节" not in APP


# ── ④ 换行卫生：胶囊禁断词、导航平衡断行、长词兜底 ─────────────────────────


def test_metric_pills_never_wrap_mid_word() -> None:
    """顶栏指标胶囊（未读决策/高风险开放…）44px 高度内禁止文字换行。

    反例：1440 视口 '未读决/策'、'高风险开/放' 断词换行（r1 截图实证）。
    """
    metric_block = STYLES.split(".metric {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in metric_block, (
        ".metric 缺 white-space: nowrap；胶囊标签在窄视口会断词换行。"
    )


def test_sidebar_nav_labels_wrap_balanced() -> None:
    """侧栏导航长标签（证据调研与方案设计/安全信号与PV协同）应平衡断行，
    不在词素中间截断（'…方案/设计''…PV协/同'）。"""
    nav_rules = ""
    for chunk in STYLES.split(".nav-item")[1:]:
        nav_rules += chunk[:400]
    assert "text-wrap: balance" in nav_rules, (
        ".nav-item span 缺 text-wrap: balance；长导航名在窄侧栏断词生硬。"
    )


def test_page_has_long_token_wrap_guard() -> None:
    """主内容区对超长英文串（哈希/URL）有 overflow-wrap 兜底，不撑破布局。"""
    page_block = STYLES.split(".page {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap" in page_block


def test_writing_toolbar_buttons_never_wrap_mid_word() -> None:
    """写作工具条按钮（创建工作副本/版式估算/一键冻结…）禁断词换行。

    反例：1440 视口按钮内文字断成三行（'创建/工作副/本''版/式估算'）；
    容器本就 overflow-x 滚动，按钮应保持完整。
    """
    block = STYLES.split(".working-copy-actions button {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in block, (
        "写作工具条按钮缺 nowrap；窄视口按钮标签断词成多行。"
    )
