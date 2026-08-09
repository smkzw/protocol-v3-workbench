"""Regression: closed-to-open drawer transition must trigger workspace refresh.

r11 blocker: after basket confirmation the drawer was reopened but no
/references/workspace request was issued because the panel's load effect only
fires on [projectId, snapshotId, lockedIndication, lockedPhase] changes.
The repair adds a monotonically increasing refreshSignal prop from the drawer
that increments on every false->true open transition, and the panel reacts to
it with a fresh workspace fetch.  Rendering must distinguish loading from
loaded-empty so the user never sees a misleading "0项" during refresh.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAWER = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-writing"
    / "AuthoringCompetitorDrawer.jsx"
)
PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "writing-reference"
    / "WritingReferencePanel.jsx"
)


def test_drawer_increments_refresh_signal_on_open_transition() -> None:
    source = DRAWER.read_text(encoding="utf-8")

    # The drawer tracks previous open state and increments on false->true.
    assert "useRef(open)" in source, "drawer must track previous open state"
    assert "prevOpenRef.current" in source
    assert "setRefreshSignal" in source
    assert "open && !prevOpenRef.current" in source, (
        "signal must increment only on closed-to-open transition"
    )
    # Signal is passed to the panel.
    assert "refreshSignal={refreshSignal}" in source


def test_panel_accepts_refresh_signal_and_triggers_workspace_fetch() -> None:
    source = PANEL.read_text(encoding="utf-8")

    # Prop declared with default 0.
    assert "refreshSignal = 0," in source
    # Reopening refreshes both the workspace and the latest durable triage run.
    refresh_effect = source.split("if (refreshSignal > 0) {", 1)[1].split(
        "}, [refreshSignal]);", 1
    )[0]
    assert "refreshWorkspace();" in refresh_effect
    assert (
        "recoverLatestTriageRun({ silentNotFound: true, background: true });"
        in refresh_effect
    )
    # Effect dependency is the signal itself.
    assert "[refreshSignal]" in source


def test_locked_search_facts_do_not_reset_recovered_triage_state() -> None:
    source = PANEL.read_text(encoding="utf-8")

    # Project/snapshot identity changes own the destructive reset.
    reset_effect = source.split(
        "activeProjectRef.current = projectId;", 1
    )[1].split("}, [projectId, snapshotId]);", 1)[0]
    assert "setAiTriageRun(null);" in reset_effect
    assert "setAiTriageSelections({});" in reset_effect
    assert "setIndication(lockedIndication);" not in reset_effect
    assert "setPhase(lockedPhase" not in reset_effect
    assert (
        "}, [projectId, snapshotId, lockedIndication, lockedPhase]);"
        not in source
    )

    # Asynchronous fact normalization only updates display/search fields.
    assert (
        "setIndication(lockedIndication);\n"
        '    setPhase(lockedPhase || "PHASE2");\n'
        "  }, [lockedIndication, lockedPhase]);"
        in source
    )


def test_review_ready_ai_classifications_are_projected_into_candidate_list() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert 'aiTriageRun?.run?.status === "review_ready"' in source
    assert "aiTriageSelections[candidate.nct_id] || candidate.relevance_status" in source
    assert "const displayStatus = candidateDisplayStatus(candidate);" in source
    assert '<ReferenceTag value={displayStatus}' in source


def test_ai_triage_copy_uses_batch_review_not_individual_confirmation() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "AI先完成全量分类；您整体浏览，必要时展开修改，再一次确认锁定。" in source
    assert "AI分诊已完成。请整体浏览AI建议" in source
    assert "医学经理已整体核对AI分诊结果" in source


def test_panel_workspace_fetch_retains_stale_guard() -> None:
    source = PANEL.read_text(encoding="utf-8")

    # Generation guard prevents stale responses from overwriting current state.
    assert "generation !== refreshGenerationRef.current" in source
    # Snapshot mismatch guard rejects wrong-snapshot payloads.
    assert "payload.snapshot?.snapshot_id !== snapshotId" in source


def test_candidate_list_distinguishes_loading_from_loaded_empty() -> None:
    source = PANEL.read_text(encoding="utf-8")

    # Loading state: shown while workspace is unresolved.
    assert "loading && !workspace" in source
    assert "正在加载候选研究…" in source
    # Loaded-empty state: only after workspace loaded with zero candidates.
    assert "!loading && workspace && !candidates.length" in source
    assert 'data-state="loaded-empty"' in source
    # Count indicator suppresses misleading "0项" during load.
    assert 'data-testid="candidate-count"' in source
    assert "加载中…" in source


def test_genuine_empty_state_preserved_after_load() -> None:
    source = PANEL.read_text(encoding="utf-8")

    # The original empty message is retained for the true empty case.
    assert "尚未检索公开竞品研究。" in source
    # It is gated behind workspace being loaded (not during refresh).
    assert "!loading && workspace && !candidates.length" in source
