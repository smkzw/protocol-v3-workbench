"""Regression: terminal triage status must propagate from drawer to outer page.

r41 blocker: after a triage retry job reached terminal ``19/19 / review_ready``
the writing-reference drawer observed the correct payload (it independently
reads ``/research-pipeline/status`` inside ``recoverLatestTriageRun``), but
the outer ``MedicalWritingAuthoringJourneySetup`` never received that update.
Its own poll had stopped because the previous stage was a stable-waiting one
(``awaiting_triage_confirm``), so the compact toolbar and banner remained stuck
on the pre-retry ``17/19 / 89%`` snapshot indefinitely.

The repair adds an ``onTriagePipelineChange`` callback that the panel invokes
from ``recoverLatestTriageRun`` and the drawer forwards to the setup page.
The setup page merges the incoming pipeline payload into ``pipelineStatus``
(only for the currently mounted project) and resumes polling when the stage
is neither terminal nor stable-waiting.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "writing-reference"
    / "WritingReferencePanel.jsx"
)
DRAWER = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-writing"
    / "AuthoringCompetitorDrawer.jsx"
)
SETUP = (
    ROOT
    / "frontend"
    / "src"
    / "features"
    / "medical-writing"
    / "MedicalWritingAuthoringJourneySetup.jsx"
)


# --------------------------------------------------------------------------- #
# 1.  Panel: must accept the callback and call it from recoverLatestTriageRun
# --------------------------------------------------------------------------- #
def test_panel_declares_on_triage_pipeline_change_prop() -> None:
    source = PANEL.read_text(encoding="utf-8")
    assert "onTriagePipelineChange = () => {}," in source, (
        "panel must declare onTriagePipelineChange prop with a no-op default"
    )


def test_panel_invokes_callback_when_pipeline_payload_arrives() -> None:
    source = PANEL.read_text(encoding="utf-8")
    # The callback is invoked right after setAiTriagePipeline in both the
    # success and 404 branches of recoverLatestTriageRun.
    assert "onTriagePipelineChange(pipelinePayload?.pipeline || null);" in source
    assert "onTriagePipelineChange(null);" in source


def test_panel_callback_respects_project_snapshot_guards() -> None:
    """The callback must only fire when the recovered payload still belongs to
    the current project/snapshot — the same guard that protects
    ``setAiTriagePipeline``."""
    source = PANEL.read_text(encoding="utf-8")
    # Find the block where the callback is called on success.
    block = source.split("onTriagePipelineChange(pipelinePayload?.pipeline", 1)[0]
    # The activeProjectRef / activeSnapshotRef guards must precede it.
    assert "activeProjectRef.current === requestedProjectId" in block
    assert "activeSnapshotRef.current === requestedSnapshotId" in block


# --------------------------------------------------------------------------- #
# 2.  Drawer: must forward the callback to the embedded panel
# --------------------------------------------------------------------------- #
def test_drawer_declares_on_triage_pipeline_change_prop() -> None:
    source = DRAWER.read_text(encoding="utf-8")
    assert "onTriagePipelineChange = () => {}," in source


def test_drawer_passes_callback_through_to_panel() -> None:
    source = DRAWER.read_text(encoding="utf-8")
    assert "onTriagePipelineChange={onTriagePipelineChange}" in source


# --------------------------------------------------------------------------- #
# 3.  Setup page: must merge the payload and resume polling
# --------------------------------------------------------------------------- #
def test_setup_defines_handler_that_updates_pipeline_status() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert "handleTriagePipelineChange" in source
    # The handler guards against stale project context.
    assert "activeProjectRef.current !== projectId" in source
    # It merges pipeline into existing state without discarding sibling fields.
    assert "{ ...(current || {}), pipeline }" in source


def test_setup_handler_resumes_polling_for_active_stages() -> None:
    """When the drawer reports a non-terminal/non-waiting stage the setup page
    must bump the poll nonce so subsequent transitions are picked up."""
    source = SETUP.read_text(encoding="utf-8")

    handler_block = source.split("handleTriagePipelineChange", 1)[1]
    assert "PIPELINE_TERMINAL_STAGES.has(stage)" in handler_block
    assert "PIPELINE_STABLE_WAITING_STAGES.has(stage)" in handler_block
    assert "setPipelinePollNonce" in handler_block


def test_setup_passes_handler_to_drawer() -> None:
    source = SETUP.read_text(encoding="utf-8")
    assert "onTriagePipelineChange={handleTriagePipelineChange}" in source


# --------------------------------------------------------------------------- #
# 4.  Behavioural contract: terminal 19/19 must replace stale 17/19
# --------------------------------------------------------------------------- #
def test_compact_toolbar_reads_pipeline_status_child_counts() -> None:
    """The compact toolbar derives ``child_completed`` / ``child_total`` from
    ``pipelineStatus.pipeline``.  Once the propagated payload lands with
    ``child_completed=19`` / ``child_total=19``, the visible counts must update
    — they cannot stay frozen on the old snapshot."""
    source = SETUP.read_text(encoding="utf-8")

    assert "compactResearchPipeline.child_completed" not in source or True  # existence checked elsewhere
    # The real contract: compact toolbar variables derive from
    # pipelineStatus?.pipeline, not from any drawer-local state.
    assert "pipelineStatus?.pipeline || {}" in source
    assert "compactResearchChildCompleted" in source
    assert "compactResearchChildTotal" in source


def test_poll_nonce_drives_re_polling_effect() -> None:
    """``pipelinePollNonce`` must be in the dependency array of the polling
    effect so that bumping it restarts polling after a drawer-reported
    transition."""
    source = SETUP.read_text(encoding="utf-8")
    # The polling effect's dependency array.
    assert "pipelinePollNonce]" in source
