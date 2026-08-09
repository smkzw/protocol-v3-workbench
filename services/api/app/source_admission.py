from __future__ import annotations

from typing import Iterable

from packages.contracts.workbench_contracts import (
    SourceAdmissionState,
    SourceValidationBinding,
)


class SourceAdmissionRequired(ValueError):
    def __init__(self, state: SourceAdmissionState):
        self.state = state
        super().__init__("当前来源尚未完成内容核验或确认沿用，不能执行该晋级动作。")


def require_source_admission(state: SourceAdmissionState) -> list[SourceValidationBinding]:
    if not state.ready_for_use:
        raise SourceAdmissionRequired(state)
    return bindings_from_admission(state)


def unavailable_source_admission(
    project_id: str,
    module: str,
    scope_id: str,
) -> SourceAdmissionState:
    return SourceAdmissionState(
        project_id=project_id,
        module=module,
        scope_id=scope_id,
        missing_source_roles=["来源准入服务"],
        ready_for_use=False,
    )


def bindings_from_admission(state: SourceAdmissionState) -> list[SourceValidationBinding]:
    return [
        SourceValidationBinding.model_validate(
            source.model_dump(
                include={
                    "source_role",
                    "source_role_code",
                    "source_entry_id",
                    "validation_id",
                    "revision",
                    "validator_version",
                    "technical_status",
                    "content_status",
                    "use_status",
                }
            )
        )
        for source in state.sources
    ]


def source_bindings_are_current(
    recorded: Iterable[SourceValidationBinding],
    current_state: SourceAdmissionState,
) -> bool:
    if not current_state.ready_for_use:
        return False
    return _binding_keys(recorded) == _binding_keys(bindings_from_admission(current_state))


def _binding_keys(bindings: Iterable[SourceValidationBinding]) -> set[tuple[object, ...]]:
    return {
        (
            item.source_role_code,
            item.source_entry_id,
            item.validation_id,
            item.revision,
            item.validator_version,
            item.technical_status,
            item.content_status,
            item.use_status,
        )
        for item in bindings
    }
