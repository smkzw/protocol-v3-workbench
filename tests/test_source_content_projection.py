from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from packages.contracts.workbench_contracts import (
    SourceRegistrationResult,
    SourceRegistryEntry,
    SourceRegistrySpan,
)
from services.api.app.source_content_projection import (
    SourceContentProjectionService,
    project_source_content,
)


BASE_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


class ReadOnlyStore:
    def __init__(self, results: list[SourceRegistrationResult]):
        self.results = list(results)
        self.queries: list[str] = []

    def list_results(self, project_id: str) -> list[SourceRegistrationResult]:
        self.queries.append(project_id)
        return list(self.results)

    def append(self, *_args, **_kwargs) -> None:
        raise AssertionError("read-only projection must never append registry state")


def _result(
    *,
    project_id: str = "project_alpha",
    module: str = "medical_monitoring",
    source_kind: str = "protocol_docx",
    content_hash: str = "a" * 64,
    parser_version: str | None = "parser_v1",
    created_offset: int = 0,
    span_suffix: str = "one",
    public_title: str = "方案.docx",
    purpose: str | None = None,
    absolute_path: str = "/Users/example/private/方案.docx",
) -> SourceRegistrationResult:
    entry_id = f"legacy_{project_id}_{module}_{source_kind}_{content_hash[:6]}"
    entry_payload = {
        "entry_id": entry_id,
        "project_id": project_id,
        "module": module,
        "source_kind": source_kind,
        "public_title": public_title,
        "content_hash": content_hash,
        "size_bytes": 1024,
        "parser_status": "parsed",
        "span_count": 1,
        "metadata": {
            "filename": public_title,
            "absolute_path": absolute_path,
            **({"purpose": purpose} if purpose is not None else {}),
        },
        "storage_key": "private/storage/key",
        "server_path": absolute_path,
        "created_at": BASE_TIME + timedelta(minutes=created_offset),
    }
    if parser_version is not None:
        entry_payload["parser_version"] = parser_version
    entry = SourceRegistryEntry.model_validate(entry_payload)
    span = SourceRegistrySpan(
        source_id=f"{entry_id}_{span_suffix}",
        entry_id=entry_id,
        project_id=project_id,
        module=module,
        source_type=f"{source_kind}_paragraph",
        title=public_title,
        locator=f"docx:paragraph:{span_suffix}",
        text_preview=f"高度敏感的原始全文片段 {span_suffix}",
        metadata={"private_locator": absolute_path},
        created_at=entry.created_at,
    )
    return SourceRegistrationResult(entry=entry, spans=[span])


def _dump(projections) -> str:
    return json.dumps(
        [item.model_dump(mode="json") for item in projections],
        ensure_ascii=False,
        sort_keys=True,
    )


def test_legacy_entry_without_parser_version_is_projected_read_only():
    legacy = _result(parser_version=None)
    store = ReadOnlyStore([legacy])

    projected = SourceContentProjectionService(store).list_contents("project_alpha")

    assert store.queries == ["project_alpha"]
    assert len(projected) == 1
    assert projected[0].bindings[0].parser_version == "source_registry_v0_1"
    assert projected[0].bindings[0].current is True


def test_same_content_across_modules_aggregates_one_content_with_two_bindings():
    monitoring = _result(module="medical_monitoring", purpose="protocol_rules")
    writing = _result(module="medical_writing", purpose="chapter_evidence")

    projected = project_source_content(
        [writing, monitoring],
        project_id="project_alpha",
    )

    assert len(projected) == 1
    assert len(projected[0].bindings) == 2
    assert {item.module for item in projected[0].bindings} == {
        "medical_monitoring",
        "medical_writing",
    }
    assert len({item.module_binding_id for item in projected[0].bindings}) == 2


def test_same_binding_keeps_parse_revisions_and_marks_only_latest_current():
    older = _result(parser_version="parser_v1", created_offset=1, span_suffix="v1")
    newer = _result(parser_version="parser_v2", created_offset=2, span_suffix="v2")

    projected = project_source_content(
        [newer, older],
        project_id="project_alpha",
    )

    bindings = projected[0].bindings
    assert len(bindings) == 2
    assert len({item.module_binding_id for item in bindings}) == 1
    assert len({item.parse_revision for item in bindings}) == 2
    assert len({item.module_binding_revision for item in bindings}) == 2
    assert sum(item.current for item in bindings) == 1
    assert next(item for item in bindings if item.current).parser_version == "parser_v2"
    assert projected[0].source_content_revision == project_source_content(
        [older],
        project_id="project_alpha",
    )[0].source_content_revision


def test_exact_duplicate_parse_revision_is_collapsed_deterministically():
    first = _result(public_title="B方案.docx")
    duplicate = _result(public_title="A方案.docx")

    projected = project_source_content(
        [first, duplicate],
        project_id="project_alpha",
    )

    assert len(projected[0].bindings) == 1
    assert projected[0].bindings[0].public_title == "A方案.docx"


def test_different_content_is_never_merged():
    first = _result(content_hash="a" * 64)
    second = _result(content_hash="b" * 64)

    projected = project_source_content(
        [first, second],
        project_id="project_alpha",
    )

    assert len(projected) == 2
    assert len({item.source_content_id for item in projected}) == 2
    assert len({item.source_content_revision for item in projected}) == 2


def test_projection_order_and_ids_do_not_depend_on_input_order():
    results = [
        _result(content_hash="b" * 64, module="medical_writing"),
        _result(content_hash="a" * 64, module="medical_monitoring"),
        _result(
            content_hash="a" * 64,
            module="medical_monitoring",
            parser_version="parser_v2",
            span_suffix="v2",
            created_offset=1,
        ),
    ]

    forward = project_source_content(results, project_id="project_alpha")
    reverse = project_source_content(reversed(results), project_id="project_alpha")

    assert _dump(forward) == _dump(reverse)


def test_public_projection_excludes_hash_paths_storage_keys_and_raw_text():
    private_path = "/Users/example/secret/原始方案.docx"
    result = _result(
        absolute_path=private_path,
        public_title=private_path,
    )
    projected = project_source_content(
        [result],
        project_id="project_alpha",
    )

    payload = _dump(projected)
    assert projected[0].public_title == "原始方案.docx"
    assert projected[0].bindings[0].public_title == "原始方案.docx"
    for forbidden in (
        "content_hash",
        "storage_key",
        "server_path",
        private_path,
        "高度敏感的原始全文片段",
        "private/storage/key",
    ):
        assert forbidden not in payload


def test_queries_filter_bindings_by_module_and_source_kind():
    results = [
        _result(module="medical_monitoring", source_kind="protocol_docx"),
        _result(module="medical_writing", source_kind="protocol_docx"),
        _result(
            module="medical_monitoring",
            source_kind="listing_file",
            content_hash="c" * 64,
        ),
    ]
    store = ReadOnlyStore(results)
    service = SourceContentProjectionService(store)

    module_view = service.list_contents(
        "project_alpha",
        module="medical_monitoring",
    )
    protocol_view = service.list_contents(
        "project_alpha",
        source_kind="protocol_docx",
    )

    assert {binding.module for item in module_view for binding in item.bindings} == {
        "medical_monitoring"
    }
    assert {binding.source_kind for item in protocol_view for binding in item.bindings} == {
        "protocol_docx"
    }
    assert len(module_view) == 2
    assert len(protocol_view) == 1
    assert len(protocol_view[0].bindings) == 2


def test_project_queries_are_isolated_even_if_store_returns_extra_results():
    alpha = _result(project_id="project_alpha", content_hash="d" * 64)
    beta = _result(project_id="project_beta", content_hash="d" * 64)
    store = ReadOnlyStore([alpha, beta])

    alpha_view = SourceContentProjectionService(store).list_contents("project_alpha")
    beta_view = SourceContentProjectionService(store).list_contents("project_beta")

    assert len(alpha_view) == len(beta_view) == 1
    assert alpha_view[0].project_id == "project_alpha"
    assert beta_view[0].project_id == "project_beta"
    assert alpha_view[0].source_content_id != beta_view[0].source_content_id


def test_blank_project_is_rejected_without_reading_or_creating_state():
    store = ReadOnlyStore([])

    try:
        SourceContentProjectionService(store).list_contents("  ")
    except ValueError as exc:
        assert str(exc) == "project_id is required"
    else:
        raise AssertionError("blank project_id must be rejected")

    assert store.queries == []
