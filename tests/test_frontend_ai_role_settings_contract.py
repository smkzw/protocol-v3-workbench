from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def test_four_ai_roles_use_openai_compatible_connection_fields() -> None:
    assert "全系统 AI 角色" in APP
    assert "Base URL" in APP
    assert "https://provider.example.com/v1" in APP
    assert "填写 OpenAI 兼容格式的 API Base URL" in APP
    assert "API Key" in APP
    assert "保存角色配置" in APP


def test_non_specialized_ocr_has_real_visual_probe_action() -> None:
    assert "/api/ai-gateway/roles/ocr/probe-visual" in APP
    assert "正在发送真实图像并验证文字识别能力" in APP
    assert "验证视觉能力" in APP


def test_global_role_settings_entry_is_available_before_project_creation() -> None:
    empty_start = APP.index("function EmptyProjectOverview(")
    empty_end = APP.index("function AppShell(", empty_start)
    empty_overview = APP[empty_start:empty_end]
    assert "<AiGatewayPanel" in empty_overview
    assert "compact" in empty_overview
    assert "AI 设置" in APP


def test_selecting_a_connection_switches_provider_and_model_atomically() -> None:
    start = APP.index("const chooseProfile = (profileId) =>")
    end = APP.index("const saveRoleConfiguration", start)
    choose_profile = APP[start:end]
    assert "role_model: profile.model" in choose_profile
    assert "role_model: role?.model || profile.model" not in choose_profile
