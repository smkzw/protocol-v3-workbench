from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")


def test_revision_progress_uses_persisted_job_message_and_percent() -> None:
    assert 'aria-label="AI候选生成进度"' in APP
    assert "revisionJobProgress.message" in APP
    assert "revisionJobProgress.step_total" in APP
    assert "revisionJobPercent" in APP
    assert "setOperationJob(map, op" in APP
    assert "progress: st.progress" in APP


def test_revision_progress_does_not_expose_internal_phase_as_primary_copy() -> None:
    assert "AI修订生成中：${st.progress.phase" not in APP
    assert ".revision-progress-track" in CSS
