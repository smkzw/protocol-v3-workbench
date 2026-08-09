from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")


def test_old_greenfield_template_is_the_only_upgrade_entry_surface():
    assert 'documentSession?.template_version === "greenfield_protocol_v0_1"' in APP
    assert "isLegacyGreenfieldTemplate &&" in APP
    assert "升级模板" in APP
    assert "不会立即修改文档" in APP


def test_upgrade_requires_preview_hash_and_both_explicit_acknowledgements():
    assert "expected_preview_sha256: preview.preview_sha256" in APP
    assert "acknowledge_consolidation: templateUpgradeConsolidationAccepted" in APP
    assert "acknowledge_approval_reset: templateUpgradeApprovalResetAccepted" in APP
    assert "请先逐项确认迁移边界" in APP


def test_upgrade_drawer_exposes_mapping_origin_target_and_processing_mode():
    assert "旧章节" in APP
    assert "内容版本" in APP
    assert "当前M11目标" in APP
    assert "工作副本 v${mapping.source_content_revision}" in APP
    assert "合并保留" in APP
    assert "直接保留" in APP


def test_immediate_rollback_is_visible_but_describes_its_guard():
    assert "恢复升级前版本" in APP
    assert "开始保存新工作副本后将不再允许直接恢复" in APP
    assert "/template-upgrade/rollback" in APP


def test_desktop_drawer_has_stable_dense_dimensions():
    assert ".writing-template-upgrade-drawer" in STYLES
    assert "width: min(1120px, 78vw)" in STYLES
    assert "table-layout: fixed" in STYLES
    assert ".writing-template-upgrade-table-wrap" in STYLES
