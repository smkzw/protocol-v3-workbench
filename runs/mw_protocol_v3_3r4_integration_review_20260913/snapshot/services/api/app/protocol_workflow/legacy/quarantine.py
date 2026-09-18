"""Quarantine typed primitives for the v2→v3 legacy migration inventory.

This module is deliberately self-contained: it imports no repository, no
runtime singleton, no database and no sibling legacy module, so it can never
read or write a live source.  It defines the *stable reason vocabulary* and
the *quarantine record* shape that the inventory (``migration_inventory.py``)
and the later mapping/cutover tasks consume.

Design authority: frozen plan Task 1.10 and design §6.2 (unmappable legacy
data enters quarantine with an explicit reason; nothing is silently dropped)
and §20 (shadow runs are strictly read-only).  The reason vocabulary is a
finite, closed set: callers may not invent free-text codes at runtime.

Chinese-safety: every public label is UTF-8 Chinese and every canonical JSON
encoding used for hashing is produced with ``ensure_ascii=False`` (see
``canonical_json`` in ``canonical/hashing.py``), so Chinese text round-trips
unescaped and deterministically.
"""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field
from typing_extensions import Annotated

from ..canonical.hashing import canonical_json

__all__ = [
    "FAMILY_PUBLIC_LABEL_ZH",
    "QUARANTINE_REASON_CATALOG",
    "QuarantineReason",
    "QuarantineReasonKind",
    "QuarantineRecord",
    "quarantine_reason",
]

QUARANTINE_SCHEMA_VERSION = "mw_legacy_quarantine_v1"

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ReasonCode = Annotated[
    str,
    StringConstraints(pattern=r"^MW-LEGACY-Q-[A-Z][A-Z0-9_]{0,63}$"),
]


class QuarantineReasonKind(str, Enum):
    """Closed vocabulary of why a legacy source object cannot be inventoried.

    ``unsupported_type`` is reserved for the mapping phase (Worker 02), which
    declares the per-family type allow-list; the inventory itself only emits
    the other four kinds.
    """

    UNSUPPORTED_FAMILY = "unsupported_family"
    UNSUPPORTED_TYPE = "unsupported_type"
    INCOMPLETE_RECORD = "incomplete_record"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    DUPLICATE_CONFLICT = "duplicate_conflict"


class QuarantineReason(BaseModel):
    """Immutable, stable reason metadata.

    ``kind`` is the machine identity, ``code`` is a stable ASCII code for
    logs/audit, and the labels are fixed public copy (English + Chinese).
    Instances are canonicalised: the catalog returns the same frozen object
    for the same kind, so reason metadata can never drift between records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    kind: QuarantineReasonKind
    code: ReasonCode
    label_en: str = Field(min_length=1)
    label_zh: str = Field(min_length=1)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "code": self.code,
            "label_en": self.label_en,
            "label_zh": self.label_zh,
        }


_QUARANTINE_REASONS: dict[QuarantineReasonKind, QuarantineReason] = {
    QuarantineReasonKind.UNSUPPORTED_FAMILY: QuarantineReason(
        kind=QuarantineReasonKind.UNSUPPORTED_FAMILY,
        code="MW-LEGACY-Q-UNSUPPORTED_FAMILY",
        label_en="source family is not one of the seven declared families",
        label_zh="来源族不在七类声明范围内",
    ),
    QuarantineReasonKind.UNSUPPORTED_TYPE: QuarantineReason(
        kind=QuarantineReasonKind.UNSUPPORTED_TYPE,
        code="MW-LEGACY-Q-UNSUPPORTED_TYPE",
        label_en="source type is not declared for the family",
        label_zh="来源类型不在该来源族的声明范围内",
    ),
    QuarantineReasonKind.INCOMPLETE_RECORD: QuarantineReason(
        kind=QuarantineReasonKind.INCOMPLETE_RECORD,
        code="MW-LEGACY-Q-INCOMPLETE_RECORD",
        label_en="source record is missing required fields or a valid payload",
        label_zh="来源记录缺少必需字段或缺少有效载荷",
    ),
    QuarantineReasonKind.AMBIGUOUS_IDENTITY: QuarantineReason(
        kind=QuarantineReasonKind.AMBIGUOUS_IDENTITY,
        code="MW-LEGACY-Q-AMBIGUOUS_IDENTITY",
        label_en="source identity cannot be normalized or is self-contradictory",
        label_zh="来源身份无法归一化或自相矛盾",
    ),
    QuarantineReasonKind.DUPLICATE_CONFLICT: QuarantineReason(
        kind=QuarantineReasonKind.DUPLICATE_CONFLICT,
        code="MW-LEGACY-Q-DUPLICATE_CONFLICT",
        label_en="duplicate source identity with conflicting payload",
        label_zh="重复来源身份且载荷冲突",
    ),
}

QUARANTINE_REASON_CATALOG: Mapping[QuarantineReasonKind, QuarantineReason] = (
    MappingProxyType(dict(_QUARANTINE_REASONS))
)


def quarantine_reason(kind: QuarantineReasonKind) -> QuarantineReason:
    """Return the canonical, frozen reason metadata for a kind.

    The catalog is the only source of reason metadata; the returned object is
    shared and immutable, so two records with the same kind always carry the
    exact same ``code`` / ``label_en`` / ``label_zh`` values.
    """

    try:
        return QUARANTINE_REASON_CATALOG[QuarantineReasonKind(kind)]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unknown quarantine reason kind: {kind!r}") from exc


# Stable Chinese public labels for the seven declared source families.  Keyed
# by the canonical family *string value* so this module stays import-free.
FAMILY_PUBLIC_LABEL_ZH: Mapping[str, str] = MappingProxyType(
    {
        "study_definition": "研究方案定义",
        "journey_stage_draft": "写作旅程阶段草稿",
        "working_copy_snapshot": "工作副本与快照",
        "corpus_evidence": "语料与证据",
        "decision_approval": "决策与审批",
        "protocol_document": "方案文档",
        "artifact_lineage": "产物谱系",
    }
)


class QuarantineRecord(BaseModel):
    """Immutable quarantine candidate bound to the original source.

    Every record keeps the *original* source hash (``payload_sha256``), the
    normalized project/family/type/id/revision identity, the immutable
    locator hash and the closed-set reason(s).  ``quarantine_id`` is a
    deterministic content hash of the whole record, so identical inputs
    always produce the same id regardless of insertion order or caller state.

    The hash fields are ``None`` only when the offending item carried no
    JSON-serialisable payload at all (missing/invalid payload); a fabricated
    digest is never substituted.  The module is standalone by design:
    identity fields are canonical string values (validated by the inventory
    before this record is built), which keeps quarantine.py free of any
    import cycle with migration_inventory.py.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: str = QUARANTINE_SCHEMA_VERSION
    project_id: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    revision_token: str = Field(min_length=1)
    payload_sha256: Optional[Sha256Hex] = None
    locator_sha256: Optional[Sha256Hex] = None
    reasons: tuple[QuarantineReason, ...] = Field(min_length=1)
    detail_zh: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def quarantine_id(self) -> str:
        payload = self.canonical_payload()
        return sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "source_family": self.source_family,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "revision_token": self.revision_token,
            "payload_sha256": self.payload_sha256,
            "locator_sha256": self.locator_sha256,
            "reasons": [reason.canonical_payload() for reason in self.reasons],
            "detail_zh": self.detail_zh,
        }

    @property
    def reason_kinds(self) -> tuple[QuarantineReasonKind, ...]:
        return tuple(reason.kind for reason in self.reasons)
