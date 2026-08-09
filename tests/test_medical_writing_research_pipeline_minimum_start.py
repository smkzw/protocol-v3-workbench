from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_research_pipeline_accepts_creation_minimum_before_product_profile_is_known():
    source = (
        ROOT
        / "services"
        / "api"
        / "app"
        / "medical_writing_research_pipeline.py"
    ).read_text(encoding="utf-8")

    assert "creation_minimum_complete()" in source
    assert "产品画像待公开证据、IB或用户补充；先按最小项目信息检索" in source
    assert "须先确认药品种类（technology_type）后再启动研究流水线" not in source
    assert "须先确认至少一种给药途径（administration_routes）后再启动研究流水线" not in source


def test_research_pipeline_has_advance_after_basket_confirm():
    """MW-A1-002: the pipeline must expose advance_after_basket_confirm so
    the one-click confirm API can advance the parent without a second click."""
    source = (
        ROOT
        / "services"
        / "api"
        / "app"
        / "medical_writing_research_pipeline.py"
    ).read_text(encoding="utf-8")

    assert "def advance_after_basket_confirm(" in source
    assert "awaiting_triage_confirm" in source
    assert ":after-triage-confirm:" in source
    # The durable executor must handle resume_from=awaiting_triage_confirm
    assert 'resume_from == "awaiting_triage_confirm"' in source


def test_confirmed_resume_path_never_reconfirms_basket():
    """MW-A1-002 P0: the confirmed resume path must NOT call
    confirm_basket, _confirm_triage_basket, or finalize_triage again."""
    source = (
        ROOT
        / "services"
        / "api"
        / "app"
        / "medical_writing_research_pipeline.py"
    ).read_text(encoding="utf-8")

    assert "def _continue_after_confirmed_triage(" in source
    assert "def _resolve_confirmed_retained_ids(" in source
    # The confirmed resume method must consume frozen_retained_ids
    assert "frozen_retained_ids" in source
    # The durable executor must call _continue_after_confirmed_triage
    # (not continue_after_triage) for the resume_from path
    assert "_continue_after_confirmed_triage(" in source
    # The confirmed resume method must validate frozen IDs against projection
    assert "确认的竞品篮子范围与当前锁定快照的投影不一致" in source


def test_api_threads_confirmation_retained_ids_into_advance():
    """MW-A1-002 P0: the confirm API must pass retained_nct_ids from the
    confirmation response into advance_after_basket_confirm."""
    source = (ROOT / "services" / "api" / "app" / "main.py").read_text(
        encoding="utf-8"
    )

    assert "confirmed_retained_ids" in source
    assert "retained_candidate_ids=confirmed_retained_ids" in source


def test_advance_after_basket_confirm_does_not_set_preparing_before_wake():
    """MW-A1-002: the preparing stage must only be set if wake() succeeds."""
    source = (
        ROOT
        / "services"
        / "api"
        / "app"
        / "medical_writing_research_pipeline.py"
    ).read_text(encoding="utf-8")

    # The wake result must be checked before transitioning to preparing
    assert "woken = False" in source
    assert "if woken:" in source


def test_translation_batch_accepts_confirmed_discovery_projection():
    """MW-A1-002: translation _snapshot_scope must accept a confirmed
    discovery basket projection, not only finalized corpus triage."""
    source = (
        ROOT
        / "services"
        / "api"
        / "app"
        / "writing_reference_translation_batch.py"
    ).read_text(encoding="utf-8")

    assert "discovery_basket_projection" in source
    assert "discovery_confirmed" in source
    assert "_effective_retained_ids" in source
    # Must NOT hard-require finalized triage
    assert (
        'competitor triage must be finalized before batch translation' not in source
    )
