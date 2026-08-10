"""Canonical reducer and CAS kernel for Protocol v3.

This package contains the pure, deterministic reducers that are the only path
authorised to change StudyDefinition and SemanticDocumentRevision authority.
The package imports no repository, storage, network, clock or model dependency.
"""

from __future__ import annotations

from .hashing import (
    canonical_json,
    canonical_revision_hash,
    decision_cas_identity,
    exact_payload_sha256,
    fact_set_sha256,
    material_sha256,
    study_definition_lineage_hash,
)
from .decisions import (
    DecisionCasError,
    DecisionLedger,
    DecisionPayloadConflictError as DecisionRecordPayloadConflictError,
    DecisionReducer,
    DecisionReplayResult,
    IllegalDecisionTransitionError,
)
from .study_definition import (
    DecisionEffect,
    DecisionEffectLedger,
    DecisionPayloadConflictError,
    FrozenFactOverwriteError,
    RevisionStaleError,
    StudyDefinitionCasError,
    StudyDefinitionReducer,
    study_revision_hash,
)
from .document import (
    DocumentCasError,
    DocumentEffect,
    DocumentEffectLedger,
    DocumentPayloadConflictError,
    DocumentRevisionStaleError,
    EditClass,
    EditOutcome,
    FactProposal,
    FactProposalError,
    FactRevisionMismatchError,
    SemanticDocumentReducer,
    UnboundFactPathError,
    document_revision_hash,
)

__all__ = [
    "DecisionCasError",
    "DecisionEffect",
    "DecisionEffectLedger",
    "DecisionLedger",
    "DecisionPayloadConflictError",
    "DecisionRecordPayloadConflictError",
    "DecisionReducer",
    "DecisionReplayResult",
    "DocumentCasError",
    "DocumentEffect",
    "DocumentEffectLedger",
    "DocumentPayloadConflictError",
    "DocumentRevisionStaleError",
    "EditClass",
    "EditOutcome",
    "FactProposal",
    "FactProposalError",
    "FactRevisionMismatchError",
    "FrozenFactOverwriteError",
    "IllegalDecisionTransitionError",
    "RevisionStaleError",
    "SemanticDocumentReducer",
    "StudyDefinitionCasError",
    "StudyDefinitionReducer",
    "UnboundFactPathError",
    "canonical_json",
    "canonical_revision_hash",
    "decision_cas_identity",
    "document_revision_hash",
    "exact_payload_sha256",
    "fact_set_sha256",
    "material_sha256",
    "study_definition_lineage_hash",
    "study_revision_hash",
]
