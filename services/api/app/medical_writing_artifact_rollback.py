"""Route-free, ACL-bound artifact generation-pointer rollback adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .medical_writing_artifact_lifecycle import (
    MedicalWritingArtifactPrincipal,
    MedicalWritingArtifactLifecycleConflict,
    MedicalWritingArtifactLifecycleRepository,
    MedicalWritingArtifactLifecycleResult,
    MedicalWritingArtifactLifecycleStale,
)
from .medical_writing_principal_acl import (
    MedicalWritingAccessRequest,
    MedicalWritingAclPolicy,
    MedicalWritingAuthenticatedPrincipal,
    MedicalWritingAuthorizationDecision,
    require_medical_writing_authorization,
)


class MedicalWritingArtifactRollbackError(ValueError):
    """Base error for malformed rollback intents."""


class MedicalWritingArtifactRollbackBindingMismatch(
    MedicalWritingArtifactRollbackError
):
    """Raised when a current/target artifact identity hash does not match."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalWritingArtifactRollbackError(f"{field_name} is required")
    return text


def _require_hash(value: Any, *, field_name: str) -> str:
    text = _require_text(value, field_name=field_name).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise MedicalWritingArtifactRollbackError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return text


@dataclass(frozen=True)
class MedicalWritingArtifactRollbackIntent:
    request_id: str
    project_id: str
    document_id: str
    current_artifact_id: str
    current_identity_sha256: str
    target_artifact_id: str
    target_identity_sha256: str
    expected_pointer_revision: int
    reason: str
    idempotency_key: str
    client_actor: Optional[str] = None
    trace_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        try:
            revision = int(self.expected_pointer_revision)
        except (TypeError, ValueError) as exc:
            raise MedicalWritingArtifactRollbackError(
                "expected_pointer_revision must be an integer"
            ) from exc
        if revision < 1:
            raise MedicalWritingArtifactRollbackError(
                "expected_pointer_revision must be >= 1"
            )
        actor = str(self.client_actor or "").strip()
        trace = str(self.trace_id or "").strip()
        return {
            "schema_version": "medical_writing_artifact_rollback_v1",
            "request_id": _require_text(self.request_id, field_name="request_id"),
            "project_id": _require_text(self.project_id, field_name="project_id"),
            "document_id": _require_text(self.document_id, field_name="document_id"),
            "current_artifact_id": _require_text(
                self.current_artifact_id, field_name="current_artifact_id"
            ),
            "current_identity_sha256": _require_hash(
                self.current_identity_sha256, field_name="current_identity_sha256"
            ),
            "target_artifact_id": _require_text(
                self.target_artifact_id, field_name="target_artifact_id"
            ),
            "target_identity_sha256": _require_hash(
                self.target_identity_sha256, field_name="target_identity_sha256"
            ),
            "expected_pointer_revision": revision,
            "reason": _require_text(self.reason, field_name="reason"),
            "idempotency_key": _require_text(
                self.idempotency_key, field_name="idempotency_key"
            ),
            "client_actor_present": bool(actor),
            "client_actor_sha256": _sha256(actor) if actor else "",
            "trace_id": trace,
        }

    @property
    def intent_hash(self) -> str:
        return _sha256(self.as_dict())


@dataclass(frozen=True)
class MedicalWritingArtifactRollbackResult:
    lifecycle_result: MedicalWritingArtifactLifecycleResult
    authorization: MedicalWritingAuthorizationDecision
    intent_hash: str
    current_artifact_id: str
    target_artifact_id: str

    @property
    def replayed(self) -> bool:
        return self.lifecycle_result.replayed

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "medical_writing_artifact_rollback_v1",
            "intent_hash": self.intent_hash,
            "current_artifact_id": self.current_artifact_id,
            "target_artifact_id": self.target_artifact_id,
            "replayed": self.replayed,
            "authorization": self.authorization.as_dict(),
            "lifecycle": {
                "event_id": self.lifecycle_result.event_id,
                "action": self.lifecycle_result.action,
                "allowed": self.lifecycle_result.allowed,
                "reason": self.lifecycle_result.reason,
                "pointer_revision": self.lifecycle_result.pointer_revision,
                "artifact_id": self.lifecycle_result.record.artifact_id,
            },
        }


def artifact_identity_sha256(record: Any) -> str:
    """Hash only the canonical immutable identity, never artifact bytes."""

    try:
        identity = record.identity.as_dict()
    except AttributeError as exc:
        raise MedicalWritingArtifactRollbackError(
            "artifact record identity is unavailable"
        ) from exc
    return _sha256(identity)


def _lifecycle_principal(
    principal: MedicalWritingAuthenticatedPrincipal,
) -> MedicalWritingArtifactPrincipal:
    """Project the already-validated principal into the lifecycle contract."""

    payload = principal.as_dict()
    return MedicalWritingArtifactPrincipal(
        subject_id=payload["subject_id"],
        tenant_id=payload["tenant_id"],
        role=payload["role"],
        assurance=payload["assurance"],
        authenticated=payload["authenticated"],
    )


def execute_artifact_rollback(
    *,
    repository: MedicalWritingArtifactLifecycleRepository,
    principal: MedicalWritingAuthenticatedPrincipal,
    policy: MedicalWritingAclPolicy,
    intent: MedicalWritingArtifactRollbackIntent,
    now: Any = None,
) -> MedicalWritingArtifactRollbackResult:
    """Authorize and execute one immutable pointer transition."""

    intent_payload = intent.as_dict()
    lifecycle_principal = _lifecycle_principal(principal)
    authorization = require_medical_writing_authorization(
        principal=principal,
        request=MedicalWritingAccessRequest(
            request_id=intent_payload["request_id"],
            tenant_id=principal.tenant_id,
            project_id=intent_payload["project_id"],
            document_id=intent_payload["document_id"],
            action="rollback",
            client_actor=intent.client_actor,
            trace_id=intent.trace_id,
        ),
        policy=policy,
        now=now,
    )

    target = repository.get(
        principal=lifecycle_principal,
        project_id=intent_payload["project_id"],
        artifact_id=intent_payload["target_artifact_id"],
    )
    if artifact_identity_sha256(target) != intent_payload["target_identity_sha256"]:
        raise MedicalWritingArtifactRollbackBindingMismatch(
            "target artifact identity hash does not match rollback intent"
        )
    if target.identity.document_id != intent_payload["document_id"]:
        raise MedicalWritingArtifactRollbackBindingMismatch(
            "target artifact document does not match rollback intent"
        )
    if target.state != "active":
        raise MedicalWritingArtifactLifecycleConflict(
            "rollback target must be active"
        )

    # The lifecycle repository checks current ID/revision/hash inside its
    # transaction.  Its idempotency lookup happens before those checks, so an
    # exact replay remains a replay after the pointer has moved.
    try:
        lifecycle_result = repository.rollback_to(
            principal=lifecycle_principal,
            project_id=intent_payload["project_id"],
            document_id=intent_payload["document_id"],
            target_artifact_id=intent_payload["target_artifact_id"],
            expected_pointer_revision=intent_payload["expected_pointer_revision"],
            reason=intent_payload["reason"],
            idempotency_key=intent_payload["idempotency_key"],
            now=now,
            expected_current_artifact_id=intent_payload["current_artifact_id"],
            expected_current_identity_sha256=intent_payload["current_identity_sha256"],
            request_context={"intent_hash": intent.intent_hash},
        )
    except MedicalWritingArtifactLifecycleStale as exc:
        if "identity" in str(exc):
            raise MedicalWritingArtifactRollbackBindingMismatch(
                "current artifact identity hash does not match rollback intent"
            ) from exc
        raise
    return MedicalWritingArtifactRollbackResult(
        lifecycle_result=lifecycle_result,
        authorization=authorization,
        intent_hash=intent.intent_hash,
        current_artifact_id=intent_payload["current_artifact_id"],
        target_artifact_id=intent_payload["target_artifact_id"],
    )
