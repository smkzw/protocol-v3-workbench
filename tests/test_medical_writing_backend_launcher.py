from pathlib import Path


WORKBENCH_ROOT = Path(__file__).resolve().parents[1]


def test_backend_launcher_does_not_pin_or_require_a_supplier() -> None:
    launcher = (
        WORKBENCH_ROOT / "runtime/start_medical_writing_backend_8911.zsh"
    ).read_text(encoding="utf-8")

    assert "DEEPSEEK_API_KEY" not in launcher
    assert "WORKBENCH_AI_PROVIDER=" not in launcher
    assert "WORKBENCH_AI_MODEL=" not in launcher
    assert "api.deepseek.com" not in launcher
    assert "exec env -u PYTHONPATH" in launcher
    assert "uvicorn services.api.app.main:app" in launcher
