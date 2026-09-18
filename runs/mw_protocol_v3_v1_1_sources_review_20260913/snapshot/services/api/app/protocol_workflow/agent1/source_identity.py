"""Product source identities over the existing event stream and staged bytes.

This application service confirms file identity, never medical admission.
Only committed source events select current versions; filesystem latest does not.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Callable

from packages.contracts.workbench_contracts.protocol_v3 import ActorType, SourceArtifact
from app.protocol_workflow.events.models import EventEnvelopeBuilder, verify_event_integrity
from app.protocol_workflow.ports.artifacts import ArtifactStore
from app.protocol_workflow.ports.unit_of_work import UnitOfWork

STREAM = 'source_catalog'
EVENT = 'source.identity.adopted'
SCHEMA = 'source_identity.v1'


def _digest(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class StoredSource:
    source: SourceArtifact
    storage_key: str
    storage_revision: int


@dataclass(frozen=True)
class SourceAdoption:
    source: StoredSource
    current: StoredSource
    replayed: bool


class SourceIdentityService:
    """Compose only at the application boundary, never inside a model worker.

The SQLite UoW serializes staging and event writes through BEGIN IMMEDIATE.
The passed artifact store is staging, outside SQL rollback; abandoned bytes
are retained and a retry can reuse them without adopting an orphan manifest.
"""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], artifacts: ArtifactStore):
        self._uow_factory = uow_factory
        self._artifacts = artifacts

    @staticmethod
    def _history(uow: UnitOfWork, project_id: str):
        events = tuple(uow.event_stream_repository.read_events(project_id, STREAM))
        records = []
        previous = None
        for sequence, event in enumerate(events, 1):
            verify_event_integrity(event)
            if (event.stream_id != STREAM or event.sequence != sequence
                    or event.previous_event_sha256 != previous
                    or event.event_type != EVENT or event.payload_schema_version != SCHEMA):
                raise ValueError('source_catalog_event_invalid')
            payload = event.payload
            if payload['project_id'] != project_id:
                raise ValueError('source_catalog_project_mismatch')
            records.append(StoredSource(
                SourceArtifact.model_validate(payload['source']),
                payload['storage_key'], payload['storage_revision'],
            ))
            previous = event.event_sha256
        return tuple(records), events

    def history(self, project_id: str) -> tuple[StoredSource, ...]:
        with self._uow_factory() as uow:
            return self._history(uow, project_id)[0]

    def list_current(self, project_id: str) -> tuple[StoredSource, ...]:
        current = {}
        for record in self.history(project_id):
            current[record.source.logical_source_key] = record
        return tuple(current.values())

    def read_content(self, project_id: str, source_artifact_id: str) -> bytes:
        for record in self.history(project_id):
            if record.source.source_artifact_id == source_artifact_id:
                stored = self._artifacts.read(record.storage_key, revision=record.storage_revision)
                if stored.metadata.content_sha256 != record.source.content_sha256:
                    raise ValueError('source_content_binding_mismatch')
                return stored.content
        raise LookupError('source_identity_not_found')

    def adopt(self, *, project_id: str, logical_source_key: str, content: bytes,
              source_role: str, source_version: str, jurisdiction: str,
              mime_type: str, captured_at: datetime) -> SourceAdoption:
        if not project_id.strip():
            raise ValueError('project_id_required')
        logical_source_key = logical_source_key.strip()
        content = bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        storage_key = 'source-' + _digest(project_id, logical_source_key)
        source = SourceArtifact(
            source_artifact_id='source-' + _digest(project_id, logical_source_key, sha),
            logical_source_key=logical_source_key, content_sha256=sha,
            source_role=source_role, source_version=source_version,
            jurisdiction=jurisdiction, mime_type=mime_type, captured_at=captured_at,
        )
        with self._uow_factory() as uow:
            records, events = self._history(uow, project_id)
            same_key = [r for r in records if r.source.logical_source_key == logical_source_key]
            for record in same_key:
                if record.source.content_sha256 == sha:
                    for field in ('source_role', 'source_version', 'jurisdiction', 'mime_type'):
                        if getattr(record.source, field) != getattr(source, field):
                            raise ValueError('source_metadata_conflict:' + field)
                    return SourceAdoption(record, same_key[-1], True)
            metadata = self._artifacts.store(
                storage_key, content, media_type=mime_type, created_at=captured_at,
            )
            stored = self._artifacts.read(storage_key, revision=metadata.revision)
            if stored.content != content or stored.metadata.content_sha256 != sha:
                raise ValueError('source_content_binding_mismatch')
            record = StoredSource(source, storage_key, metadata.revision)
            event = EventEnvelopeBuilder().build(
                domain_event_id='source-event-' + _digest(project_id, logical_source_key, sha),
                stream_id=STREAM, sequence=len(events) + 1, event_type=EVENT,
                payload_schema_version=SCHEMA, upcaster_id='none', actor_type=ActorType.SYSTEM,
                actor_id='source-import', action='adopt_source_identity',
                reason='Preserve supplied source identity; medical admission remains pending.',
                payload={'project_id': project_id, 'source': source.model_dump(mode='json'),
                         'storage_key': storage_key, 'storage_revision': metadata.revision},
                emitted_at=captured_at,
                previous_event_sha256=events[-1].event_sha256 if events else None,
            )
            uow.event_stream_repository.append_events(project_id, STREAM, [event])
            uow.commit()
            return SourceAdoption(record, record, False)
