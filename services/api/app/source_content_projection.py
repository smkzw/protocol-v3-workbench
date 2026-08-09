from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.workbench_contracts import (
    SourceRegistrationResult,
    SourceRegistryEntry,
    SourceRegistrySpan,
)

from .source_intake import SourceRegistryStore


SOURCE_CONTENT_PROJECTION_VERSION = "source_content_projection_v1"


class SourceModuleBindingProjection(BaseModel):
    """Public, read-only view of one module's parse of shared source content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module_binding_id: str
    module_binding_revision: str
    legacy_entry_id: str
    module: str
    purpose: str
    source_kind: str
    parse_revision: str
    parser_status: str
    parser_version: str
    public_title: str
    span_count: int = Field(ge=0)
    current: bool
    created_at: datetime


class SourceContentProjection(BaseModel):
    """Shared content identity with module-owned parse revisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_content_id: str
    source_content_revision: str
    project_id: str
    public_title: str
    size_bytes: int = Field(ge=0)
    first_registered_at: datetime
    bindings: tuple[SourceModuleBindingProjection, ...]


class SourceContentProjectionService:
    """Projects the existing module-scoped registry without creating new state."""

    def __init__(self, store: SourceRegistryStore):
        self._store = store

    def list_contents(
        self,
        project_id: str,
        *,
        module: str | None = None,
        source_kind: str | None = None,
    ) -> list[SourceContentProjection]:
        project = project_id.strip()
        if not project:
            raise ValueError("project_id is required")
        module_filter = _optional_filter(module)
        source_kind_filter = _optional_filter(source_kind)
        results = [
            result
            for result in self._store.list_results(project)
            if result.entry.project_id == project
        ]
        return project_source_content(
            results,
            project_id=project,
            module=module_filter,
            source_kind=source_kind_filter,
        )


def project_source_content(
    results: Iterable[SourceRegistrationResult],
    *,
    project_id: str,
    module: str | None = None,
    source_kind: str | None = None,
) -> list[SourceContentProjection]:
    """Build a deterministic, privacy-bounded projection from registry results."""

    project = project_id.strip()
    if not project:
        raise ValueError("project_id is required")
    module_filter = _optional_filter(module)
    source_kind_filter = _optional_filter(source_kind)

    by_content: dict[str, list[SourceRegistrationResult]] = defaultdict(list)
    for result in results:
        entry = result.entry
        if entry.project_id != project:
            continue
        if module_filter is not None and entry.module != module_filter:
            continue
        if source_kind_filter is not None and entry.source_kind != source_kind_filter:
            continue
        by_content[entry.content_hash].append(result)

    projections: list[SourceContentProjection] = []
    for content_hash, content_results in by_content.items():
        source_content_id = _opaque_id(
            "sc",
            "content",
            project,
            content_hash,
        )
        source_content_revision = _opaque_id(
            "scr",
            "content_revision",
            project,
            content_hash,
        )
        binding_candidates = [
            _binding_candidate(source_content_id, result)
            for result in content_results
        ]
        bindings = _finalize_bindings(binding_candidates)
        entries = [result.entry for result in content_results]
        projections.append(
            SourceContentProjection(
                source_content_id=source_content_id,
                source_content_revision=source_content_revision,
                project_id=project,
                public_title=min(_public_title(entry.public_title) for entry in entries),
                size_bytes=max(entry.size_bytes for entry in entries),
                first_registered_at=min(entry.created_at for entry in entries),
                bindings=tuple(bindings),
            )
        )

    return sorted(
        projections,
        key=lambda item: (item.source_content_id, item.source_content_revision),
    )


def _binding_candidate(
    source_content_id: str,
    result: SourceRegistrationResult,
) -> SourceModuleBindingProjection:
    entry = result.entry
    purpose = _entry_purpose(entry)
    parser_version = _effective_parser_version(entry)
    module_binding_id = _opaque_id(
        "smb",
        "module_binding",
        source_content_id,
        entry.module,
        purpose,
        entry.source_kind,
    )
    parse_revision = _parse_revision(entry, result.spans, parser_version)
    module_binding_revision = _opaque_id(
        "smbr",
        "module_binding_revision",
        module_binding_id,
        parse_revision,
    )
    return SourceModuleBindingProjection(
        module_binding_id=module_binding_id,
        module_binding_revision=module_binding_revision,
        legacy_entry_id=entry.entry_id,
        module=entry.module,
        purpose=purpose,
        source_kind=entry.source_kind,
        parse_revision=parse_revision,
        parser_status=entry.parser_status,
        parser_version=parser_version,
        public_title=_public_title(entry.public_title),
        span_count=len({_span_public_identity(span) for span in result.spans}),
        current=False,
        created_at=entry.created_at,
    )


def _finalize_bindings(
    candidates: Sequence[SourceModuleBindingProjection],
) -> list[SourceModuleBindingProjection]:
    unique_revisions: dict[
        tuple[str, str],
        SourceModuleBindingProjection,
    ] = {}
    for candidate in candidates:
        key = (candidate.module_binding_id, candidate.module_binding_revision)
        existing = unique_revisions.get(key)
        if existing is None or _candidate_preference(candidate) < _candidate_preference(existing):
            unique_revisions[key] = candidate

    current_by_binding: dict[str, str] = {}
    revisions_by_binding: dict[str, list[SourceModuleBindingProjection]] = defaultdict(list)
    for candidate in unique_revisions.values():
        revisions_by_binding[candidate.module_binding_id].append(candidate)
    for binding_id, revisions in revisions_by_binding.items():
        current_by_binding[binding_id] = max(
            revisions,
            key=lambda item: (item.created_at, item.module_binding_revision),
        ).module_binding_revision

    finalized = [
        candidate.model_copy(
            update={
                "current": (
                    current_by_binding[candidate.module_binding_id]
                    == candidate.module_binding_revision
                )
            }
        )
        for candidate in unique_revisions.values()
    ]
    return sorted(
        finalized,
        key=lambda item: (
            item.module,
            item.source_kind,
            item.purpose,
            item.module_binding_id,
            0 if item.current else 1,
            item.created_at,
            item.module_binding_revision,
        ),
    )


def _parse_revision(
    entry: SourceRegistryEntry,
    spans: Sequence[SourceRegistrySpan],
    parser_version: str,
) -> str:
    span_identities = sorted(_span_parse_identity(span) for span in spans)
    return _opaque_id(
        "spr",
        "parse_revision",
        parser_version,
        entry.entry_id,
        entry.module,
        entry.source_kind,
        entry.parser_status,
        span_identities,
    )


def _span_parse_identity(span: SourceRegistrySpan) -> tuple[str, ...]:
    preview_identity = span.preview_hash or _digest(span.text_preview)
    return (
        span.source_id,
        span.entry_id,
        span.project_id,
        span.module,
        span.source_type,
        span.locator,
        preview_identity,
        _digest(_canonical_json(span.metadata)),
    )


def _span_public_identity(span: SourceRegistrySpan) -> tuple[str, str, str]:
    return (span.source_id, span.source_type, span.locator)


def _entry_purpose(entry: SourceRegistryEntry) -> str:
    for key in ("purpose", "document_role", "expected_file_role"):
        value = entry.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return entry.source_kind


def _effective_parser_version(entry: SourceRegistryEntry) -> str:
    metadata_version = entry.metadata.get("parser_version")
    if isinstance(metadata_version, str) and metadata_version.strip():
        return metadata_version.strip()
    return entry.parser_version


def _candidate_preference(
    candidate: SourceModuleBindingProjection,
) -> tuple[str, str, str]:
    return (
        candidate.public_title,
        candidate.legacy_entry_id,
        candidate.module_binding_revision,
    )


def _optional_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _public_title(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "source"


def _opaque_id(prefix: str, domain: str, *parts: Any) -> str:
    payload = _canonical_json(
        [SOURCE_CONTENT_PROJECTION_VERSION, domain, *parts]
    )
    return f"{prefix}_{_digest(payload)[:24]}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
