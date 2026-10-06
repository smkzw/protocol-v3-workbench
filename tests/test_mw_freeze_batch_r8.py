"""R8 片X-5（P0-03）：一键冻结全部待冻章节（freeze-batch）。

现场（七轮规格原样重述）：终稿导出前须逐章点『冻结当前版本』——22章
方案要点22次按钮+22次确认，正式运作时的人工负担量不可接受
（20261004a 检验方向）。契约：
- 批量端点对 freeze-readiness 中 reason_code∈{section_not_frozen,
  freeze_invalidated} 的章节逐章冻结（其余缺口跳过并留原因）；
- 单章版本冲突不中断批次：该章计入 failures，其余照常冻结；
- 幂等：同批重复提交已冻结章节为 no-op（frozen 空、skipped 指明已冻结）；
- 审计语义与单章冻结一致（作者冻结记录逐章留档）。
"""

from __future__ import annotations

import pytest

from packages.contracts.workbench_contracts.models import (
    MedicalWritingSectionFreezeBatchRequest,
)
from tests.test_medical_writing_author_freeze_backend import (
    DocumentService,
    PROJECT_A,
    author_freeze_runtime,
    _save,
    _section,
)


@pytest.fixture
def runtime(author_freeze_runtime):
    yield author_freeze_runtime


def _batch(repository, *, reason="医学作者确认全部待冻章节当前保存版本已定稿。", key="batch-freeze-r8"):
    return repository.freeze_current_versions_batch(
        PROJECT_A,
        MedicalWritingSectionFreezeBatchRequest(
            reason=reason,
            actor="medical_manager",
            idempotency_key=key,
        ),
    )


def test_batch_freezes_all_pending_sections_and_readiness_goes_ready(runtime) -> None:
    _, documents, _, _, repository = runtime
    section = _section(documents, PROJECT_A)
    _save(repository, documents, PROJECT_A)

    result = _batch(repository)

    assert [section.section_id] == result.frozen_section_ids
    assert result.failures == []
    readiness = repository.final_freeze_readiness(PROJECT_A)
    assert readiness.ready is True
    assert readiness.current_frozen_section_count == readiness.required_section_count


def test_batch_repeat_is_noop_and_reports_already_frozen(runtime) -> None:
    _, documents, _, _, repository = runtime
    _save(repository, documents, PROJECT_A)
    _batch(repository)

    again = _batch(repository, key="batch-freeze-r8-again")

    assert again.frozen_section_ids == []
    assert any(
        "已冻结" in (item.message or "") or item.reason_code == "already_frozen"
        for item in again.skipped
    )


def test_unsaved_section_is_skipped_not_failed(runtime) -> None:
    _, documents, _, _, repository = runtime
    # 不保存工作副本 → readiness 缺口 reason_code=working_copy_not_saved，
    # 批量冻结必须跳过（不能替作者冻结从未保存的内容）。
    result = _batch(repository)
    assert result.frozen_section_ids == []
    assert any(
        item.reason_code == "working_copy_not_saved" for item in result.skipped
    )
    assert result.failures == []


def test_single_section_conflict_does_not_abort_batch(runtime) -> None:
    _, documents, _, _, repository = runtime
    document = documents.documents[PROJECT_A]
    # 多章文档：首章造成版本冲突（用陈旧 revision 意外写入路径模拟），
    # 其余章节照常冻结。
    original_sections = document.sections
    try:
        from packages.contracts.workbench_contracts import ProtocolSection

        document.sections = [
            original_sections[0],
            ProtocolSection(
                section_id="sec_batch_second",
                document_id=original_sections[0].document_id,
                heading="第二章节",
                content_blocks=[
                    {"block_id": "b2", "block_type": "paragraph", "text": "第二章正文。"}
                ],
            ),
        ]
        _save(repository, documents, PROJECT_A, key="save-batch-1")
        from packages.contracts.workbench_contracts import (
            MedicalWritingWorkingCopySaveRequest,
        )

        repository.save_working_copy(
            PROJECT_A,
            "sec_batch_second",
            MedicalWritingWorkingCopySaveRequest(
                document_id=original_sections[0].document_id,
                expected_revision=0,
                content_blocks=document.sections[1].content_blocks,
                actor="medical_manager",
                idempotency_key="save-batch-2",
            ),
        )
        # 让第一章的冻结 CAS 失败：保存后立刻改库内 revision 不可行——
        # 改用monkeypatch第一次 freeze_current_version 抛冲突。
        from packages.contracts.workbench_contracts.models import (
            MedicalWritingSectionFreezeRequest,
        )
        original_freeze = repository.freeze_current_version
        calls: list[str] = []

        def flaky_freeze(project_id, section_id, request):
            calls.append(section_id)
            if section_id == original_sections[0].section_id:
                from services.api.app.sqlite_runtime_store import (
                    StaleRuntimeStateError,
                )

                raise StaleRuntimeStateError("simulated stale revision")
            return original_freeze(project_id, section_id, request)

        repository.freeze_current_version = flaky_freeze
        result = _batch(repository)
        repository.freeze_current_version = original_freeze

        assert original_sections[0].section_id in [
            item.section_id for item in result.failures
        ]
        assert "sec_batch_second" in result.frozen_section_ids
    finally:
        document.sections = original_sections


if __name__ == "__main__":
    import unittest

    unittest.main()
