from pathlib import Path

from scripts.render_docx_visual_qc import build_fontconfig


def test_fontconfig_keeps_company_font_semantics_and_declares_cjk_fallbacks(tmp_path):
    font_directory = tmp_path / "fonts & fallback"
    font_directory.mkdir()
    xml = build_fontconfig([font_directory], tmp_path / "cache")

    assert "fonts &amp; fallback" in xml
    assert "<family>宋体</family>" in xml
    assert "<family>黑体</family>" in xml
    assert "<family>Noto Serif SC</family>" in xml
    assert "<family>Noto Sans SC</family>" in xml
    assert "<family>Songti SC</family>" in xml
    assert "<family>PingFang SC</family>" in xml
