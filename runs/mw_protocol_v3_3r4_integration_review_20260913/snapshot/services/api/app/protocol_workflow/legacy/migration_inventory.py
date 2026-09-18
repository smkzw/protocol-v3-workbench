"""Read-only v2→v3 legacy migration inventory.

This module turns *caller-supplied synthetic* legacy source records into an
immutable, JSON-canonical inventory snapshot with explicit quarantine.  It is
a pure in-memory function: it opens no database, imports no runtime singleton,
touches no repository and never infers semantic nodes.  The 3,878-row company
corpus requirement is represented here only as a *denominator discipline* —
every input row produces exactly one outcome (inventoried, quarantined, or
deduplicated-as-identical), and nothing is dropped or fabricated.

Design authority: frozen plan Task 1.10 (per-field identity normalisation,
explicit quarantine with reason/locator/source hash, deterministic hashes,
duplicate identity with divergent payload fails closed) and design §6.2 / §20
(shadow runs strictly read-only; unmappable data is quarantined, not dropped).

Determinism contract:

* identity keys and sort orders are canonical strings — never input position;
* ``canonical_json`` (sorted keys, ``ensure_ascii=False``, compact
  separators) is the only serialisation used for hashing, so Chinese payloads
  and labels round-trip unescaped and byte-stably;
* duplicate identity is resolved by *content*, not by arrival order: an
  identity key whose occurrences all share one payload hash yields one
  inventoried record plus ``n-1`` deduplicated rows; an identity key whose
  occurrences carry divergent payloads quarantines **every** occurrence.  Both
  outcomes are identical for any permutation of the input sequence.
"""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from typing import Any, Literal, Mapping, Optional, Sequence, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from ..canonical.hashing import canonical_json

from .quarantine import (
    FAMILY_PUBLIC_LABEL_ZH,
    QuarantineReasonKind,
    QuarantineRecord,
    quarantine_reason,
)

__all__ = [
    "FAMILY_PUBLIC_LABEL_ZH",
    "INVENTORY_SCHEMA_VERSION",
    "ImmutableLocator",
    "InventorySnapshot",
    "LEGACY_SOURCE_FAMILIES",
    "LegacySourceFamily",
    "LegacySourceRecord",
    "SourceRevisionToken",
    "build_inventory",
]

INVENTORY_SCHEMA_VERSION = "mw_legacy_inventory_v1"

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


# ---------------------------------------------------------------------------
# The seven declared source families (the closed migration denominator)
# ---------------------------------------------------------------------------


class LegacySourceFamily(str, Enum):
    """Exactly the seven v2 source families declared by the task context.

    Enum order is stable and is also the canonical sort order for family.
    """

    STUDY_DEFINITION = "study_definition"
    JOURNEY_STAGE_DRAFT = "journey_stage_draft"
    WORKING_COPY_SNAPSHOT = "working_copy_snapshot"
    CORPUS_EVIDENCE = "corpus_evidence"
    DECISION_APPROVAL = "decision_approval"
    PROTOCOL_DOCUMENT = "protocol_document"
    ARTIFACT_LINEAGE = "artifact_lineage"


LEGACY_SOURCE_FAMILIES: frozenset[str] = frozenset(
    member.value for member in LegacySourceFamily
)

_FAMILY_BY_VALUE: dict[str, LegacySourceFamily] = {
    member.value: member for member in LegacySourceFamily
}

_FAMILY_BY_CASEFOLD: dict[str, LegacySourceFamily] = {
    member.value.casefold(): member for member in LegacySourceFamily
}


def _coerce_family(value: Any) -> Optional[LegacySourceFamily]:
    """Coerce a family value strictly; return ``None`` when unsupported.

    Accepts the enum member or its canonical string value.  A casefold match
    is also accepted (``Study_Definition`` -> ``study_definition``); anything
    else — including a plausible but undeclared family — returns ``None`` so
    the caller can quarantine it explicitly instead of guessing.
    """

    if isinstance(value, LegacySourceFamily):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text in _FAMILY_BY_VALUE:
            return _FAMILY_BY_VALUE[text]
        folded = text.casefold()
        if folded in _FAMILY_BY_CASEFOLD:
            return _FAMILY_BY_CASEFOLD[folded]
    return None


# ---------------------------------------------------------------------------
# Frozen JSON containers: payloads stay deep-immutable and JSON-canonical
# ---------------------------------------------------------------------------


class _FrozenJsonDict(dict[str, JsonValue]):
    """JSON mapping that serialises like a dict but rejects mutation."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("legacy inventory payload mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self


class _FrozenJsonList(list[JsonValue]):
    """JSON list that serialises like a list but rejects mutation."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("legacy inventory payload list is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self


def _freeze_json_value(value: JsonValue) -> JsonValue:
    """Deep-copy a JSON value into frozen containers (caller input untouched)."""

    if isinstance(value, dict):
        return _FrozenJsonDict(
            {key: _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _FrozenJsonList(_freeze_json_value(item) for item in value)
    return value


def _payload_hash_of(payload: Any) -> Optional[str]:
    """SHA-256 of the canonical JSON encoding of a raw payload.

    Returns ``None`` when the value is not JSON-serialisable (the quarantine
    record then says so explicitly instead of inventing a hash).
    """

    try:
        return sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return None


def _locator_hash_of(
    *,
    project_id: str,
    source_family: str,
    source_type: str,
    source_id: str,
    revision_token: str,
    payload_sha256: Optional[str],
) -> Optional[str]:
    """Locator hash for quarantine records, mirroring ImmutableLocator.

    Requires a real payload hash; without one the locator cannot be bound to
    content and is ``None`` rather than a fabricated digest.
    """

    if payload_sha256 is None:
        return None
    payload = {
        "project_id": project_id,
        "source_family": source_family,
        "source_type": source_type,
        "source_id": source_id,
        "revision_token": revision_token,
        "payload_sha256": payload_sha256,
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Identity primitives
# ---------------------------------------------------------------------------


class SourceRevisionToken(BaseModel):
    """Normalised, immutable source revision token.

    Normalisation is strip + collapse of internal whitespace runs; the empty
    token is rejected (a source without a revision cannot be inventoried
    deterministically and is handled as an incomplete record by the builder).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str = Field(min_length=1, max_length=512)

    @field_validator("value", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("revision token must be a string")
        text = " ".join(value.strip().split())
        if not text:
            raise ValueError("revision token must not be empty")
        return text

    def __str__(self) -> str:
        return self.value


class ImmutableLocator(BaseModel):
    """Immutable locator binding normalized identity + payload hash.

    ``locator_sha256`` is derived (computed), never caller-supplied, so two
    locators with the same identity and payload always share one locator hash.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    source_family: LegacySourceFamily
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    revision_token: str = Field(min_length=1)
    payload_sha256: Sha256Hex

    @computed_field  # type: ignore[prop-decorator]
    @property
    def locator_sha256(self) -> str:
        return sha256(
            canonical_json(self.canonical_payload()).encode("utf-8")
        ).hexdigest()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def family_label_zh(self) -> str:
        return FAMILY_PUBLIC_LABEL_ZH.get(
            self.source_family.value, self.source_family.value
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "source_family": self.source_family.value,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "revision_token": self.revision_token,
            "payload_sha256": self.payload_sha256,
        }


class LegacySourceRecord(BaseModel):
    """Frozen legacy source record: normalized identity + original payload.

    The payload is stored byte-stable (no whitespace stripping, no key
    reordering) in deep-frozen JSON containers and its ``payload_sha256`` is
    the SHA-256 of the canonical JSON encoding of the *original* payload —
    computed, so it cannot diverge from the stored content.  The immutable
    locator is derived from the same identity + hash.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_legacy_inventory_v1"] = INVENTORY_SCHEMA_VERSION
    project_id: str = Field(min_length=1, max_length=512)
    source_family: LegacySourceFamily
    source_type: str = Field(min_length=1, max_length=512)
    source_id: str = Field(min_length=1, max_length=512)
    revision_token: SourceRevisionToken
    payload: JsonValue

    @field_validator("project_id", "source_type", "source_id", mode="before")
    @classmethod
    def _normalize_identity(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("identity field must be a string")
        text = " ".join(value.strip().split())
        if not text:
            raise ValueError("identity field must not be empty")
        return text

    @model_validator(mode="after")
    def _freeze_payload(self) -> "LegacySourceRecord":
        # JSON validation happens first; only then do we swap in the deep-
        # frozen containers so `payload` rejects every mutation attempt.
        object.__setattr__(self, "payload", _freeze_json_value(self.payload))
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def payload_sha256(self) -> str:
        return sha256(canonical_json(self.payload).encode("utf-8")).hexdigest()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def locator(self) -> ImmutableLocator:
        return ImmutableLocator(
            project_id=self.project_id,
            source_family=self.source_family,
            source_type=self.source_type,
            source_id=self.source_id,
            revision_token=self.revision_token.value,
            payload_sha256=self.payload_sha256,
        )

    @property
    def identity_key(self) -> tuple[str, str, str, str, str]:
        """Canonical, order-free identity: project, family, type, id, revision."""

        return (
            self.project_id,
            self.source_family.value,
            self.source_type,
            self.source_id,
            self.revision_token.value,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "source_family": self.source_family.value,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "revision_token": self.revision_token.value,
            "payload_sha256": self.payload_sha256,
            "locator_sha256": self.locator.locator_sha256,
        }


# ---------------------------------------------------------------------------
# Inventory snapshot
# ---------------------------------------------------------------------------


class InventorySnapshot(BaseModel):
    """Immutable, self-validating result of one inventory pass.

    Accounting invariant (never violated)::

        source_count == record_count + quarantined_count + deduplicated_count

    ``family_counts`` counts *inventoried* records per declared family;
    ``counts_by_reason`` counts quarantine records per reason kind.

    Every snapshot validates itself at construction (after-validator):

    * the accounting identity above holds exactly;
    * declared counts equal the actual tuple lengths;
    * ``records``/``quarantine_records`` are in the canonical sort order and
      contain no duplicate identities/records, so a caller can never forge a
      non-canonical snapshot;
    * ``family_counts`` equals the actual per-family record counts, uses only
      the seven declared families and carries positive integer counts;
    * ``counts_by_reason`` equals the actual per-reason quarantine counts,
      uses only the closed reason vocabulary and carries positive integer
      counts.

    ``family_counts`` and ``counts_by_reason`` are then deep-frozen, so every
    dict mutation API fails and ``inventory_sha256`` can never drift after
    construction.  Serialization stays deterministic: ``canonical_payload``
    sorts both maps by key before hashing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_legacy_inventory_v1"] = INVENTORY_SCHEMA_VERSION
    source_count: int = Field(ge=0)
    record_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    deduplicated_count: int = Field(ge=0)
    records: tuple[LegacySourceRecord, ...] = ()
    quarantine_records: tuple[QuarantineRecord, ...] = ()
    family_counts: dict[str, int] = Field(default_factory=dict)
    counts_by_reason: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _enforce_accounting_and_freeze(self) -> "InventorySnapshot":
        # 1) aggregate accounting identity
        if (
            self.source_count
            != self.record_count + self.quarantined_count + self.deduplicated_count
        ):
            raise ValueError(
                "invalid inventory snapshot: source_count must equal "
                "record_count + quarantined_count + deduplicated_count"
            )
        if len(self.records) != self.record_count:
            raise ValueError(
                "invalid inventory snapshot: record_count does not match "
                "len(records)"
            )
        if len(self.quarantine_records) != self.quarantined_count:
            raise ValueError(
                "invalid inventory snapshot: quarantined_count does not match "
                "len(quarantine_records)"
            )

        # 2) canonical record ordering and duplicate-identity rejection
        if list(self.records) != sorted(self.records, key=_record_sort_key):
            raise ValueError(
                "invalid inventory snapshot: records are not in canonical order"
            )
        seen_identities: set[tuple[str, str, str, str, str]] = set()
        for record in self.records:
            key = record.identity_key
            if key in seen_identities:
                raise ValueError(
                    f"invalid inventory snapshot: duplicate record identity {key}"
                )
            seen_identities.add(key)

        # 3) canonical quarantine ordering; quarantine identities must never
        # duplicate inventoried identities (the builder either invents a
        # record or quarantines an identity, never both).  Identical
        # quarantine records themselves are legitimate builder output (e.g.
        # two payload-less rows produce the same record), so only ordering
        # and cross-set identity exclusion are enforced here.
        if list(self.quarantine_records) != sorted(
            self.quarantine_records, key=_quarantine_sort_key
        ):
            raise ValueError(
                "invalid inventory snapshot: quarantine_records are not in "
                "canonical order"
            )
        record_identities = {record.identity_key for record in self.records}
        for quarantined in self.quarantine_records:
            qkey = _quarantine_identity_key(quarantined)
            if qkey[:5] in record_identities:
                raise ValueError(
                    f"invalid inventory snapshot: quarantine identity {qkey[:5]} "
                    "also appears as an inventoried record"
                )

        # 4) family counts: closed vocabulary, positive, and exactly the truth
        actual_family_counts: dict[str, int] = {}
        for record in self.records:
            family = record.source_family.value
            actual_family_counts[family] = actual_family_counts.get(family, 0) + 1
        for family, count in self.family_counts.items():
            if family not in LEGACY_SOURCE_FAMILIES:
                raise ValueError(
                    f"invalid inventory snapshot: family {family!r} is not one "
                    "of the seven declared families"
                )
            if count < 1:
                raise ValueError(
                    f"invalid inventory snapshot: family count for {family!r} "
                    "must be a positive integer"
                )
        if dict(self.family_counts) != actual_family_counts:
            raise ValueError(
                "invalid inventory snapshot: family_counts do not match the records"
            )

        # 5) reason counts: closed vocabulary, positive, and exactly the truth
        actual_reason_counts: dict[str, int] = {}
        for quarantined in self.quarantine_records:
            for reason in quarantined.reasons:
                kind = reason.kind.value
                actual_reason_counts[kind] = actual_reason_counts.get(kind, 0) + 1
        for kind, count in self.counts_by_reason.items():
            if kind not in _REASON_KIND_VALUES:
                raise ValueError(
                    f"invalid inventory snapshot: reason {kind!r} is not in the "
                    "closed quarantine reason vocabulary"
                )
            if count < 1:
                raise ValueError(
                    f"invalid inventory snapshot: reason count for {kind!r} "
                    "must be a positive integer"
                )
        if dict(self.counts_by_reason) != actual_reason_counts:
            raise ValueError(
                "invalid inventory snapshot: counts_by_reason do not match the "
                "quarantine records"
            )

        # 6) deep-freeze the count maps so hashes can never drift
        object.__setattr__(
            self, "family_counts", _FrozenJsonDict(dict(self.family_counts))
        )
        object.__setattr__(
            self, "counts_by_reason", _FrozenJsonDict(dict(self.counts_by_reason))
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def inventory_sha256(self) -> str:
        return sha256(
            canonical_json(self.canonical_payload()).encode("utf-8")
        ).hexdigest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_count": self.source_count,
            "record_count": self.record_count,
            "quarantined_count": self.quarantined_count,
            "deduplicated_count": self.deduplicated_count,
            "records": [record.canonical_payload() for record in self.records],
            "quarantine": [
                record.canonical_payload() for record in self.quarantine_records
            ],
            "family_counts": dict(sorted(self.family_counts.items())),
            "counts_by_reason": dict(sorted(self.counts_by_reason.items())),
        }


# ---------------------------------------------------------------------------
# Normalization helpers for the builder
# ---------------------------------------------------------------------------

_IDENTITY_FIELDS = (
    "project_id",
    "source_family",
    "source_type",
    "source_id",
    "revision_token",
)


def _normalize_identity_text(value: Any) -> Optional[str]:
    """Normalize one identity field; ``None`` means invalid/empty/too long."""

    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text or len(text) > 512:
        return None
    return text


def _payload_internal_revision(payload: Any) -> Optional[str]:
    """Best-effort revision declared *inside* the payload, if any.

    Returns ``None`` when the payload carries no comparable revision key.
    """

    if not isinstance(payload, dict):
        return None
    for key in ("revision", "revision_token", "version"):
        raw = payload.get(key)
        if isinstance(raw, str):
            return " ".join(raw.strip().split()) or None
        if isinstance(raw, int):
            return str(raw)
    return None


def _validation_error_detail(exc: ValidationError) -> str:
    """Deterministic one-line summary of a payload validation failure."""

    issues = sorted(
        {
            "/".join(map(str, err.get("loc", ()))) + ":" + str(err.get("type", ""))
            for err in exc.errors()
        }
    )
    return "载荷校验失败: " + ", ".join(issues)


_REASON_KIND_VALUES: frozenset[str] = frozenset(
    kind.value for kind in QuarantineReasonKind
)


def _record_sort_key(record: LegacySourceRecord) -> tuple[str, str, str, str, str, str]:
    """Canonical record order: project, family, type, id, revision, payload."""

    return (
        record.project_id,
        record.source_family.value,
        record.source_type,
        record.source_id,
        record.revision_token.value,
        record.payload_sha256,
    )


def _quarantine_identity_key(
    quarantined: QuarantineRecord,
) -> tuple[str, str, str, str, str, Optional[str]]:
    """Identity + payload hash of a quarantine record (uniqueness key)."""

    return (
        quarantined.project_id,
        quarantined.source_family,
        quarantined.source_type,
        quarantined.source_id,
        quarantined.revision_token,
        quarantined.payload_sha256,
    )


def _quarantine_sort_key(
    quarantined: QuarantineRecord,
) -> tuple[str, str, str, str, str, str, str]:
    """Canonical quarantine order: identity + payload, then record id."""

    return _quarantine_identity_key(quarantined) + (quarantined.quarantine_id,)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _quarantine_for(
    *,
    project_id: str,
    source_family: str,
    source_type: str,
    source_id: str,
    revision_token: str,
    payload_sha256: Optional[str],
    kind: QuarantineReasonKind,
    detail_zh: str,
) -> QuarantineRecord:
    return QuarantineRecord(
        project_id=project_id,
        source_family=source_family,
        source_type=source_type,
        source_id=source_id,
        revision_token=revision_token,
        payload_sha256=payload_sha256,
        locator_sha256=_locator_hash_of(
            project_id=project_id,
            source_family=source_family,
            source_type=source_type,
            source_id=source_id,
            revision_token=revision_token,
            payload_sha256=payload_sha256,
        ),
        reasons=(quarantine_reason(kind),),
        detail_zh=detail_zh,
    )


def _quarantine_from_record(
    record: LegacySourceRecord,
    kind: QuarantineReasonKind,
    detail_zh: str,
) -> QuarantineRecord:
    return _quarantine_for(
        project_id=record.project_id,
        source_family=record.source_family.value,
        source_type=record.source_type,
        source_id=record.source_id,
        revision_token=record.revision_token.value,
        payload_sha256=record.payload_sha256,
        kind=kind,
        detail_zh=detail_zh,
    )


def _ingest(
    item: Union[Mapping[str, Any], LegacySourceRecord],
) -> tuple[Optional[LegacySourceRecord], Optional[QuarantineRecord]]:
    """Validate + normalize one caller-supplied item.

    Returns exactly one of (record, None) or (None, quarantine_record).  All
    quarantine details are derived from the item's own content — never from
    its input position — so results are permutation-stable.
    """

    if isinstance(item, LegacySourceRecord):
        # Already normalized and immutable by construction.
        return item, None

    if not isinstance(item, Mapping):
        return None, QuarantineRecord(
            project_id="unknown",
            source_family="unknown",
            source_type="unknown",
            source_id="unknown",
            revision_token="unknown",
            payload_sha256=None,
            locator_sha256=None,
            reasons=(quarantine_reason(QuarantineReasonKind.INCOMPLETE_RECORD),),
            detail_zh="来源记录必须是字典或 LegacySourceRecord，收到 "
            + type(item).__name__,
        )

    missing = sorted(name for name in _IDENTITY_FIELDS if name not in item)
    if missing:
        payload = item.get("payload")
        payload_sha256 = _payload_hash_of(payload) if payload is not None else None
        return None, _quarantine_for(
            project_id=_normalize_identity_text(item.get("project_id")) or "unknown",
            source_family=(
                _coerce_family(item.get("source_family")).value
                if _coerce_family(item.get("source_family")) is not None
                else "unknown"
            ),
            source_type=_normalize_identity_text(item.get("source_type")) or "unknown",
            source_id=_normalize_identity_text(item.get("source_id")) or "unknown",
            revision_token=(
                _normalize_identity_text(item.get("revision_token")) or "unknown"
            ),
            payload_sha256=payload_sha256,
            kind=QuarantineReasonKind.INCOMPLETE_RECORD,
            detail_zh="缺少必需字段: " + ", ".join(missing),
        )

    family = _coerce_family(item["source_family"])
    if family is None:
        payload = item.get("payload")
        payload_sha256 = _payload_hash_of(payload) if payload is not None else None
        return None, _quarantine_for(
            project_id=_normalize_identity_text(item.get("project_id")) or "unknown",
            source_family="unknown",
            source_type=_normalize_identity_text(item.get("source_type")) or "unknown",
            source_id=_normalize_identity_text(item.get("source_id")) or "unknown",
            revision_token=(
                _normalize_identity_text(item.get("revision_token")) or "unknown"
            ),
            payload_sha256=payload_sha256,
            kind=QuarantineReasonKind.UNSUPPORTED_FAMILY,
            detail_zh=(
                f"来源族 {item['source_family']!r} 不属于声明的七类来源族"
            ),
        )

    project_id = _normalize_identity_text(item.get("project_id"))
    source_type = _normalize_identity_text(item.get("source_type"))
    source_id = _normalize_identity_text(item.get("source_id"))
    revision_token = _normalize_identity_text(item.get("revision_token"))
    if None in (project_id, source_type, source_id, revision_token):
        payload = item.get("payload")
        payload_sha256 = _payload_hash_of(payload) if payload is not None else None
        bad = [
            name
            for name, value in (
                ("project_id", project_id),
                ("source_type", source_type),
                ("source_id", source_id),
                ("revision_token", revision_token),
            )
            if value is None
        ]
        return None, _quarantine_for(
            project_id=project_id or "unknown",
            source_family=family.value,
            source_type=source_type or "unknown",
            source_id=source_id or "unknown",
            revision_token=revision_token or "unknown",
            payload_sha256=payload_sha256,
            kind=QuarantineReasonKind.INCOMPLETE_RECORD,
            detail_zh="身份字段为空或无法归一化: " + ", ".join(bad),
        )

    payload = item.get("payload")
    if payload is None:
        return None, _quarantine_for(
            project_id=project_id,
            source_family=family.value,
            source_type=source_type,
            source_id=source_id,
            revision_token=revision_token,
            payload_sha256=None,
            kind=QuarantineReasonKind.INCOMPLETE_RECORD,
            detail_zh="载荷为空（payload 缺失或为 null）",
        )

    try:
        record = LegacySourceRecord(
            project_id=project_id,
            source_family=family,
            source_type=source_type,
            source_id=source_id,
            revision_token=SourceRevisionToken(value=revision_token),
            payload=payload,
        )
    except ValidationError as exc:
        return None, _quarantine_for(
            project_id=project_id,
            source_family=family.value,
            source_type=source_type,
            source_id=source_id,
            revision_token=revision_token,
            payload_sha256=_payload_hash_of(payload),
            kind=QuarantineReasonKind.INCOMPLETE_RECORD,
            detail_zh=_validation_error_detail(exc),
        )

    # Fail closed on a payload that self-declares a different revision.
    internal_revision = _payload_internal_revision(payload)
    if internal_revision is not None and internal_revision != revision_token:
        return None, _quarantine_from_record(
            record,
            QuarantineReasonKind.AMBIGUOUS_IDENTITY,
            detail_zh=(
                f"载荷内部声明的 revision {internal_revision!r} "
                f"与来源 revision_token {revision_token!r} 不一致"
            ),
        )

    return record, None


def build_inventory(
    records: Sequence[Union[Mapping[str, Any], LegacySourceRecord]],
) -> InventorySnapshot:
    """Build an immutable inventory snapshot from synthetic source records.

    Args:
        records: caller-supplied sequence of mappings (with keys
            ``project_id``, ``source_family``, ``source_type``, ``source_id``,
            ``revision_token``, ``payload``) or already-built
            :class:`LegacySourceRecord` instances.  No database, runtime
            singleton or semantic inference is involved.

    Returns:
        An :class:`InventorySnapshot` satisfying
        ``source_count == record_count + quarantined_count + deduplicated_count``.
        Record and quarantine ordering, family/reason counts and
        ``inventory_sha256`` are independent of input order.
    """

    by_identity: dict[tuple[str, str, str, str, str], list[LegacySourceRecord]] = {}
    quarantine_out: list[QuarantineRecord] = []

    for item in records:
        record, quarantined = _ingest(item)
        if quarantined is not None:
            quarantine_out.append(quarantined)
            continue
        assert record is not None
        by_identity.setdefault(record.identity_key, []).append(record)

    records_out: list[LegacySourceRecord] = []
    deduplicated = 0
    for key, group in by_identity.items():
        payload_hashes = {record.payload_sha256 for record in group}
        if len(payload_hashes) == 1:
            # Content-identical occurrences: one inventory record, the rest
            # are explicit deduplications (never a silent drop).
            records_out.append(group[0])
            deduplicated += len(group) - 1
        else:
            # Divergent payloads under one identity: fail closed — every
            # occurrence becomes an explicit quarantine candidate.
            for record in sorted(group, key=lambda r: r.payload_sha256):
                quarantine_out.append(
                    _quarantine_from_record(
                        record,
                        QuarantineReasonKind.DUPLICATE_CONFLICT,
                        detail_zh=(
                            f"同一来源身份出现 {len(group)} 条且载荷哈希不一致，"
                            "全部隔离，不静默选择"
                        ),
                    )
                )

    records_sorted = sorted(records_out, key=_record_sort_key)
    quarantine_sorted = sorted(quarantine_out, key=_quarantine_sort_key)

    family_counts: dict[str, int] = {}
    for record in records_sorted:
        family = record.source_family.value
        family_counts[family] = family_counts.get(family, 0) + 1

    counts_by_reason: dict[str, int] = {}
    for quarantined in quarantine_sorted:
        for reason in quarantined.reasons:
            kind = reason.kind.value
            counts_by_reason[kind] = counts_by_reason.get(kind, 0) + 1

    return InventorySnapshot(
        source_count=len(records),
        record_count=len(records_sorted),
        quarantined_count=len(quarantine_sorted),
        deduplicated_count=deduplicated,
        records=tuple(records_sorted),
        quarantine_records=tuple(quarantine_sorted),
        family_counts=family_counts,
        counts_by_reason=counts_by_reason,
    )
