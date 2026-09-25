from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from services.api.app.chapter_translation_pipeline import (
    FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
    FLASH_PLANNING_PROMPT_VERSION,
    PLANNER_CONTRACT_TRANSITION_VERSION,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
)
from services.api.app.writing_reference_upper_layer_execution import (
    DEFAULT_UPPER_LAYER_MODEL,
    ESCALATED_UPPER_LAYER_MODEL,
    UpperLayerAdapterRequest,
    UpperLayerAdapterResult,
    UpperLayerExecutionRequest,
    UpperLayerTransientError,
    WritingReferenceUpperLayerExecutionService,
)


NOW = datetime(2026, 7, 25, 2, 0, tzinfo=timezone.utc)
TARGET_MAP_SHA256 = "a" * 64


class ManualClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class ScriptedAdapter:
    def __init__(
        self,
        model: str,
        scripts: dict[str, list[Any]],
        calls: list[UpperLayerAdapterRequest],
    ) -> None:
        self.model = model
        self.scripts = scripts
        self.calls = calls

    def invoke(self, request: UpperLayerAdapterRequest) -> UpperLayerAdapterResult:
        assert request.requested_model == self.model
        self.calls.append(request)
        action = self.scripts[self.model].pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class ScriptedAdapterFactory:
    def __init__(self, **scripts: list[Any]) -> None:
        self.scripts = scripts
        self.calls: list[UpperLayerAdapterRequest] = []

    def __call__(self, model: str) -> ScriptedAdapter:
        if model not in self.scripts:
            raise AssertionError(f"unexpected model route: {model}")
        return ScriptedAdapter(model, self.scripts, self.calls)

    def models_called(self) -> list[str]:
        return [item.requested_model for item in self.calls]


def planning_request(
    *,
    idempotency_key: str = "upper-layer-request-001",
) -> UpperLayerExecutionRequest:
    return UpperLayerExecutionRequest(
        project_id="project_001",
        owner_type="translation_batch_item",
        owner_id="item_001",
        batch_id="batch_001",
        item_id="item_001",
        artifact_id="artifact_001",
        extraction_revision="extract_r2",
        plan_id="",
        chapter_id="",
        stage="document_planning",
        prompt_version="document_planning_v1",
        prompt="请仅按冻结来源形成连续、完整的章节计划。",
        deployment_profile="medical-writing-upper-layer-v1",
        input_payload={"source_span_ids": ["span_001"], "source_text": "source"},
        idempotency_key=idempotency_key,
    )


def integration_request(
    *,
    idempotency_key: str = "upper-layer-request-qc-001",
) -> UpperLayerExecutionRequest:
    return UpperLayerExecutionRequest(
        project_id="project_001",
        owner_type="translation_batch_item",
        owner_id="item_001",
        batch_id="batch_001",
        item_id="item_001",
        artifact_id="artifact_001",
        extraction_revision="extract_r2",
        plan_id="plan_001",
        chapter_id="chapter_001",
        stage="post_hy_mt2_integration_qc",
        prompt_version="integration_qc_v1",
        prompt="只检查并整合结构，不得改写 Hy-MT2 target map。",
        deployment_profile="medical-writing-upper-layer-v1",
        input_payload={
            "hy_mt2_target_map": [{"unit_id": "u1", "target_text": "目标译文"}]
        },
        idempotency_key=idempotency_key,
        hy_mt2_target_map_sha256=TARGET_MAP_SHA256,
    )


@pytest.fixture
def repository(tmp_path: Path) -> WritingReferenceRepository:
    return WritingReferenceRepository(tmp_path / "writing_reference.sqlite3")


def success(
    model: str,
    *,
    output: Any = None,
    target_map_sha256: str = "",
) -> UpperLayerAdapterResult:
    return UpperLayerAdapterResult(
        response_model=model,
        status="succeeded",
        output_payload=output or {"result": model},
        preserved_hy_mt2_target_map_sha256=target_map_sha256,
    )


def degraded(
    *,
    output: Any = None,
    target_map_sha256: str = "",
) -> UpperLayerAdapterResult:
    return UpperLayerAdapterResult(
        response_model=DEFAULT_UPPER_LAYER_MODEL,
        status="completed_degraded",
        output_payload=output or {"result": "deterministic_fallback"},
        failure_code="flash_structure_invalid_fallback_used",
        preserved_hy_mt2_target_map_sha256=target_map_sha256,
    )


def escalatable() -> UpperLayerAdapterResult:
    return UpperLayerAdapterResult(
        response_model=DEFAULT_UPPER_LAYER_MODEL,
        status="failed_escalatable",
        failure_code="flash_structure_invalid_no_valid_fallback",
    )


def planner_structural_failure(code: str) -> UpperLayerAdapterResult:
    return UpperLayerAdapterResult(
        response_model=DEFAULT_UPPER_LAYER_MODEL,
        status="failed_escalatable",
        failure_code=code,
    )


def terminal_failure() -> UpperLayerAdapterResult:
    """A non-retryable, non-escalatable failure: persists as one failed run."""
    return UpperLayerAdapterResult(
        response_model=DEFAULT_UPPER_LAYER_MODEL,
        status="failed_terminal",
        failure_code="product_ai_provider_transient",
    )


def test_capabilities_are_server_owned_and_corpus_support_is_honest() -> None:
    capabilities = WritingReferenceUpperLayerExecutionService.capabilities()

    planning = capabilities.upper_layer_stages["document_planning"]
    corpus = capabilities.upper_layer_stages["corpus_selection_support"]
    assert planning.default_model == DEFAULT_UPPER_LAYER_MODEL
    assert planning.escalation_model == ESCALATED_UPPER_LAYER_MODEL
    assert planning.automatic_escalation_supported is True
    assert corpus.status == "not_implemented"
    assert corpus.default_model is None
    assert corpus.escalation_model is None


def test_flash_success_is_idempotent_hash_verified_and_survives_restart(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{DEFAULT_UPPER_LAYER_MODEL: [success(DEFAULT_UPPER_LAYER_MODEL)]}
    )
    service = WritingReferenceUpperLayerExecutionService(repository, factory)
    request = planning_request()

    first = service.execute(request)
    replay = service.execute(request)

    assert first.flash_run.status == "succeeded"
    assert first.latest_run.stage_run_id == replay.latest_run.stage_run_id
    assert first.selected_output == {"result": DEFAULT_UPPER_LAYER_MODEL}
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL]
    assert repository.upper_layer_escalation_for_source(
        request.project_id,
        first.flash_run.stage_run_id,
    ) is None

    restarted = WritingReferenceRepository(repository.db_path)
    restored = restarted.upper_layer_stage_run(
        request.project_id,
        first.flash_run.stage_run_id,
    )
    execution = restarted.upper_layer_stage_run_execution(
        request.project_id,
        first.flash_run.stage_run_id,
    )
    assert restored.model_dump() == first.flash_run.model_dump()
    assert execution["input_payload"] == request.input_payload
    assert execution["output_payload"] == first.selected_output
    assert len(execution["execution_fingerprint"]) == 64
    assert restarted.health_report()["schema_version"] == 8


def test_record_advances_stale_failed_pointer_to_fresh_result(
    repository: WritingReferenceRepository,
) -> None:
    """A pointer left at a FAILED run is not a result (86fe7ea): recording a
    fresh run must advance the pointer instead of raising, so a retry round's
    real result (even completed_degraded) is kept and the next replay
    converges without another model call."""
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                terminal_failure(),
                success(DEFAULT_UPPER_LAYER_MODEL),
            ]
        }
    )
    service = WritingReferenceUpperLayerExecutionService(repository, factory)
    request = planning_request()
    scoped_key = service._route_scoped_idempotency_key(request.idempotency_key)

    failed = service.execute(request)
    assert failed.selected_output is None

    recovered = service.execute(request)

    assert recovered.selected_run.status == "succeeded"
    with repository._connect() as connection:
        pointer = connection.execute(
            """
            SELECT result_id FROM writing_reference_idempotency
            WHERE tenant_id='kangzhe_local' AND project_id=?
              AND operation='execute_upper_layer_stage' AND idempotency_key=?
            """,
            (request.project_id, scoped_key),
        ).fetchone()
        audit = connection.execute(
            """
            SELECT detail_json FROM writing_reference_audit_chain
            WHERE tenant_id='kangzhe_local' AND project_id=?
              AND event_type='upper_layer_idempotency_pointer_advanced'
            """,
            (request.project_id,),
        ).fetchall()
    assert pointer["result_id"] == recovered.latest_run.stage_run_id
    assert len(audit) == 1
    assert json.loads(audit[0]["detail_json"])["previous_result_id"] == (
        failed.latest_run.stage_run_id
    )

    # The advanced pointer makes the next execution a true replay.
    replayed = service.execute(request)
    assert replayed.selected_run.stage_run_id == recovered.latest_run.stage_run_id
    assert factory.models_called() == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
    ]


def test_record_still_rejects_changed_result_for_succeeded_run(
    repository: WritingReferenceRepository,
) -> None:
    """A pointer at a SUCCEEDED run stays a strict result: recording a
    different result_id must keep raising the conflict and must not mutate
    the pointer (concurrent double-success guard)."""
    factory = ScriptedAdapterFactory(
        **{DEFAULT_UPPER_LAYER_MODEL: [success(DEFAULT_UPPER_LAYER_MODEL)]}
    )
    service = WritingReferenceUpperLayerExecutionService(repository, factory)
    request = planning_request()
    scoped_key = service._route_scoped_idempotency_key(request.idempotency_key)
    first = service.execute(request)
    assert first.selected_run.status == "succeeded"

    with repository._connect() as connection:
        row = connection.execute(
            """
            SELECT result_id, request_hash FROM writing_reference_idempotency
            WHERE tenant_id='kangzhe_local' AND project_id=?
              AND operation='execute_upper_layer_stage' AND idempotency_key=?
            """,
            (request.project_id, scoped_key),
        ).fetchone()
    assert row["result_id"] == first.latest_run.stage_run_id

    with pytest.raises(WritingReferenceConflictError):
        repository.record_upper_layer_execution_idempotency(
            request.project_id,
            idempotency_key=scoped_key,
            request_hash=str(row["request_hash"]),
            result_id="wref_ulrun_" + "0" * 24,
        )

    with repository._connect() as connection:
        after = connection.execute(
            """
            SELECT result_id FROM writing_reference_idempotency
            WHERE tenant_id='kangzhe_local' AND project_id=?
              AND operation='execute_upper_layer_stage' AND idempotency_key=?
            """,
            (request.project_id, scoped_key),
        ).fetchone()
    assert after["result_id"] == first.latest_run.stage_run_id


def test_flash_transient_errors_retry_flash_only(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout"),
                UpperLayerTransientError("http_429"),
                success(DEFAULT_UPPER_LAYER_MODEL),
            ]
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=3,
    ).execute(planning_request())

    assert outcome.flash_run.status == "succeeded"
    assert outcome.flash_run.provider_call_count == 3
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL] * 3
    assert outcome.escalation is None


def test_persisted_planner_retries_structure_once_on_same_model_and_stage_run(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                planner_structural_failure("planning_chapters_missing"),
                success(
                    DEFAULT_UPPER_LAYER_MODEL,
                    output={"result": "corrected_flash_plan"},
                ),
            ]
        }
    )
    request = planning_request()
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(request)

    assert outcome.selected_output == {"result": "corrected_flash_plan"}
    assert outcome.escalation is None
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL] * 2
    assert [call.stage_run_id for call in factory.calls] == [
        outcome.flash_run.stage_run_id,
        outcome.flash_run.stage_run_id,
    ]
    assert [call.planner_attempt for call in factory.calls] == [1, 2]
    assert factory.calls[0].retry_instruction == ""
    assert factory.calls[1].retry_instruction
    assert factory.calls[0].input_hash == factory.calls[1].input_hash
    assert factory.calls[0].input_payload == factory.calls[1].input_payload
    assert outcome.flash_run.provider_call_count == 2
    assert outcome.flash_run.planner_attempt_count == 2
    assert [
        attempt.retry_kind
        for attempt in outcome.flash_run.provider_call_attempts
    ] == ["initial", "structural_correction"]
    assert [
        attempt.status for attempt in outcome.flash_run.provider_call_attempts
    ] == ["failed_escalatable", "succeeded"]
    assert (
        outcome.flash_run.provider_call_attempts[1]
        .correction_instruction_sha256
    )

    restored = WritingReferenceRepository(
        repository.db_path
    ).upper_layer_stage_run(
        request.project_id,
        outcome.flash_run.stage_run_id,
    )
    assert restored.provider_call_count == 2
    assert restored.planner_attempt_count == 2
    assert restored.provider_call_attempts == outcome.flash_run.provider_call_attempts


def test_persisted_planner_escalates_only_after_corrective_flash_retry_fails(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                planner_structural_failure("planner_range_gap"),
                planner_structural_failure("planner_range_overlap"),
            ],
            ESCALATED_UPPER_LAYER_MODEL: [
                success(
                    ESCALATED_UPPER_LAYER_MODEL,
                    output={"result": "pro_plan"},
                )
            ],
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(planning_request())

    assert factory.models_called() == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
        ESCALATED_UPPER_LAYER_MODEL,
    ]
    assert outcome.flash_run.provider_call_count == 2
    assert outcome.flash_run.planner_attempt_count == 2
    assert outcome.flash_run.failure_code == "planner_range_overlap"
    assert outcome.latest_run.provider_call_count == 1
    assert outcome.latest_run.planner_attempt_count == 1
    assert outcome.escalation is not None
    assert outcome.escalation.trigger_code == "planner_range_overlap"
    assert outcome.selected_output == {"result": "pro_plan"}


def test_retry_generation_creates_one_new_parented_stage_and_replays_it(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout"),
                success(
                    DEFAULT_UPPER_LAYER_MODEL,
                    output={"result": "retry_generation_plan"},
                ),
            ]
        }
    )
    first_request = planning_request(
        idempotency_key="retry-generation-initial-001"
    )
    first = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=1,
    ).execute(first_request)
    assert first.flash_run.status == "failed_retryable"

    retry_request = UpperLayerExecutionRequest(
        **{
            **first_request.__dict__,
            "idempotency_key": "retry-generation-second-001",
            "retry_generation": 2,
            "retry_parent_stage_run_id": first.flash_run.stage_run_id,
        }
    )
    service = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(repository.db_path),
        factory,
        flash_max_attempts=1,
    )
    recovered = service.execute(retry_request)
    replay = service.execute(retry_request)

    assert recovered.flash_run.stage_run_id != first.flash_run.stage_run_id
    assert recovered.flash_run.retry_generation == 2
    assert (
        recovered.flash_run.retry_parent_stage_run_id
        == first.flash_run.stage_run_id
    )
    assert recovered.selected_output == {"result": "retry_generation_plan"}
    assert replay.flash_run.stage_run_id == recovered.flash_run.stage_run_id
    assert factory.models_called() == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
    ]
    with repository._connect() as connection:
        run_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM writing_reference_upper_layer_stage_runs
            WHERE project_id=? AND stage='document_planning'
            """,
            (first_request.project_id,),
        ).fetchone()[0]
        detail = connection.execute(
            """
            SELECT detail_json
            FROM writing_reference_audit_chain
            WHERE project_id=? AND event_type='upper_layer_stage_run_saved'
              AND target_id=?
            """,
            (
                first_request.project_id,
                recovered.flash_run.stage_run_id,
            ),
        ).fetchone()[0]
    assert run_count == 2
    assert '"retry_generation":2' in detail
    assert first.flash_run.stage_run_id in detail
    for forbidden in (
        "source_text",
        "system_prompt",
        "retry_instruction",
        "provider_output",
    ):
        assert forbidden not in detail


def test_allowlisted_contract_supersession_creates_fresh_v3_root_and_replays(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout"),
                success(
                    DEFAULT_UPPER_LAYER_MODEL,
                    output={"result": "v3_plan"},
                ),
            ]
        }
    )
    source_request = UpperLayerExecutionRequest(
        **{
            **planning_request(
                idempotency_key="contract-supersession-v2-source"
            ).__dict__,
            "prompt_version": FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            "prompt": "冻结的 v2 章节规划提示。",
        }
    )
    source = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=1,
    ).execute(source_request)
    assert source.flash_run.status == "failed_retryable"
    source_execution = repository.upper_layer_stage_run_execution(
        source_request.project_id,
        source.flash_run.stage_run_id,
    )

    target_request = UpperLayerExecutionRequest(
        **{
            **source_request.__dict__,
            "prompt_version": FLASH_PLANNING_PROMPT_VERSION,
            "prompt": "冻结的 v3 服务端章节身份规划提示。",
            "idempotency_key": "contract-supersession-v3-target",
            "contract_supersession_generation": 2,
            "contract_supersession_transition_version": (
                PLANNER_CONTRACT_TRANSITION_VERSION
            ),
            "contract_supersession_source_stage_run_id": (
                source.flash_run.stage_run_id
            ),
            "contract_supersession_source_execution_fingerprint": (
                source_execution["execution_fingerprint"]
            ),
            "contract_supersession_source_prompt_version": (
                FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
            ),
            "contract_supersession_target_prompt_version": (
                FLASH_PLANNING_PROMPT_VERSION
            ),
        }
    )
    restarted = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(repository.db_path),
        factory,
        flash_max_attempts=1,
    )
    target = restarted.execute(target_request)
    replay = restarted.execute(target_request)

    assert target.flash_run.stage_run_id != source.flash_run.stage_run_id
    assert target.flash_run.retry_generation == 0
    assert target.flash_run.retry_parent_stage_run_id == ""
    assert target.flash_run.parent_stage_run_id == ""
    assert target.flash_run.contract_supersession_generation == 2
    assert (
        target.flash_run.contract_supersession_source_stage_run_id
        == source.flash_run.stage_run_id
    )
    assert target.selected_output == {"result": "v3_plan"}
    assert replay.flash_run.stage_run_id == target.flash_run.stage_run_id
    assert factory.models_called() == [
        DEFAULT_UPPER_LAYER_MODEL,
        DEFAULT_UPPER_LAYER_MODEL,
    ]
    with repository._connect() as connection:
        rows = connection.execute(
            """
            SELECT detail_json
            FROM writing_reference_audit_chain
            WHERE project_id=?
              AND event_type='upper_layer_contract_supersession_recorded'
            """,
            (source_request.project_id,),
        ).fetchall()
    assert len(rows) == 1
    detail = rows[0]["detail_json"]
    assert source.flash_run.stage_run_id in detail
    assert FLASH_PLANNING_PREVIOUS_PROMPT_VERSION in detail
    assert FLASH_PLANNING_PROMPT_VERSION in detail
    for forbidden in (
        "source_text",
        "prompt_text",
        "provider_output",
        "translated_text",
    ):
        assert forbidden not in detail


def test_cross_contract_ordinary_retry_and_ambiguous_supersession_fail_closed(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout")
            ]
        }
    )
    source_request = UpperLayerExecutionRequest(
        **{
            **planning_request(
                idempotency_key="cross-contract-v2-source"
            ).__dict__,
            "prompt_version": FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            "prompt": "冻结的 v2 章节规划提示。",
        }
    )
    service = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=1,
    )
    source = service.execute(source_request)
    source_execution = repository.upper_layer_stage_run_execution(
        source_request.project_id,
        source.flash_run.stage_run_id,
    )
    ordinary_cross_contract = UpperLayerExecutionRequest(
        **{
            **source_request.__dict__,
            "prompt_version": FLASH_PLANNING_PROMPT_VERSION,
            "prompt": "冻结的 v3 服务端章节身份规划提示。",
            "idempotency_key": "cross-contract-ordinary-child",
            "retry_generation": 2,
            "retry_parent_stage_run_id": source.flash_run.stage_run_id,
        }
    )
    with pytest.raises(ValueError, match="retry parent"):
        service.execute(ordinary_cross_contract)

    ambiguous = UpperLayerExecutionRequest(
        **{
            **ordinary_cross_contract.__dict__,
            "idempotency_key": "cross-contract-ambiguous-child",
            "contract_supersession_generation": 2,
            "contract_supersession_transition_version": (
                PLANNER_CONTRACT_TRANSITION_VERSION
            ),
            "contract_supersession_source_stage_run_id": (
                source.flash_run.stage_run_id
            ),
            "contract_supersession_source_execution_fingerprint": (
                source_execution["execution_fingerprint"]
            ),
            "contract_supersession_source_prompt_version": (
                FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
            ),
            "contract_supersession_target_prompt_version": (
                FLASH_PLANNING_PROMPT_VERSION
            ),
        }
    )
    with pytest.raises(
        ValueError,
        match="ordinary retry and contract supersession",
    ):
        service.execute(ambiguous)
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL]
    with repository._connect() as connection:
        run_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM writing_reference_upper_layer_stage_runs
            WHERE project_id=? AND stage='document_planning'
            """,
            (source_request.project_id,),
        ).fetchone()[0]
        idempotency_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM writing_reference_idempotency
            WHERE project_id=? AND operation='execute_upper_layer_stage'
            """,
            (source_request.project_id,),
        ).fetchone()[0]
    assert run_count == 1
    assert idempotency_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_id": "item_other", "item_id": "item_other"},
        {"artifact_id": "artifact_other"},
        {"extraction_revision": "extract_other"},
        {"prompt": "changed frozen prompt"},
        {"input_payload": {"source_text": "changed"}},
    ],
    ids=["owner", "artifact", "extraction", "prompt", "input"],
)
def test_retry_parent_must_match_frozen_stage_lineage(
    repository: WritingReferenceRepository,
    changes: dict[str, Any],
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout")
            ]
        }
    )
    first_request = planning_request(
        idempotency_key="retry-parent-lineage-initial"
    )
    parent = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=1,
    ).execute(first_request).flash_run
    retry_request = UpperLayerExecutionRequest(
        **{
            **first_request.__dict__,
            **changes,
            "idempotency_key": "retry-parent-lineage-second",
            "retry_generation": 2,
            "retry_parent_stage_run_id": parent.stage_run_id,
        }
    )

    with pytest.raises(ValueError, match="retry parent"):
        WritingReferenceUpperLayerExecutionService(
            repository,
            factory,
            flash_max_attempts=1,
        ).execute(retry_request)
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL]


def test_retry_generation_pro_child_keeps_retry_and_escalation_lineage(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout"),
                planner_structural_failure("planner_range_gap"),
                planner_structural_failure("planner_range_overlap"),
            ],
            ESCALATED_UPPER_LAYER_MODEL: [
                success(
                    ESCALATED_UPPER_LAYER_MODEL,
                    output={"result": "retry_generation_pro_plan"},
                )
            ],
        }
    )
    initial_request = planning_request(
        idempotency_key="retry-generation-pro-initial"
    )
    parent = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=1,
    ).execute(initial_request).flash_run
    retry_request = UpperLayerExecutionRequest(
        **{
            **initial_request.__dict__,
            "idempotency_key": "retry-generation-pro-second",
            "retry_generation": 2,
            "retry_parent_stage_run_id": parent.stage_run_id,
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=1,
    ).execute(retry_request)

    assert outcome.escalation is not None
    assert outcome.latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert outcome.latest_run.retry_generation == 2
    assert (
        outcome.latest_run.retry_parent_stage_run_id
        == parent.stage_run_id
    )
    assert (
        outcome.latest_run.parent_stage_run_id
        == outcome.flash_run.stage_run_id
    )
    assert outcome.latest_run.escalation_id == outcome.escalation.escalation_id
    assert outcome.selected_output == {
        "result": "retry_generation_pro_plan"
    }


def test_successful_stage_cannot_be_used_as_retry_parent(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                success(DEFAULT_UPPER_LAYER_MODEL)
            ]
        }
    )
    first_request = planning_request(
        idempotency_key="successful-retry-parent-initial"
    )
    parent = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(first_request).flash_run
    retry_request = UpperLayerExecutionRequest(
        **{
            **first_request.__dict__,
            "idempotency_key": "successful-retry-parent-second",
            "retry_generation": 2,
            "retry_parent_stage_run_id": parent.stage_run_id,
        }
    )

    with pytest.raises(ValueError, match="failed stage run"):
        WritingReferenceUpperLayerExecutionService(
            repository,
            factory,
        ).execute(retry_request)
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL]


def test_planner_final_ineligible_second_failure_never_invokes_pro(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                planner_structural_failure("planner_range_gap"),
                planner_structural_failure(
                    "planning_segment_manifest_missing"
                ),
            ],
            ESCALATED_UPPER_LAYER_MODEL: [
                success(ESCALATED_UPPER_LAYER_MODEL)
            ],
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(planning_request())

    assert outcome.flash_run.planner_attempt_count == 2
    assert (
        outcome.flash_run.failure_code
        == "planning_segment_manifest_missing"
    )
    assert outcome.escalation is None
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL] * 2


def test_exhausted_flash_transient_failure_never_upgrades_to_pro(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout"),
                UpperLayerTransientError("http_503"),
            ]
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=2,
    ).execute(planning_request())

    assert outcome.flash_run.status == "failed_retryable"
    assert outcome.flash_run.failure_code == "http_503"
    assert factory.models_called() == [DEFAULT_UPPER_LAYER_MODEL] * 2
    assert outcome.escalation is None


@pytest.mark.parametrize(
    "flash_result",
    [
        escalatable(),
        degraded(target_map_sha256=TARGET_MAP_SHA256),
    ],
    ids=["failed_escalatable", "completed_degraded"],
)
def test_post_hy_status_trigger_auto_creates_exactly_one_pro_child(
    repository: WritingReferenceRepository,
    flash_result: UpperLayerAdapterResult,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [flash_result],
            ESCALATED_UPPER_LAYER_MODEL: [
                success(
                    ESCALATED_UPPER_LAYER_MODEL,
                    output={"result": "pro"},
                    target_map_sha256=TARGET_MAP_SHA256,
                )
            ],
        }
    )
    service = WritingReferenceUpperLayerExecutionService(repository, factory)
    request = integration_request()

    first = service.execute(request)
    replay = service.execute(request)
    replay_with_another_key = service.execute(
        integration_request(idempotency_key="upper-layer-request-qc-002")
    )

    assert first.escalation is not None
    assert first.escalation.status == "completed"
    assert first.latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert first.latest_run.parent_stage_run_id == first.flash_run.stage_run_id
    assert first.latest_run.escalation_id == first.escalation.escalation_id
    assert first.latest_run.stage_run_id == first.escalation.target_stage_run_id
    assert first.selected_output == {"result": "pro"}
    assert replay.latest_run.stage_run_id == first.latest_run.stage_run_id
    assert (
        replay_with_another_key.latest_run.stage_run_id
        == first.latest_run.stage_run_id
    )
    assert factory.models_called() == [
        DEFAULT_UPPER_LAYER_MODEL,
        ESCALATED_UPPER_LAYER_MODEL,
    ]
    with repository._connect() as connection:
        escalation_count = connection.execute(
            "SELECT COUNT(*) FROM writing_reference_upper_layer_escalations"
        ).fetchone()[0]
        pro_count = connection.execute(
            """
            SELECT COUNT(*) FROM writing_reference_upper_layer_stage_runs
            WHERE requested_model='deepseek-v4-pro'
            """
        ).fetchone()[0]
    assert escalation_count == 1
    assert pro_count == 1


def test_pro_transient_failure_is_not_automatically_retried(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [escalatable()],
            ESCALATED_UPPER_LAYER_MODEL: [
                UpperLayerTransientError("provider_timeout")
            ],
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
        flash_max_attempts=3,
    ).execute(integration_request())

    assert outcome.latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert outcome.latest_run.status == "failed_retryable"
    assert outcome.escalation is not None
    assert outcome.escalation.status == "failed_retryable"
    assert factory.models_called() == [
        DEFAULT_UPPER_LAYER_MODEL,
        ESCALATED_UPPER_LAYER_MODEL,
    ]
    assert (
        WritingReferenceUpperLayerExecutionService(
            WritingReferenceRepository(repository.db_path),
            ScriptedAdapterFactory(
                **{
                    ESCALATED_UPPER_LAYER_MODEL: [
                        success(ESCALATED_UPPER_LAYER_MODEL)
                    ]
                }
            ),
        ).resume_pending_escalations(project_id="project_001")
        == []
    )


def test_failed_pro_preserves_usable_degraded_flash_output(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                degraded(
                    output={"result": "deterministic_fallback"},
                    target_map_sha256=TARGET_MAP_SHA256,
                )
            ],
            ESCALATED_UPPER_LAYER_MODEL: [
                UpperLayerAdapterResult(
                    response_model=ESCALATED_UPPER_LAYER_MODEL,
                    status="failed_terminal",
                    failure_code="pro_schema_invalid",
                )
            ],
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(integration_request())

    assert outcome.latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert outcome.latest_run.status == "failed_terminal"
    assert outcome.escalation is not None
    assert outcome.escalation.status == "failed_terminal"
    assert outcome.selected_run.stage_run_id == outcome.flash_run.stage_run_id
    assert outcome.selected_output == {"result": "deterministic_fallback"}


def test_post_hy_qc_rejects_target_map_mutation_and_never_upgrades(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                success(
                    DEFAULT_UPPER_LAYER_MODEL,
                    output={"integrated_text": "被改写的正文"},
                    target_map_sha256="b" * 64,
                )
            ]
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(integration_request())

    assert outcome.flash_run.status == "failed_terminal"
    assert outcome.flash_run.failure_code == "hy_mt2_target_map_changed"
    assert outcome.flash_run.output_hash == ""
    assert outcome.selected_output is None
    assert outcome.escalation is None


def test_post_hy_degraded_path_escalates_without_changing_target_map(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [
                degraded(
                    output={"integrated_text": "目标译文"},
                    target_map_sha256=TARGET_MAP_SHA256,
                )
            ],
            ESCALATED_UPPER_LAYER_MODEL: [
                success(
                    ESCALATED_UPPER_LAYER_MODEL,
                    output={"integrated_text": "目标译文", "qc": "passed"},
                    target_map_sha256=TARGET_MAP_SHA256,
                )
            ],
        }
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(integration_request())

    assert outcome.latest_run.status == "succeeded"
    assert outcome.latest_run.requested_model == ESCALATED_UPPER_LAYER_MODEL
    assert outcome.selected_output["integrated_text"] == "目标译文"
    assert all(
        call.hy_mt2_target_map_sha256 == TARGET_MAP_SHA256
        for call in factory.calls
    )


def test_process_interruption_during_pro_is_recovered_after_lease_expiry(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "writing_reference.sqlite3"
    clock = ManualClock()
    first_repository = WritingReferenceRepository(db_path)
    interrupted_factory = ScriptedAdapterFactory(
        **{
            DEFAULT_UPPER_LAYER_MODEL: [escalatable()],
            ESCALATED_UPPER_LAYER_MODEL: [KeyboardInterrupt()],
        }
    )
    first_service = WritingReferenceUpperLayerExecutionService(
        first_repository,
        interrupted_factory,
        clock=clock,
        escalation_lease_seconds=60,
    )
    with pytest.raises(KeyboardInterrupt):
        first_service.execute(integration_request())

    with first_repository._connect() as connection:
        row = connection.execute(
            """
            SELECT status, target_stage_run_id
            FROM writing_reference_upper_layer_escalations
            """
        ).fetchone()
    assert row["status"] == "running"
    assert (
        first_repository.optional_upper_layer_stage_run(
            "project_001",
            row["target_stage_run_id"],
        )
        is None
    )
    concurrent_factory = ScriptedAdapterFactory()
    pending = WritingReferenceUpperLayerExecutionService(
        WritingReferenceRepository(db_path),
        concurrent_factory,
        clock=clock,
        escalation_lease_seconds=60,
    ).execute(integration_request())
    assert pending.escalation is not None
    assert pending.escalation.status == "running"
    assert concurrent_factory.calls == []
    with first_repository._connect() as connection:
        idempotency_count = connection.execute(
            """
            SELECT COUNT(*) FROM writing_reference_idempotency
            WHERE operation='execute_upper_layer_stage'
            """
        ).fetchone()[0]
    assert idempotency_count == 0

    clock.advance(61)
    restarted_repository = WritingReferenceRepository(db_path)
    recovery_factory = ScriptedAdapterFactory(
        **{
                ESCALATED_UPPER_LAYER_MODEL: [
                    success(
                        ESCALATED_UPPER_LAYER_MODEL,
                        output={"result": "recovered"},
                        target_map_sha256=TARGET_MAP_SHA256,
                    )
                ]
            }
        )
    recovered = WritingReferenceUpperLayerExecutionService(
        restarted_repository,
        recovery_factory,
        clock=clock,
        escalation_lease_seconds=60,
    ).resume_pending_escalations(project_id="project_001")

    assert len(recovered) == 1
    assert recovered[0].latest_run.status == "succeeded"
    assert recovered[0].selected_output == {"result": "recovered"}
    assert recovered[0].escalation is not None
    assert recovered[0].escalation.status == "completed"
    assert recovery_factory.models_called() == [ESCALATED_UPPER_LAYER_MODEL]


def test_client_cannot_supply_model_or_provider(
    repository: WritingReferenceRepository,
) -> None:
    payload = planning_request().__dict__.copy()
    payload["model"] = ESCALATED_UPPER_LAYER_MODEL
    with pytest.raises(TypeError):
        UpperLayerExecutionRequest(**payload)

    corpus = planning_request()
    corpus = UpperLayerExecutionRequest(
        **{
            **corpus.__dict__,
            "stage": "corpus_selection_support",
            "idempotency_key": "corpus-selection-request-001",
        }
    )
    factory = ScriptedAdapterFactory()
    service = WritingReferenceUpperLayerExecutionService(repository, factory)
    with pytest.raises(NotImplementedError, match="no product model invocation"):
        service.execute(corpus)
    assert factory.calls == []


def test_idempotency_key_reuse_with_different_request_fails(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{DEFAULT_UPPER_LAYER_MODEL: [success(DEFAULT_UPPER_LAYER_MODEL)]}
    )
    service = WritingReferenceUpperLayerExecutionService(repository, factory)
    first = planning_request(idempotency_key="same-key-request")
    service.execute(first)
    changed = UpperLayerExecutionRequest(
        **{
            **first.__dict__,
            "prompt": "changed prompt",
        }
    )

    with pytest.raises(
        WritingReferenceConflictError,
        match="idempotency key reused",
    ):
        service.execute(changed)


def test_upper_layer_stage_runs_are_immutable(
    repository: WritingReferenceRepository,
) -> None:
    factory = ScriptedAdapterFactory(
        **{DEFAULT_UPPER_LAYER_MODEL: [success(DEFAULT_UPPER_LAYER_MODEL)]}
    )
    outcome = WritingReferenceUpperLayerExecutionService(
        repository,
        factory,
    ).execute(planning_request())

    with sqlite3.connect(repository.db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """
                UPDATE writing_reference_upper_layer_stage_runs
                SET status='failed_terminal'
                WHERE stage_run_id=?
                """,
                (outcome.flash_run.stage_run_id,),
            )


def test_v4_repository_is_additively_migrated_to_v8(tmp_path: Path) -> None:
    db_path = tmp_path / "writing_reference.sqlite3"
    initial = WritingReferenceRepository(db_path)
    assert initial.health_report()["schema_version"] == 8
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN (5, 6, 7, 8)"
        )
        connection.execute("DROP INDEX idx_wref_extractions_latest")
        connection.execute("DROP INDEX idx_wref_source_spans_artifact_revision")
        connection.execute("DROP INDEX idx_wref_documents_snapshot")
        connection.execute("DROP TABLE writing_reference_upper_layer_escalations")
        connection.execute("DROP TABLE writing_reference_upper_layer_stage_runs")
        connection.execute(
            "CREATE TABLE migration_preservation_marker(value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO migration_preservation_marker(value) VALUES ('preserved')"
        )

    migrated = WritingReferenceRepository(db_path)
    assert migrated.health_report()["schema_version"] == 8
    with migrated._connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'writing_reference_upper_layer_%'
                """
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='index' AND name IN (
                    'idx_wref_extractions_latest',
                    'idx_wref_source_spans_artifact_revision',
                    'idx_wref_documents_snapshot'
                )
                """
            ).fetchall()
        }
        marker = connection.execute(
            "SELECT value FROM migration_preservation_marker"
        ).fetchone()[0]
    assert tables == {
        "writing_reference_upper_layer_stage_runs",
        "writing_reference_upper_layer_escalations",
    }
    assert indexes == {
        "idx_wref_extractions_latest",
        "idx_wref_source_spans_artifact_revision",
        "idx_wref_documents_snapshot",
    }
    assert marker == "preserved"
