"""Versioned v2→v3 mapping specification + deterministic dry-run mapper.

This module is the Worker 02 half of Task 1.10: it loads and strictly
validates the versioned seven-family mapping specification
(``config/medical_writing/protocol_v3/v2_v3_mapping.json``), then runs a pure,
deterministic dry-run over the Worker 01 read-only inventory.  It opens no
database, imports no runtime singleton and never mutates a source: inputs are
caller-supplied frozen :class:`LegacySourceRecord` instances (or an
:class:`InventorySnapshot`) and the spec; outputs are immutable, JSON-canonical
reports with an explicit disposition for every input row.

Design authority: frozen plan Task 1.10 and design §6.2 / §20 (shadow runs
strictly read-only; unmappable legacy data enters quarantine with an explicit
reason; nothing is silently dropped) and the closed quarantine vocabulary of
``quarantine.py``.  ``unsupported_type`` was reserved there for this mapping
phase: it is the single mapping-phase reason kind, used for both undeclared
source types and spec-declared ``quarantine`` outcomes — the spec's
``quarantine_detail_zh`` (or the fail-closed detail below) makes the exact
disposition explicit and auditable, and the closed vocabulary is never
extended at runtime.

Fail-closed contract (never weakened):

* every source record yields exactly one outcome: ``mapped`` or
  ``quarantined``; ``source_count == mapped_count + unmapped_count`` and
  ``quarantined_count == unmapped_count`` hold exactly;
* a source type not declared in the spec is quarantined as
  ``unsupported_type`` — the mapper never invents a target type, target id,
  semantic node or default field at runtime;
* **real source identity binding** — before any mapped outcome the declared
  identity/project/revision fields of the real contract location must match
  the record envelope; any missing, unsupported or mismatched value yields
  one explicit ``incomplete_record`` quarantine and **no lineage entry**, so
  a wrong project/id/revision can never be mapped under the envelope's
  identity (deterministic lineage is based on the real source identity);
* **exhaustive field disposition** — every real model field / DDL column /
  payload-model field of a mapped type is covered by a declared role, a
  field rule, or deep-frozen whole-payload preservation; ``omitted`` rules
  require a non-empty Chinese justification; the read-only drift verifier
  fails when a contract field is added without a disposition;
* a declared ``direct`` / ``preserved_legacy_only`` / ``derived`` rule whose
  source payload field is missing quarantines the record as
  ``incomplete_record`` (no ``None`` default is ever injected);
* every quarantine record keeps the original source hash, the immutable
  locator and the closed reason metadata (same shape as Worker 01).

Target storage scope: target identities are project-scoped.  Lineage keys
always embed the project id, so two projects can never collapse into the
same migration key or lineage; v3 target nodes are stored under the project
scope, which is what prevents equal ``target_id`` values in different
projects from colliding (proved by the cross-project isolation tests).

Determinism contract:

* records are processed in canonical order (project, family, type, source id,
  revision, payload hash), never input position, so any permutation of the
  input sequence yields an identical report;
* ``canonical_json`` (sorted keys, ``ensure_ascii=False``, compact) is the only
  serialisation used for hashing, so Chinese payloads round-trip unescaped and
  byte-stably;
* ``target_sha256`` (target type + id + fields) and ``lineage_id`` (migration
  key + mapping version + revision + payload + target hash) are computed,
  never caller-supplied, so they cannot diverge from content;
* composite identity/project/revision binding uses the canonical JSON array
  of the ordered normalized scalars — never ambiguous string concatenation —
  and scalar int/string/date-like values normalize deterministically.

Idempotent lineage contract:

* ``migration_key`` = (project, family, type, source id) — the identity that
  survives revisions; ``lineage_key`` = migration key + mapping version;
* a record whose ``lineage_key`` + revision + payload + target hash was already
  seen in ``prior_lineage`` is an *exact replay*: it emits the same target
  identity/hash, marks ``replayed`` and appends **no** new lineage entry (no
  extra semantic effect);
* the same lineage key + same revision with a *different* payload is a
  *conflicting replay*: it fails closed into a ``duplicate_conflict``
  quarantine record and never touches the prior entry;
* a changed revision creates a *new child* lineage entry whose
  ``parent_lineage_id`` points at the prior result; the prior entry is
  immutable and never overwritten, so the full history is preserved in
  ``lineage_entries``;
* ``lineage_entries`` in the report is the *full* carried-forward lineage
  (prior + new), canonically sorted, so chaining runs is simply
  ``run(records, spec, prior_lineage=previous.lineage_entries)``.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from hashlib import sha256
from pathlib import Path
from types import ModuleType
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

from .migration_inventory import (
    LEGACY_SOURCE_FAMILIES,
    InventorySnapshot,
    LegacySourceRecord,
)
from .quarantine import (
    QuarantineReasonKind,
    QuarantineRecord,
    quarantine_reason,
)

__all__ = [
    "CONTRACT_VERIFICATION_SCHEMA_VERSION",
    "DRY_RUN_SCHEMA_VERSION",
    "DryRunReport",
    "LINEAGE_SCHEMA_VERSION",
    "MAPPING_SCHEMA_VERSION",
    "MappedOutcome",
    "MappingContractIssue",
    "MappingContractSpec",
    "MappingContractVerification",
    "MappingFamilySpec",
    "MappingFieldRule",
    "MappingLineageEntry",
    "MappingLineageError",
    "MappingOutcome",
    "MappingSpec",
    "MappingSpecError",
    "MappingTypeSpec",
    "QuarantinedOutcome",
    "load_mapping_spec",
    "parse_mapping_spec",
    "run_mapping_dry_run",
    "verify_mapping_spec_contracts",
]

MAPPING_SCHEMA_VERSION = "mw_v2_v3_mapping_v1"
LINEAGE_SCHEMA_VERSION = "mw_v2_v3_lineage_v1"
DRY_RUN_SCHEMA_VERSION = "mw_v2_v3_dry_run_v1"
CONTRACT_VERIFICATION_SCHEMA_VERSION = "mw_v2_v3_contract_verification_v1"

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

# Deterministic separator for the declared ``string_join`` derive op.
JOIN_SEPARATOR = "::"

_OUTCOME_VALUES = frozenset({"direct", "derived", "preserved_legacy_only", "quarantine"})
_RULE_KIND_VALUES = frozenset(
    {"direct", "derived", "preserved_legacy_only", "omitted", "whole_payload"}
)


class MappingSpecError(ValueError):
    """Raised when a mapping specification violates the closed schema."""


class MappingLineageError(ValueError):
    """Raised when caller-supplied prior lineage is invalid or mismatched."""


# ---------------------------------------------------------------------------
# Frozen JSON containers (same discipline as Worker 01: serialise like plain
# JSON but reject every mutation API so report hashes can never drift).
# ---------------------------------------------------------------------------


class _FrozenJsonDict(dict[str, JsonValue]):
    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("legacy mapping target field mapping is immutable")

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
    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("legacy mapping target field list is immutable")

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
    if isinstance(value, dict):
        return _FrozenJsonDict(
            {key: _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _FrozenJsonList(_freeze_json_value(item) for item in value)
    return value


class _FrozenSpecDict(dict[str, Any]):
    """Deeply immutable dict backing ``MappingSpec.families``.

    Every mutation API raises ``TypeError`` so a validated spec and its
    ``spec_sha256`` can never drift after construction.  Values are frozen
    Pydantic models whose own containers (tuples) are already immutable, so
    freezing this one mapping closes the last mutable path into the spec.
    Serialisation behaves like a plain dict.
    """

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("mapping spec families mapping is immutable")

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


# ---------------------------------------------------------------------------
# Hashing helpers (computed, never caller-supplied)
# ---------------------------------------------------------------------------


def _target_sha256(
    target_type: str, target_id: str, fields: Mapping[str, JsonValue]
) -> str:
    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "fields": dict(sorted(fields.items())),
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _lineage_id(
    *,
    mapping_version: str,
    migration_key: tuple[str, str, str, str],
    revision_token: str,
    payload_sha256: str,
    target_sha256: str,
) -> str:
    payload = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "mapping_version": mapping_version,
        "migration_key": list(migration_key),
        "revision_token": revision_token,
        "payload_sha256": payload_sha256,
        "target_sha256": target_sha256,
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _locator_hash_of(
    *,
    project_id: str,
    source_family: str,
    source_type: str,
    source_id: str,
    revision_token: str,
    payload_sha256: Optional[str],
) -> Optional[str]:
    """Locator hash mirroring Worker 01's ImmutableLocator payload shape."""

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
# Mapping specification models (extra="forbid" everywhere: unknown keys and
# unknown rule/outcome/derive/basis values all fail closed at load time).
# ---------------------------------------------------------------------------

_NonEmpty = Annotated[str, StringConstraints(min_length=1)]

_SOURCE_CONTRACT_KINDS = frozenset(
    {"pydantic_model", "sqlite_table", "jsonl_snapshot"}
)
_CONTRACT_KIND_PREFIX = {
    "pydantic_model": "models",
    "sqlite_table": "sqlite",
    "jsonl_snapshot": "jsonl",
}


class MappingContractSpec(BaseModel):
    """Explicit real-contract locator anchoring one declared source type.

    Every production ``source_type`` must resolve to a real, checked-in v2
    contract — a Pydantic model symbol, a SQLite table, or an immutable
    JSONL snapshot — declared here with enough closed information to answer
    identity, revision, payload-container and field-rule questions *without
    opening a live database*:

    * ``pydantic_model``: ``source_file`` + ``symbol`` name the model class;
      ``identity_fields`` / ``project_scope_fields`` / ``revision_fields``
      name the physical model fields; field rules reference actual top-level
      model fields.
    * ``sqlite_table``: ``source_file`` + ``table`` name the table; the same
      field groups name physical columns; when rows store a Pydantic object
      in a JSON column, ``payload_container`` (e.g. ``payload_json``) plus
      ``payload_model`` / ``payload_model_file`` declare the container column
      and the payload model symbol — nested payload fields are never
      pretended to be physical columns.
    * ``jsonl_snapshot``: ``source_file`` + ``snapshot_file`` +
      ``snapshot_constants`` bind to immutable snapshot constants (e.g.
      ``SNAPSHOT_PATH`` / ``MANIFEST_PATH`` in ``medical_writing_company_corpus.py``).

    ``derived_source_type`` mechanically derives the canonical ``source_type``
    (``models.<symbol>`` / ``sqlite.<table>`` / ``jsonl.<snapshot_file>``);
    the owning type spec must carry exactly that value, so generic toy aliases
    can never enter the production spec.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["pydantic_model", "sqlite_table", "jsonl_snapshot"]
    source_file: _NonEmpty
    symbol: Optional[_NonEmpty] = None
    table: Optional[_NonEmpty] = None
    snapshot_file: Optional[_NonEmpty] = None
    snapshot_constants: tuple[_NonEmpty, ...] = ()
    payload_model: Optional[_NonEmpty] = None
    payload_model_file: Optional[_NonEmpty] = None
    payload_container: Optional[_NonEmpty] = None
    identity_fields: tuple[_NonEmpty, ...] = Field(min_length=1)
    project_scope_fields: tuple[_NonEmpty, ...] = ()
    revision_fields: tuple[_NonEmpty, ...] = ()

    @property
    def derived_source_type(self) -> str:
        if self.kind == "pydantic_model":
            return f"models.{self.symbol}"
        if self.kind == "sqlite_table":
            return f"sqlite.{self.table}"
        snapshot = self.snapshot_file or ""
        if snapshot.endswith(".jsonl"):
            snapshot = snapshot[: -len(".jsonl")]
        return f"jsonl.{snapshot}"

    @model_validator(mode="after")
    def _enforce_kind_shape(self) -> "MappingContractSpec":
        if self.kind == "pydantic_model":
            if self.symbol is None:
                raise ValueError("pydantic_model contract requires symbol")
            for name, value in (
                ("table", self.table),
                ("snapshot_file", self.snapshot_file),
                ("snapshot_constants", self.snapshot_constants),
                ("payload_model", self.payload_model),
                ("payload_model_file", self.payload_model_file),
                ("payload_container", self.payload_container),
            ):
                if value:
                    raise ValueError(
                        f"pydantic_model contract must not carry {name}"
                    )
        elif self.kind == "sqlite_table":
            if self.table is None:
                raise ValueError("sqlite_table contract requires table")
            for name, value in (
                ("symbol", self.symbol),
                ("snapshot_file", self.snapshot_file),
                ("snapshot_constants", self.snapshot_constants),
            ):
                if value:
                    raise ValueError(f"sqlite_table contract must not carry {name}")
            if self.payload_container is not None:
                if self.payload_model is None or self.payload_model_file is None:
                    raise ValueError(
                        "sqlite_table contract with payload_container requires "
                        "payload_model and payload_model_file"
                    )
            elif self.payload_model is not None or self.payload_model_file is not None:
                raise ValueError(
                    "sqlite_table contract without payload_container must not "
                    "declare payload_model/payload_model_file"
                )
        else:  # jsonl_snapshot
            if self.snapshot_file is None or not self.snapshot_constants:
                raise ValueError(
                    "jsonl_snapshot contract requires snapshot_file and "
                    "snapshot_constants"
                )
            for name, value in (
                ("symbol", self.symbol),
                ("table", self.table),
                ("payload_model", self.payload_model),
                ("payload_model_file", self.payload_model_file),
                ("payload_container", self.payload_container),
            ):
                if value:
                    raise ValueError(
                        f"jsonl_snapshot contract must not carry {name}"
                    )
        for group_name, group in (
            ("identity_fields", self.identity_fields),
            ("project_scope_fields", self.project_scope_fields),
            ("revision_fields", self.revision_fields),
        ):
            if len(set(group)) != len(group):
                raise ValueError(
                    f"contract {group_name} must not contain duplicates"
                )
        return self


class IdentityRuleSpec(BaseModel):
    """Declared target-identity rule: basis + deterministic prefix.

    The mapper enforces real source identity binding first (see
    :func:`run_mapping_dry_run`): the declared identity/project/revision
    fields of the source contract must match the record envelope, and only
    then is the target id built as ``prefix + canonical_bound_identity``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    basis: _NonEmpty
    prefix: _NonEmpty


class MappingFieldRule(BaseModel):
    """One declared per-field rule.  Shape depends on ``kind``:

    * ``direct`` / ``preserved_legacy_only``: source_field -> target_field;
    * ``derived``: derive op (``string_join`` needs ``source_fields``,
      ``revision_token`` / ``payload_sha256`` need none) -> target_field;
    * ``omitted``: source_field is declared dropped from the target and must
      carry a non-empty Chinese justification (``omission_reason_zh``) —
      a bare omission is a silent drop and fails validation;
    * ``whole_payload``: the entire real payload (Pydantic model dump) or the
      declared ``payload_container`` value (SQLite payload model dump) is
      deep-frozen and carried into ``target_field``. ``covered_fields`` must
      explicitly enumerate that model's complete field set so contract drift
      cannot be silently absorbed by a generic preserve-all declaration.

    ``source_scope`` says where ``source_field``/``source_fields`` live:

    * ``payload`` (default) — a Pydantic model field / JSONL row field, or
      (for SQLite rows) a field of the declared ``payload_model`` inside the
      ``payload_container`` column;
    * ``physical`` — an actual SQLite table column of the declared table.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "direct", "derived", "preserved_legacy_only", "omitted", "whole_payload"
    ]
    source_scope: Literal["physical", "payload"] = "payload"
    source_field: Optional[_NonEmpty] = None
    target_field: Optional[_NonEmpty] = None
    derive: Optional[_NonEmpty] = None
    source_fields: tuple[_NonEmpty, ...] = ()
    covered_fields: tuple[_NonEmpty, ...] = ()
    omission_reason_zh: str = ""

    @model_validator(mode="after")
    def _enforce_rule_shape(self) -> "MappingFieldRule":
        if self.kind != "whole_payload" and self.covered_fields:
            raise ValueError(
                "covered_fields is only allowed on a whole_payload field rule"
            )
        if self.kind in ("direct", "preserved_legacy_only"):
            if self.source_field is None or self.target_field is None:
                raise ValueError(
                    f"field rule kind {self.kind!r} requires source_field and "
                    "target_field"
                )
            if self.derive is not None or self.source_fields:
                raise ValueError(
                    f"field rule kind {self.kind!r} must not carry derive or "
                    "source_fields"
                )
        elif self.kind == "derived":
            if self.derive is None or self.target_field is None:
                raise ValueError(
                    "derived field rule requires derive and target_field"
                )
            if self.source_field is not None:
                raise ValueError(
                    "derived field rule must not carry source_field"
                )
            if self.derive == "string_join" and not self.source_fields:
                raise ValueError(
                    "string_join derived rule requires non-empty source_fields"
                )
            if self.derive != "string_join" and self.source_fields:
                raise ValueError(
                    f"derived rule {self.derive!r} must not carry source_fields"
                )
        elif self.kind == "omitted":
            if self.source_field is None:
                raise ValueError("omitted field rule requires source_field")
            if self.target_field is not None or self.derive is not None or self.source_fields:
                raise ValueError(
                    "omitted field rule must not carry target_field, derive or "
                    "source_fields"
                )
            if not self.omission_reason_zh.strip():
                raise ValueError(
                    "omitted field rule requires a non-empty omission_reason_zh "
                    "(a bare omission is a silent drop)"
                )
        else:  # whole_payload
            if self.target_field is None:
                raise ValueError("whole_payload field rule requires target_field")
            if (
                self.source_field is not None
                or self.derive is not None
                or self.source_fields
            ):
                raise ValueError(
                    "whole_payload field rule must not carry source_field, "
                    "derive or source_fields"
                )
            if self.source_scope == "physical":
                raise ValueError(
                    "whole_payload field rule must not declare physical scope"
                )
            if not self.covered_fields:
                raise ValueError(
                    "whole_payload field rule requires explicit covered_fields"
                )
            if len(set(self.covered_fields)) != len(self.covered_fields):
                raise ValueError(
                    "whole_payload covered_fields must not contain duplicates"
                )
        return self


class MappingTypeSpec(BaseModel):
    """One declared source type: real-contract anchor + outcome + (for
    non-quarantine) target type, identity rule and field rules.

    ``source_type`` must be exactly the mechanically derived identifier of
    ``source_contract`` (``models.<symbol>`` / ``sqlite.<table>`` /
    ``jsonl.<snapshot_file>``), so generic toy aliases fail closed at load
    time.  Field-rule ``source_scope`` values must match the contract kind,
    and SQLite sources must derive target identity from the physical
    ``source_id`` (never a fabricated payload path).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: _NonEmpty
    outcome: Literal["direct", "derived", "preserved_legacy_only", "quarantine"]
    source_contract: MappingContractSpec
    target_type: Optional[_NonEmpty] = None
    identity_rule: Optional[IdentityRuleSpec] = None
    field_rules: tuple[MappingFieldRule, ...] = ()
    quarantine_detail_zh: str = ""

    @model_validator(mode="after")
    def _enforce_outcome_shape(self) -> "MappingTypeSpec":
        derived = self.source_contract.derived_source_type
        contract = self.source_contract
        if self.source_type != derived:
            raise ValueError(
                f"source_type {self.source_type!r} is not the mechanically "
                f"derived identifier {derived!r} of its source_contract; "
                "generic aliases are not allowed"
            )
        if self.outcome == "quarantine":
            if self.target_type is not None or self.identity_rule is not None or self.field_rules:
                raise ValueError(
                    f"quarantine outcome for source type {self.source_type!r} "
                    "must not declare target_type, identity_rule or field_rules"
                )
            if not self.quarantine_detail_zh:
                raise ValueError(
                    f"quarantine outcome for source type {self.source_type!r} "
                    "must declare a non-empty quarantine_detail_zh"
                )
        else:
            if self.target_type is None or self.identity_rule is None:
                raise ValueError(
                    f"outcome {self.outcome!r} for source type "
                    f"{self.source_type!r} requires target_type and identity_rule"
                )
            if self.quarantine_detail_zh:
                raise ValueError(
                    f"non-quarantine outcome for source type {self.source_type!r} "
                    "must not carry quarantine_detail_zh"
                )
            if self.identity_rule.basis != "source_id":
                raise ValueError(
                    f"non-quarantine source type {self.source_type!r} must use "
                    "the source_id identity basis (real identity binding)"
                )
            # A mapped type must independently bind project, identity and
            # revision from its real contract location; a source that cannot
            # (e.g. a nested model with no project field) must be declared
            # quarantine instead of pretending a weak identity is global.
            if not contract.identity_fields:
                raise ValueError(
                    f"non-quarantine source type {self.source_type!r} must "
                    "declare non-empty contract identity_fields"
                )
            if not contract.project_scope_fields:
                raise ValueError(
                    f"non-quarantine source type {self.source_type!r} must "
                    "declare non-empty contract project_scope_fields "
                    "(independent project binding)"
                )
            if not contract.revision_fields:
                raise ValueError(
                    f"non-quarantine source type {self.source_type!r} must "
                    "declare non-empty contract revision_fields "
                    "(independent revision binding)"
                )
        whole_rules = [rule for rule in self.field_rules if rule.kind == "whole_payload"]
        if len(whole_rules) > 1:
            raise ValueError(
                f"source type {self.source_type!r} declares more than one "
                "whole_payload rule"
            )
        if whole_rules:
            if contract.kind == "sqlite_table" and contract.payload_container is None:
                raise ValueError(
                    f"whole_payload rule of {self.source_type!r} requires a "
                    "payload_container/payload_model on the sqlite contract"
                )
            if contract.kind == "jsonl_snapshot":
                raise ValueError(
                    f"whole_payload rule is not supported for jsonl_snapshot "
                    f"source type {self.source_type!r}"
                )
        if contract.kind == "sqlite_table":
            if self.identity_rule is not None and self.identity_rule.basis != "source_id":
                raise ValueError(
                    f"sqlite source type {self.source_type!r} must use the "
                    "source_id identity basis (physical identity column)"
                )
            for rule in self.field_rules:
                reads_fields = (
                    rule.kind in ("direct", "preserved_legacy_only", "omitted")
                    or rule.derive == "string_join"
                )
                if (
                    rule.source_scope == "payload"
                    and contract.payload_container is None
                    and reads_fields
                ):
                    raise ValueError(
                        f"sqlite source type {self.source_type!r} declares a "
                        "payload-scope rule but no payload_container/payload_model"
                    )
        else:
            for rule in self.field_rules:
                if rule.source_scope == "physical":
                    raise ValueError(
                        f"{contract.kind} source type {self.source_type!r} must "
                        "not declare physical-scope field rules"
                    )
        return self


class MappingFamilySpec(BaseModel):
    """One declared source family with its closed type allow-list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family_label_zh: _NonEmpty
    types: tuple[MappingTypeSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_duplicate_source_types(self) -> "MappingFamilySpec":
        seen: set[str] = set()
        for type_spec in self.types:
            if type_spec.source_type in seen:
                raise ValueError(
                    f"duplicate source_type {type_spec.source_type!r} in family"
                )
            seen.add(type_spec.source_type)
        return self


class MappingSpec(BaseModel):
    """The complete versioned mapping specification.

    Self-validates: exact seven-family coverage, closed top-level
    vocabularies (identity rule bases, derive ops) with no duplicates, every
    declared basis/derive actually inside those vocabularies, and no duplicate
    field-rule targets/sources within a type.  Any deviation raises a
    ``ValidationError`` (surfaced by the loader as :class:`MappingSpecError`),
    so a spec can never silently acquire unknown rules or drop a family.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_v2_v3_mapping_v1"] = MAPPING_SCHEMA_VERSION
    mapping_version: _NonEmpty
    generated_for: _NonEmpty
    authority: _NonEmpty
    identity_rule_bases: tuple[_NonEmpty, ...] = Field(min_length=1)
    derive_ops: tuple[_NonEmpty, ...] = Field(min_length=1)
    families: dict[str, MappingFamilySpec]

    @field_validator("identity_rule_bases", "derive_ops")
    @classmethod
    def _reject_duplicate_vocabulary_entries(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("vocabulary lists must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _enforce_seven_family_coverage(self) -> "MappingSpec":
        declared = set(self.families)
        expected = set(LEGACY_SOURCE_FAMILIES)
        missing = sorted(expected - declared)
        extra = sorted(declared - expected)
        if missing or extra:
            parts = []
            if missing:
                parts.append("missing families: " + ", ".join(missing))
            if extra:
                parts.append("unknown families: " + ", ".join(extra))
            raise ValueError("mapping spec violates seven-family coverage; " + "; ".join(parts))

        bases = set(self.identity_rule_bases)
        derives = set(self.derive_ops)
        for family, family_spec in self.families.items():
            for type_spec in family_spec.types:
                if type_spec.identity_rule is not None:
                    if type_spec.identity_rule.basis not in bases:
                        raise ValueError(
                            f"identity basis {type_spec.identity_rule.basis!r} "
                            f"of {family}/{type_spec.source_type} is not declared "
                            "in identity_rule_bases"
                        )
                seen_targets: set[str] = set()
                seen_sources: set[str] = set()
                for rule in type_spec.field_rules:
                    if rule.derive is not None and rule.derive not in derives:
                        raise ValueError(
                            f"derive op {rule.derive!r} of "
                            f"{family}/{type_spec.source_type} is not declared in "
                            "derive_ops"
                        )
                    if rule.target_field is not None:
                        if rule.target_field in seen_targets:
                            raise ValueError(
                                f"duplicate target_field {rule.target_field!r} in "
                                f"{family}/{type_spec.source_type}"
                            )
                        seen_targets.add(rule.target_field)
                    if rule.source_field is not None:
                        if rule.source_field in seen_sources:
                            raise ValueError(
                                f"duplicate source_field {rule.source_field!r} in "
                                f"{family}/{type_spec.source_type}"
                            )
                        seen_sources.add(rule.source_field)
        return self

    @model_validator(mode="after")
    def _deep_freeze_families(self) -> "MappingSpec":
        # families is the only plain-mapping container left in the spec; its
        # values are frozen Pydantic models whose own containers are tuples.
        # Freezing the mapping closes every mutable path into spec_sha256.
        object.__setattr__(self, "families", _FrozenSpecDict(self.families))
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spec_sha256(self) -> str:
        return sha256(
            canonical_json(self.canonical_payload()).encode("utf-8")
        ).hexdigest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mapping_version": self.mapping_version,
            "generated_for": self.generated_for,
            "authority": self.authority,
            "identity_rule_bases": list(self.identity_rule_bases),
            "derive_ops": list(self.derive_ops),
            "families": {
                family: {
                    "family_label_zh": family_spec.family_label_zh,
                    "types": [
                        {
                            "source_type": type_spec.source_type,
                            "outcome": type_spec.outcome,
                            "source_contract": {
                                "kind": type_spec.source_contract.kind,
                                "source_file": type_spec.source_contract.source_file,
                                "symbol": type_spec.source_contract.symbol,
                                "table": type_spec.source_contract.table,
                                "snapshot_file": type_spec.source_contract.snapshot_file,
                                "snapshot_constants": list(
                                    type_spec.source_contract.snapshot_constants
                                ),
                                "payload_model": type_spec.source_contract.payload_model,
                                "payload_model_file": (
                                    type_spec.source_contract.payload_model_file
                                ),
                                "payload_container": (
                                    type_spec.source_contract.payload_container
                                ),
                                "identity_fields": list(
                                    type_spec.source_contract.identity_fields
                                ),
                                "project_scope_fields": list(
                                    type_spec.source_contract.project_scope_fields
                                ),
                                "revision_fields": list(
                                    type_spec.source_contract.revision_fields
                                ),
                            },
                            "target_type": type_spec.target_type,
                            "identity_rule": (
                                {
                                    "basis": type_spec.identity_rule.basis,
                                    "prefix": type_spec.identity_rule.prefix,
                                }
                                if type_spec.identity_rule is not None
                                else None
                            ),
                            "field_rules": [
                                {
                                    "kind": rule.kind,
                                    "source_scope": rule.source_scope,
                                    "source_field": rule.source_field,
                                    "target_field": rule.target_field,
                                    "derive": rule.derive,
                                    "source_fields": list(rule.source_fields),
                                    "covered_fields": list(rule.covered_fields),
                                    "omission_reason_zh": rule.omission_reason_zh,
                                }
                                for rule in type_spec.field_rules
                            ],
                            "quarantine_detail_zh": type_spec.quarantine_detail_zh,
                        }
                        for type_spec in family_spec.types
                    ],
                }
                for family, family_spec in sorted(self.families.items())
            },
        }


def _spec_validation_detail(exc: ValidationError) -> str:
    issues = sorted(
        {
            "/".join(map(str, err.get("loc", ()))) + ":" + str(err.get("type", ""))
            + (":" + str(err.get("msg", "")) if err.get("msg") else "")
            for err in exc.errors()
        }
    )
    return "映射规范校验失败: " + "; ".join(issues)


def parse_mapping_spec(raw: Any) -> MappingSpec:
    """Strictly parse a raw JSON value into a validated :class:`MappingSpec`.

    Raises :class:`MappingSpecError` (deterministic one-line message) on any
    structural or semantic violation — unknown keys, unknown rules/outcomes,
    duplicates, missing family coverage or undeclared basis/derive ops.
    """

    if not isinstance(raw, Mapping):
        raise MappingSpecError(
            "映射规范必须是 JSON 对象，收到 " + type(raw).__name__
        )
    try:
        return MappingSpec.model_validate(raw)
    except ValidationError as exc:
        raise MappingSpecError(_spec_validation_detail(exc)) from exc


def load_mapping_spec(path: Union[str, Path]) -> MappingSpec:
    """Load and strictly validate the versioned mapping spec from ``path``."""

    import json

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MappingSpecError(
            f"无法读取映射规范文件 {path}: {exc}"
        ) from exc
    return parse_mapping_spec(raw)


# ---------------------------------------------------------------------------
# Lineage entries and per-record outcomes
# ---------------------------------------------------------------------------


class MappingLineageEntry(BaseModel):
    """One immutable lineage node: a (key, version, revision, payload) binding.

    ``lineage_id`` is computed from the node's own content (migration key +
    mapping version + revision + payload hash + target hash) and is stable
    across runs; ``parent_lineage_id`` is the stored pointer to the prior
    result and never participates in the identity hash, so replay detection is
    content-based while the chain stays visible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_v2_v3_lineage_v1"] = LINEAGE_SCHEMA_VERSION
    mapping_version: _NonEmpty
    migration_key: tuple[_NonEmpty, _NonEmpty, _NonEmpty, _NonEmpty]
    revision_token: _NonEmpty
    payload_sha256: Sha256Hex
    target_type: _NonEmpty
    target_id: _NonEmpty
    target_sha256: Sha256Hex
    parent_lineage_id: Optional[Sha256Hex] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lineage_id(self) -> str:
        return _lineage_id(
            mapping_version=self.mapping_version,
            migration_key=self.migration_key,
            revision_token=self.revision_token,
            payload_sha256=self.payload_sha256,
            target_sha256=self.target_sha256,
        )

    @property
    def lineage_key(self) -> tuple[str, str, str, str, str]:
        return self.migration_key + (self.mapping_version,)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mapping_version": self.mapping_version,
            "migration_key": list(self.migration_key),
            "revision_token": self.revision_token,
            "payload_sha256": self.payload_sha256,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_sha256": self.target_sha256,
            "parent_lineage_id": self.parent_lineage_id,
            "lineage_id": self.lineage_id,
        }


class MappedOutcome(BaseModel):
    """Disposition of one mapped source record.

    ``target_sha256`` and ``lineage_id`` are computed from content.  ``fields``
    is deep-frozen at construction so report hashes can never drift; the
    stored values are copies, so mutating the result never touches the source
    payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["mapped"] = "mapped"
    mapping_version: _NonEmpty
    project_id: _NonEmpty
    source_family: _NonEmpty
    source_type: _NonEmpty
    source_id: _NonEmpty
    revision_token: _NonEmpty
    payload_sha256: Sha256Hex
    target_type: _NonEmpty
    target_id: _NonEmpty
    fields: dict[str, JsonValue] = Field(default_factory=dict)
    lineage_id: Sha256Hex
    parent_lineage_id: Optional[Sha256Hex] = None
    replayed: bool = False

    @model_validator(mode="after")
    def _freeze_fields(self) -> "MappedOutcome":
        # Pydantic re-parses the fields dict into plain containers during
        # validation, so freeze the values again recursively: every nested
        # mapping/list that could affect target_sha256 rejects mutation.
        object.__setattr__(
            self, "fields", _FrozenJsonDict(dict(self.fields))
        )
        frozen: dict[str, JsonValue] = {}
        for key, value in self.fields.items():
            frozen[key] = _freeze_json_value(value)
        object.__setattr__(self, "fields", _FrozenJsonDict(frozen))
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_sha256(self) -> str:
        return _target_sha256(self.target_type, self.target_id, self.fields)

    @property
    def migration_key(self) -> tuple[str, str, str, str]:
        return (
            self.project_id,
            self.source_family,
            self.source_type,
            self.source_id,
        )

    @property
    def source_identity_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.project_id,
            self.source_family,
            self.source_type,
            self.source_id,
            self.revision_token,
            self.payload_sha256,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "mapping_version": self.mapping_version,
            "project_id": self.project_id,
            "source_family": self.source_family,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "revision_token": self.revision_token,
            "payload_sha256": self.payload_sha256,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "fields": dict(sorted(self.fields.items())),
            "target_sha256": self.target_sha256,
            "lineage_id": self.lineage_id,
            "parent_lineage_id": self.parent_lineage_id,
            "replayed": self.replayed,
        }


class QuarantinedOutcome(BaseModel):
    """Disposition of one unmapped source record: exactly one quarantine
    record, preserving original identity, source hash and locator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["quarantined"] = "quarantined"
    quarantine_record: QuarantineRecord

    @property
    def source_identity_key(self) -> tuple[str, str, str, str, str, Optional[str]]:
        record = self.quarantine_record
        return (
            record.project_id,
            record.source_family,
            record.source_type,
            record.source_id,
            record.revision_token,
            record.payload_sha256,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "quarantine_record": self.quarantine_record.canonical_payload(),
        }


MappingOutcome = Annotated[
    Union[MappedOutcome, QuarantinedOutcome],
    Field(discriminator="disposition"),
]


# ---------------------------------------------------------------------------
# Dry-run report
# ---------------------------------------------------------------------------


def _lineage_sort_key(entry: MappingLineageEntry) -> tuple[str, str, str]:
    return (
        *entry.lineage_key,
        entry.revision_token,
        entry.lineage_id,
    )


def _outcome_sort_key(
    outcome: Union[MappedOutcome, QuarantinedOutcome],
) -> tuple[str, ...]:
    return tuple(outcome.source_identity_key)


class DryRunReport(BaseModel):
    """Immutable, self-validating result of one deterministic dry run.

    Invariants enforced at construction (never violated):

    * ``source_count == mapped_count + unmapped_count``;
    * ``quarantined_count == unmapped_count`` and every unmapped record has
      exactly one quarantine record;
    * ``replayed_count`` equals the number of exact-replay mapped outcomes;
    * ``outcomes`` / ``quarantine_records`` / ``lineage_entries`` are in
      canonical order; ``lineage_entries`` carries no duplicate lineage id;
    * ``counts_by_reason`` is the exact per-kind quarantine tally over the
      closed vocabulary and is deep-frozen afterwards.

    ``lineage_entries`` is the full carried-forward lineage (prior + new), so
    the next run simply passes this report's entries as ``prior_lineage``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_v2_v3_dry_run_v1"] = DRY_RUN_SCHEMA_VERSION
    mapping_version: _NonEmpty
    source_count: int = Field(ge=0)
    mapped_count: int = Field(ge=0)
    unmapped_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)
    outcomes: tuple[MappingOutcome, ...] = ()
    quarantine_records: tuple[QuarantineRecord, ...] = ()
    lineage_entries: tuple[MappingLineageEntry, ...] = ()
    counts_by_reason: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _enforce_invariants_and_freeze(self) -> "DryRunReport":
        if self.source_count != self.mapped_count + self.unmapped_count:
            raise ValueError(
                "invalid dry-run report: source_count must equal "
                "mapped_count + unmapped_count"
            )
        if self.quarantined_count != self.unmapped_count:
            raise ValueError(
                "invalid dry-run report: quarantined_count must equal "
                "unmapped_count"
            )
        mapped = [
            outcome
            for outcome in self.outcomes
            if isinstance(outcome, MappedOutcome)
        ]
        quarantined = [
            outcome
            for outcome in self.outcomes
            if isinstance(outcome, QuarantinedOutcome)
        ]
        if len(mapped) != self.mapped_count:
            raise ValueError(
                "invalid dry-run report: mapped_count does not match outcomes"
            )
        if len(quarantined) != self.quarantined_count:
            raise ValueError(
                "invalid dry-run report: quarantined_count does not match outcomes"
            )
        if sum(1 for outcome in mapped if outcome.replayed) != self.replayed_count:
            raise ValueError(
                "invalid dry-run report: replayed_count does not match outcomes"
            )
        if list(self.outcomes) != sorted(self.outcomes, key=_outcome_sort_key):
            raise ValueError(
                "invalid dry-run report: outcomes are not in canonical order"
            )
        if tuple(record for outcome in quarantined for record in (outcome.quarantine_record,)) != self.quarantine_records:
            raise ValueError(
                "invalid dry-run report: quarantine_records do not match outcomes"
            )
        if list(self.quarantine_records) != sorted(
            self.quarantine_records,
            key=lambda record: (
                record.project_id,
                record.source_family,
                record.source_type,
                record.source_id,
                record.revision_token,
                record.payload_sha256,
                record.quarantine_id,
            ),
        ):
            raise ValueError(
                "invalid dry-run report: quarantine_records are not in "
                "canonical order"
            )
        if list(self.lineage_entries) != sorted(
            self.lineage_entries, key=_lineage_sort_key
        ):
            raise ValueError(
                "invalid dry-run report: lineage_entries are not in canonical order"
            )
        lineage_ids = [entry.lineage_id for entry in self.lineage_entries]
        if len(set(lineage_ids)) != len(lineage_ids):
            raise ValueError(
                "invalid dry-run report: duplicate lineage_id in lineage_entries"
            )

        actual_reason_counts: dict[str, int] = {}
        for quarantined_outcome in quarantined:
            for reason in quarantined_outcome.quarantine_record.reasons:
                kind = reason.kind.value
                actual_reason_counts[kind] = actual_reason_counts.get(kind, 0) + 1
        for kind, count in self.counts_by_reason.items():
            if kind not in {
                member.value for member in QuarantineReasonKind
            }:
                raise ValueError(
                    f"invalid dry-run report: reason {kind!r} is not in the "
                    "closed quarantine reason vocabulary"
                )
            if count < 1:
                raise ValueError(
                    f"invalid dry-run report: reason count for {kind!r} "
                    "must be a positive integer"
                )
        if dict(self.counts_by_reason) != actual_reason_counts:
            raise ValueError(
                "invalid dry-run report: counts_by_reason do not match the "
                "quarantine records"
            )
        object.__setattr__(
            self, "counts_by_reason", _FrozenJsonDict(dict(self.counts_by_reason))
        )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def run_sha256(self) -> str:
        return sha256(
            canonical_json(self.canonical_payload()).encode("utf-8")
        ).hexdigest()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mapping_version": self.mapping_version,
            "source_count": self.source_count,
            "mapped_count": self.mapped_count,
            "unmapped_count": self.unmapped_count,
            "quarantined_count": self.quarantined_count,
            "replayed_count": self.replayed_count,
            "outcomes": [
                outcome.canonical_payload() for outcome in self.outcomes
            ],
            "quarantine": [
                record.canonical_payload() for record in self.quarantine_records
            ],
            "lineage": [entry.canonical_payload() for entry in self.lineage_entries],
            "counts_by_reason": dict(sorted(self.counts_by_reason.items())),
        }


# ---------------------------------------------------------------------------
# Builder: the deterministic dry run
# ---------------------------------------------------------------------------


def _record_sort_key(record: LegacySourceRecord) -> tuple[str, str, str, str, str, str]:
    return (
        record.project_id,
        record.source_family.value,
        record.source_type,
        record.source_id,
        record.revision_token.value,
        record.payload_sha256,
    )


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


def _join_value(value: JsonValue) -> str:
    """Deterministic scalar encoding for the ``string_join`` derive op.

    Strings join verbatim; every other JSON value joins via its canonical JSON
    encoding (sorted keys, unescaped ASCII), so the join is byte-stable for
    equal content regardless of payload key order.
    """

    if isinstance(value, str):
        return value
    return canonical_json(value)


def _bound_scalar(value: Any) -> Optional[str]:
    """Deterministic normalization of one scalar identity/project/revision
    value from the real contract location.

    Strings normalize like the envelope (strip + collapse internal
    whitespace); integers normalize to their decimal form; booleans, floats,
    ``None``, objects and lists are unsupported identity values and fail
    closed (return ``None``) rather than being coerced ambiguously.
    """

    if isinstance(value, str):
        text = " ".join(value.strip().split())
        return text or None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return None


def _bound_value(
    contract: MappingContractSpec, payload: Any, field: str
) -> tuple[Optional[str], Optional[str]]:
    """Read one declared binding field from its real contract location.

    Pydantic sources read the payload object; SQLite sources read the outer
    row payload (physical columns) — never ``payload_json`` unless the
    contract itself declares that location.  Returns ``(normalized, None)``
    or ``(None, quarantine_detail_zh)``.
    """

    location = "外层行载荷" if contract.kind == "sqlite_table" else "载荷对象"
    if not isinstance(payload, dict):
        return None, f"载荷不是对象，无法绑定来源身份"
    if field not in payload:
        return None, f"缺少身份绑定字段 {field}（应位于{location}）"
    normalized = _bound_scalar(payload[field])
    if normalized is None:
        return (
            None,
            f"身份绑定字段 {field} 的值类型不支持"
            f"（{type(payload[field]).__name__}，仅标量 str/int）",
        )
    return normalized, None


def _canonical_bound(
    contract: MappingContractSpec,
    payload: Any,
    fields: Sequence[str],
) -> tuple[Optional[str], Optional[str]]:
    """Canonical encoding of one binding group.

    A single field yields its normalized scalar text; multiple fields yield
    the canonical JSON array of the ordered normalized scalars — an
    unambiguous, order-sensitive encoding (never ambiguous concatenation).
    """

    values: list[str] = []
    for field in fields:
        normalized, error = _bound_value(contract, payload, field)
        if normalized is None:
            return None, error
        values.append(normalized)
    if len(values) == 1:
        return values[0], None
    return canonical_json(values), None


def _bind_source_identity(
    record: LegacySourceRecord, type_spec: MappingTypeSpec
) -> tuple[Optional[str], Optional[str]]:
    """Enforce real source identity binding before any mapped outcome.

    Derives the expected identity, project scope and revision from the
    declared real contract location of the payload/row and compares all three
    to the ``LegacySourceRecord`` envelope.  Any missing, unsupported or
    mismatched value yields ``(None, quarantine_detail_zh)`` — one explicit
    ``incomplete_record`` quarantine outcome and **no** lineage entry.  On a
    valid binding returns ``(prefix + canonical_identity, None)`` where the
    canonical identity is the deterministic encoding of the declared
    identity fields (equal to the envelope ``source_id`` by construction).
    """

    contract = type_spec.source_contract
    payload = record.payload
    identity, error = _canonical_bound(contract, payload, contract.identity_fields)
    if identity is None:
        return None, error
    project, error = _canonical_bound(
        contract, payload, contract.project_scope_fields
    )
    if project is None:
        return None, error
    revision, error = _canonical_bound(contract, payload, contract.revision_fields)
    if revision is None:
        return None, error
    mismatches: list[str] = []
    if identity != record.source_id:
        mismatches.append(f"来源身份 {identity!r} != 信封 source_id {record.source_id!r}")
    if project != record.project_id:
        mismatches.append(f"项目作用域 {project!r} != 信封 project_id {record.project_id!r}")
    if revision != record.revision_token.value:
        mismatches.append(
            f"来源修订 {revision!r} != 信封 revision_token {record.revision_token.value!r}"
        )
    if mismatches:
        return None, "来源身份绑定不一致: " + "; ".join(mismatches)
    assert type_spec.identity_rule is not None
    return type_spec.identity_rule.prefix + identity, None


def _rule_payload(
    payload: Any,
    rule: MappingFieldRule,
    contract: MappingContractSpec,
) -> Mapping[str, JsonValue]:
    """Resolve the mapping dict for one rule's declared source scope.

    ``physical`` rules read the row payload directly (SQLite physical
    columns); ``payload`` rules read the declared ``payload_container``
    (SQLite) or the row/model payload itself (Pydantic / JSONL).  Raises
    :class:`KeyError` naming the missing container/object so the caller can
    quarantine the record explicitly — a missing value is never defaulted.
    """

    if rule.source_scope == "physical":
        if not isinstance(payload, dict):
            raise KeyError("<payload is not an object>")
        return payload
    if contract.kind == "sqlite_table" and contract.payload_container is not None:
        if not isinstance(payload, dict):
            raise KeyError("<payload is not an object>")
        if contract.payload_container not in payload:
            raise KeyError(contract.payload_container)
        inner = payload[contract.payload_container]
        if not isinstance(inner, dict):
            raise KeyError("<payload container is not an object>")
        return inner
    if not isinstance(payload, dict):
        raise KeyError("<payload is not an object>")
    return payload


def _derive_field_value(
    *,
    record: LegacySourceRecord,
    rule: MappingFieldRule,
    payload: Any,
    contract: MappingContractSpec,
) -> Union[str, JsonValue]:
    """Compute one derived field value; raises KeyError-style failure via
    :class:`KeyError` when a required source field is missing."""

    if rule.derive == "revision_token":
        return record.revision_token.value
    if rule.derive == "payload_sha256":
        return record.payload_sha256
    # string_join
    assert rule.source_fields
    source = _rule_payload(payload, rule, contract)
    parts: list[str] = []
    for field in rule.source_fields:
        if field not in source:
            raise KeyError(field)
        parts.append(_join_value(source[field]))
    return JOIN_SEPARATOR.join(parts)


def _whole_payload_value(
    record: LegacySourceRecord, contract: MappingContractSpec
) -> JsonValue:
    """Deep-frozen copy of the entire real payload for one source type.

    For SQLite sources with a declared ``payload_container`` the preserved
    value is the payload-model dump stored in that column; for Pydantic
    sources it is the whole payload object.  The returned value is a fresh
    deep-frozen container tree — mutating it never touches the source, and
    no real field can disappear from the mapped output.
    """

    payload = record.payload
    if contract.kind == "sqlite_table":
        assert contract.payload_container is not None
        if not isinstance(payload, dict) or contract.payload_container not in payload:
            raise KeyError(contract.payload_container)
        return _freeze_json_value(payload[contract.payload_container])
    if not isinstance(payload, dict):
        raise KeyError("<payload is not an object>")
    return _freeze_json_value(payload)


def _mapped_fields(
    *,
    record: LegacySourceRecord,
    type_spec: MappingTypeSpec,
) -> dict[str, JsonValue]:
    """Resolve the declared field rules against the payload.

    Raises :class:`KeyError` naming the first missing payload field or
    container so the caller can quarantine the record explicitly — a missing
    field is never filled with a default value.
    """

    payload = record.payload
    contract = type_spec.source_contract
    fields: dict[str, JsonValue] = {}
    for rule in type_spec.field_rules:
        if rule.kind == "omitted":
            continue  # declared drop with justification; nothing enters target
        if rule.kind == "whole_payload":
            assert rule.target_field is not None
            fields[rule.target_field] = _whole_payload_value(record, contract)
            continue
        if rule.kind in ("direct", "preserved_legacy_only"):
            assert rule.source_field is not None and rule.target_field is not None
            source = _rule_payload(payload, rule, contract)
            if rule.source_field not in source:
                raise KeyError(rule.source_field)
            fields[rule.target_field] = source[rule.source_field]
        else:  # derived
            assert rule.target_field is not None
            fields[rule.target_field] = _derive_field_value(
                record=record, rule=rule, payload=payload, contract=contract
            )
    return fields


def run_mapping_dry_run(
    source: Union[InventorySnapshot, Sequence[LegacySourceRecord]],
    spec: MappingSpec,
    prior_lineage: Sequence[MappingLineageEntry] = (),
) -> DryRunReport:
    """Run the pure, deterministic v2→v3 mapping dry run.

    Args:
        source: Worker 01 inventory snapshot (``.records`` is used) or a
            sequence of frozen :class:`LegacySourceRecord` instances.  No
            database, runtime singleton or semantic inference is involved and
            nothing is ever written.
        spec: the strictly validated mapping specification.
        prior_lineage: lineage entries carried from previous runs (typically
            ``previous_report.lineage_entries``); drives exact replay,
            conflicting-replay quarantine and parent pointers.

    Returns:
        A :class:`DryRunReport` with exact accounting
        (``source == mapped + unmapped``, ``quarantined == unmapped``), stable
        per-record dispositions, computed target identity/hash, full
        carried-forward lineage and a deterministic ``run_sha256``.
    """

    if isinstance(source, InventorySnapshot):
        records = list(source.records)
    else:
        records = list(source)
    for record in records:
        if not isinstance(record, LegacySourceRecord):
            raise TypeError(
                "mapping dry run accepts only LegacySourceRecord instances; "
                f"received {type(record).__name__}"
            )
    records.sort(key=_record_sort_key)

    prior: list[MappingLineageEntry] = list(prior_lineage)
    seen_prior_ids: set[str] = set()
    for entry in prior:
        if entry.mapping_version != spec.mapping_version:
            raise MappingLineageError(
                f"prior lineage entry {entry.lineage_id[:12]}… carries mapping "
                f"version {entry.mapping_version!r}, expected "
                f"{spec.mapping_version!r}"
            )
        if entry.lineage_id in seen_prior_ids:
            raise MappingLineageError(
                f"duplicate prior lineage entry {entry.lineage_id}"
            )
        seen_prior_ids.add(entry.lineage_id)
    prior.sort(key=_lineage_sort_key)

    # lineage_key -> ordered history (prior entries first, new entries appended
    # in canonical processing order as children are created).
    history: dict[tuple[str, str, str, str, str], list[MappingLineageEntry]] = {}
    for entry in prior:
        history.setdefault(entry.lineage_key, []).append(entry)

    outcomes: list[MappingOutcome] = []
    new_entries: list[MappingLineageEntry] = []

    for record in records:
        family_spec = spec.families.get(record.source_family.value)
        if family_spec is None:
            # Unreachable for Worker 01 inventory (families are closed), kept
            # fail-closed for direct record construction.
            outcomes.append(
                QuarantinedOutcome(
                    quarantine_record=_quarantine_from_record(
                        record,
                        QuarantineReasonKind.UNSUPPORTED_FAMILY,
                        detail_zh=(
                            f"来源族 {record.source_family.value!r} 未在映射规范中声明"
                        ),
                    )
                )
            )
            continue

        type_spec = next(
            (
                type_spec
                for type_spec in family_spec.types
                if type_spec.source_type == record.source_type
            ),
            None,
        )
        if type_spec is None:
            outcomes.append(
                QuarantinedOutcome(
                    quarantine_record=_quarantine_from_record(
                        record,
                        QuarantineReasonKind.UNSUPPORTED_TYPE,
                        detail_zh=(
                            f"来源类型 {record.source_type!r} 未在映射规范 "
                            f"{record.source_family.value!r} 族的声明类型中，"
                            "不映射为 v3 语义节点"
                        ),
                    )
                )
            )
            continue

        if type_spec.outcome == "quarantine":
            outcomes.append(
                QuarantinedOutcome(
                    quarantine_record=_quarantine_from_record(
                        record,
                        QuarantineReasonKind.UNSUPPORTED_TYPE,
                        detail_zh=type_spec.quarantine_detail_zh,
                    )
                )
            )
            continue

        assert type_spec.target_type is not None and type_spec.identity_rule is not None

        # Real source identity binding: the declared identity/project/revision
        # fields of the contract location must match the record envelope.
        # Any mismatch produces one explicit incomplete_record quarantine and
        # no lineage entry — never a mapped outcome under a wrong identity.
        target_id, binding_error = _bind_source_identity(record, type_spec)
        if target_id is None:
            outcomes.append(
                QuarantinedOutcome(
                    quarantine_record=_quarantine_from_record(
                        record,
                        QuarantineReasonKind.INCOMPLETE_RECORD,
                        detail_zh=binding_error or "来源身份绑定失败",
                    )
                )
            )
            continue

        try:
            fields = _mapped_fields(record=record, type_spec=type_spec)
        except KeyError as exc:
            outcomes.append(
                QuarantinedOutcome(
                    quarantine_record=_quarantine_from_record(
                        record,
                        QuarantineReasonKind.INCOMPLETE_RECORD,
                        detail_zh=f"缺少映射所需载荷字段: {exc.args[0]}",
                    )
                )
            )
            continue

        target_sha256 = _target_sha256(type_spec.target_type, target_id, fields)
        lineage_key = (
            record.project_id,
            record.source_family.value,
            record.source_type,
            record.source_id,
            spec.mapping_version,
        )
        migration_key = lineage_key[:4]
        candidate_id = _lineage_id(
            mapping_version=spec.mapping_version,
            migration_key=migration_key,
            revision_token=record.revision_token.value,
            payload_sha256=record.payload_sha256,
            target_sha256=target_sha256,
        )

        chain = history.get(lineage_key, [])
        # 1) exact replay: same key/version/revision/payload/target already
        #    recorded -> identical identity/hash, no new entry, no effect.
        replay = next(
            (entry for entry in chain if entry.lineage_id == candidate_id), None
        )
        if replay is not None:
            outcomes.append(
                MappedOutcome(
                    mapping_version=spec.mapping_version,
                    project_id=record.project_id,
                    source_family=record.source_family.value,
                    source_type=record.source_type,
                    source_id=record.source_id,
                    revision_token=record.revision_token.value,
                    payload_sha256=record.payload_sha256,
                    target_type=type_spec.target_type,
                    target_id=target_id,
                    fields=fields,
                    lineage_id=replay.lineage_id,
                    parent_lineage_id=replay.parent_lineage_id,
                    replayed=True,
                )
            )
            continue

        # 2) conflicting replay: same key/version/revision, different payload
        #    -> fail closed, prior entry untouched, no new lineage node.
        conflict = next(
            (
                entry
                for entry in chain
                if entry.revision_token == record.revision_token.value
                and entry.payload_sha256 != record.payload_sha256
            ),
            None,
        )
        if conflict is not None:
            outcomes.append(
                QuarantinedOutcome(
                    quarantine_record=_quarantine_from_record(
                        record,
                        QuarantineReasonKind.DUPLICATE_CONFLICT,
                        detail_zh=(
                            f"同一迁移键/映射版本/来源修订 {record.revision_token.value!r} "
                            "出现不同载荷哈希，视为冲突重放，全部隔离且不覆盖既有谱系"
                        ),
                    )
                )
            )
            continue

        # 3) changed revision (or first sighting): new child pointing at the
        #    prior result; the prior entry is immutable and never overwritten.
        parent = chain[-1] if chain else None
        new_entry = MappingLineageEntry(
            mapping_version=spec.mapping_version,
            migration_key=migration_key,
            revision_token=record.revision_token.value,
            payload_sha256=record.payload_sha256,
            target_type=type_spec.target_type,
            target_id=target_id,
            target_sha256=target_sha256,
            parent_lineage_id=parent.lineage_id if parent is not None else None,
        )
        history.setdefault(lineage_key, []).append(new_entry)
        new_entries.append(new_entry)
        outcomes.append(
            MappedOutcome(
                mapping_version=spec.mapping_version,
                project_id=record.project_id,
                source_family=record.source_family.value,
                source_type=record.source_type,
                source_id=record.source_id,
                revision_token=record.revision_token.value,
                payload_sha256=record.payload_sha256,
                target_type=type_spec.target_type,
                target_id=target_id,
                fields=fields,
                lineage_id=new_entry.lineage_id,
                parent_lineage_id=new_entry.parent_lineage_id,
                replayed=False,
            )
        )

    mapped_outcomes = [
        outcome for outcome in outcomes if isinstance(outcome, MappedOutcome)
    ]
    quarantine_outcomes = [
        outcome for outcome in outcomes if isinstance(outcome, QuarantinedOutcome)
    ]
    quarantine_records = [
        outcome.quarantine_record for outcome in quarantine_outcomes
    ]

    counts_by_reason: dict[str, int] = {}
    for quarantined in quarantine_records:
        for reason in quarantined.reasons:
            kind = reason.kind.value
            counts_by_reason[kind] = counts_by_reason.get(kind, 0) + 1

    full_lineage = sorted(prior + new_entries, key=_lineage_sort_key)

    return DryRunReport(
        mapping_version=spec.mapping_version,
        source_count=len(records),
        mapped_count=len(mapped_outcomes),
        unmapped_count=len(quarantine_outcomes),
        quarantined_count=len(quarantine_outcomes),
        replayed_count=sum(1 for outcome in mapped_outcomes if outcome.replayed),
        outcomes=tuple(outcomes),
        quarantine_records=tuple(quarantine_records),
        lineage_entries=tuple(full_lineage),
        counts_by_reason=counts_by_reason,
    )


# ---------------------------------------------------------------------------
# Read-only contract drift verifier
# ---------------------------------------------------------------------------

_WORKSPACE_ROOT = Path(__file__).resolve().parents[5]

_DDL_SKIP_LEADERS = (
    "PRIMARY",
    "UNIQUE",
    "FOREIGN",
    "REFERENCES",
    "CHECK",
    "CONSTRAINT",
    "CREATE",
    "ON",
    ")",
    "--",
)


class MappingContractIssue(BaseModel):
    """One deterministic contract-drift finding for a declared source type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family: _NonEmpty
    source_type: _NonEmpty
    message: _NonEmpty


class MappingContractVerification(BaseModel):
    """Pure, read-only result of verifying every declared source contract
    against the checked-in v2 contracts.

    Pydantic models are imported and their ``model_fields`` inspected;
    SQLite tables are checked against the source-controlled DDL text; JSONL
    snapshots are checked against the declared snapshot constants and the
    module source.  No database, service or runtime singleton is opened or
    imported by this verifier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mw_v2_v3_contract_verification_v1"] = (
        CONTRACT_VERIFICATION_SCHEMA_VERSION
    )
    spec_sha256: Sha256Hex
    source_type_count: int = Field(ge=0)
    verified_types: tuple[_NonEmpty, ...] = ()
    issues: tuple[MappingContractIssue, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verified(self) -> bool:
        return not self.issues

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "spec_sha256": self.spec_sha256,
            "source_type_count": self.source_type_count,
            "verified_types": list(self.verified_types),
            "issues": [
                {
                    "family": issue.family,
                    "source_type": issue.source_type,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
            "verified": self.verified,
        }


def _contract_issue(
    family: str, source_type: str, message: str
) -> MappingContractIssue:
    return MappingContractIssue(
        family=family, source_type=source_type, message=message
    )


def _module_name_for(source_file: str) -> str:
    return source_file.removesuffix(".py").replace("/", ".")


def _import_contract_module(source_file: str) -> Optional[ModuleType]:
    """Import a declared contract module by its repo path.

    Pure and read-only: adds the workspace root to ``sys.path`` only when it
    is missing and restores the path afterwards; never opens a database,
    service or runtime singleton.
    """

    root = str(_WORKSPACE_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        return importlib.import_module(_module_name_for(source_file))
    except Exception:
        return None
    finally:
        if added and root in sys.path:
            sys.path.remove(root)


def _read_source_text(source_file: str) -> Optional[str]:
    try:
        return (_WORKSPACE_ROOT / source_file).read_text(encoding="utf-8")
    except OSError:
        return None


def _ddl_columns(source_text: str, table: str) -> Optional[set[str]]:
    """Extract the declared column names of one CREATE TABLE statement."""

    match = re.search(
        r"CREATE TABLE IF NOT EXISTS\s+"
        + re.escape(table)
        + r"\s*\((.*?)\)\s*;",
        source_text,
        re.DOTALL,
    )
    if match is None:
        return None
    columns: set[str] = set()
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(_DDL_SKIP_LEADERS):
            continue
        name = stripped.split(None, 1)[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            columns.add(name)
    return columns


def _jsonl_snapshot_constants(source_text: str) -> dict[str, str]:
    """Top-level assigned names -> unparsed value expressions (AST, no import)."""

    tree = ast.parse(source_text)
    constants: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                constants[node.targets[0].id] = ast.unparse(node.value)
            except Exception:
                continue
    return constants


def _rule_source_names(type_spec: MappingTypeSpec) -> list[str]:
    """Every payload/column field a rule actually reads."""

    names: list[str] = []
    for rule in type_spec.field_rules:
        if rule.kind == "derived" and rule.derive != "string_join":
            continue
        if rule.source_field is not None:
            names.append(rule.source_field)
        names.extend(rule.source_fields)
    return names


def _verify_pydantic_contract(
    family: str, type_spec: MappingTypeSpec
) -> list[MappingContractIssue]:
    contract = type_spec.source_contract
    assert contract.kind == "pydantic_model" and contract.symbol is not None
    module = _import_contract_module(contract.source_file)
    if module is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"无法导入声明的合约模块 {contract.source_file}",
            )
        ]
    model_class = getattr(module, contract.symbol, None)
    if model_class is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"模块 {contract.source_file} 中不存在模型符号 {contract.symbol}",
            )
        ]
    model_fields = getattr(model_class, "model_fields", None)
    if model_fields is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"{contract.symbol} 不是 Pydantic 模型（无 model_fields）",
            )
        ]
    model_field_names = set(model_fields)
    role_names = (
        set(contract.identity_fields)
        | set(contract.project_scope_fields)
        | set(contract.revision_fields)
    )
    rule_names = set(_rule_source_names(type_spec))
    declared = sorted((role_names | rule_names) - model_field_names)
    issues: list[MappingContractIssue] = []
    if declared:
        issues.append(
            _contract_issue(
                family,
                type_spec.source_type,
                f"模型 {contract.symbol} 缺少声明字段: " + ", ".join(declared),
            )
        )
    if type_spec.outcome == "quarantine":
        return issues
    whole_payload_rules = [
        rule for rule in type_spec.field_rules if rule.kind == "whole_payload"
    ]
    if whole_payload_rules:
        # Exact two-way coverage invariant: a whole_payload rule's
        # covered_fields must equal the real model's field set, independent
        # of identity/project/revision roles or other field rules.  A role
        # field can never silently vanish from the explicit list — the
        # preservation mechanism is exact, never a union that masks loss.
        whole_payload_fields = {
            field for rule in whole_payload_rules for field in rule.covered_fields
        }
        unknown_whole_payload_fields = sorted(whole_payload_fields - model_field_names)
        if unknown_whole_payload_fields:
            issues.append(
                _contract_issue(
                    family,
                    type_spec.source_type,
                    f"模型 {contract.symbol} 的 whole_payload 声明了不存在字段: "
                    + ", ".join(unknown_whole_payload_fields),
                )
            )
        missing_whole_payload_fields = sorted(model_field_names - whole_payload_fields)
        if missing_whole_payload_fields:
            issues.append(
                _contract_issue(
                    family,
                    type_spec.source_type,
                    f"模型 {contract.symbol} 的 whole_payload covered_fields "
                    "缺少真实模型字段: " + ", ".join(missing_whole_payload_fields),
                )
            )
        return issues
    # No whole_payload: exhaustive disposition via declared roles + rules.
    covered = role_names | rule_names
    undispositioned = sorted(model_field_names - covered)
    if undispositioned:
        issues.append(
            _contract_issue(
                family,
                type_spec.source_type,
                f"模型 {contract.symbol} 存在未处置字段（未映射、未保留、"
                "未显式省略）: " + ", ".join(undispositioned),
            )
        )
    return issues


def _verify_sqlite_contract(
    family: str, type_spec: MappingTypeSpec
) -> list[MappingContractIssue]:
    contract = type_spec.source_contract
    assert contract.kind == "sqlite_table" and contract.table is not None
    source_text = _read_source_text(contract.source_file)
    if source_text is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"无法读取声明的合约文件 {contract.source_file}",
            )
        ]
    columns = _ddl_columns(source_text, contract.table)
    if columns is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"在 {contract.source_file} 的 DDL 中未找到表 {contract.table}",
            )
        ]
    missing = [
        name
        for name in (
            list(contract.identity_fields)
            + list(contract.project_scope_fields)
            + list(contract.revision_fields)
        )
        if name not in columns
    ]
    if contract.payload_container is not None and (
        contract.payload_container not in columns
    ):
        missing.append(contract.payload_container)
    physical_fields: set[str] = set()
    for rule in type_spec.field_rules:
        if rule.source_scope != "physical":
            continue
        if rule.source_field is not None:
            physical_fields.add(rule.source_field)
        physical_fields.update(rule.source_fields)
    missing.extend(sorted(name for name in physical_fields if name not in columns))
    issues: list[MappingContractIssue] = []
    if missing:
        issues.append(
            _contract_issue(
                family,
                type_spec.source_type,
                f"表 {contract.table} 缺少声明的物理列: "
                + ", ".join(sorted(set(missing))),
            )
        )
    if type_spec.outcome != "quarantine":
        # Exhaustive column disposition: every real DDL column must be a
        # declared role (identity/project/revision/container) or a physical
        # field-rule source — an added column with no disposition is a
        # silent drop waiting to happen.
        role_names = (
            set(contract.identity_fields)
            | set(contract.project_scope_fields)
            | set(contract.revision_fields)
        )
        covered_columns = role_names | physical_fields
        if contract.payload_container is not None:
            covered_columns.add(contract.payload_container)
        undispositioned = sorted(columns - covered_columns)
        if undispositioned:
            issues.append(
                _contract_issue(
                    family,
                    type_spec.source_type,
                    f"表 {contract.table} 存在未处置物理列（未映射、未保留、"
                    "未显式省略）: " + ", ".join(undispositioned),
                )
            )
    if contract.payload_model is not None:
        issues.extend(_verify_payload_model(family, type_spec, contract))
    return issues


def _verify_payload_model(
    family: str, type_spec: MappingTypeSpec, contract: MappingContractSpec
) -> list[MappingContractIssue]:
    assert contract.payload_model is not None and contract.payload_model_file is not None
    module = _import_contract_module(contract.payload_model_file)
    if module is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"无法导入 payload 模型模块 {contract.payload_model_file}",
            )
        ]
    model_class = getattr(module, contract.payload_model, None)
    if model_class is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"模块 {contract.payload_model_file} 中不存在 payload 模型符号 "
                f"{contract.payload_model}",
            )
        ]
    model_fields = getattr(model_class, "model_fields", None)
    if model_fields is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"{contract.payload_model} 不是 Pydantic 模型（无 model_fields）",
            )
        ]
    payload_fields: set[str] = set()
    for rule in type_spec.field_rules:
        if rule.source_scope != "payload":
            continue
        if rule.source_field is not None:
            payload_fields.add(rule.source_field)
        payload_fields.update(rule.source_fields)
    missing = sorted(name for name in payload_fields if name not in model_fields)
    issues: list[MappingContractIssue] = []
    if missing:
        issues.append(
            _contract_issue(
                family,
                type_spec.source_type,
                f"payload 模型 {contract.payload_model} 缺少声明字段: "
                + ", ".join(missing),
            )
        )
    if type_spec.outcome != "quarantine":
        # Exhaustive payload-model disposition: with a whole_payload rule the
        # covered_fields must equal the payload model fields exactly,
        # independent of other payload-scope rules — a payload field that
        # vanished from the explicit list is a silent drop; without one,
        # every real payload model field must be covered by a payload-scope
        # rule.
        whole_payload_rules = [
            rule for rule in type_spec.field_rules if rule.kind == "whole_payload"
        ]
        whole_payload_fields = {
            field
            for rule in whole_payload_rules
            for field in rule.covered_fields
        }
        unknown_whole_payload_fields = sorted(
            whole_payload_fields - set(model_fields)
        )
        if unknown_whole_payload_fields:
            issues.append(
                _contract_issue(
                    family,
                    type_spec.source_type,
                    f"payload 模型 {contract.payload_model} 的 whole_payload "
                    "声明了不存在字段: "
                    + ", ".join(unknown_whole_payload_fields),
                )
            )
        if whole_payload_rules:
            missing_whole_payload_fields = sorted(
                set(model_fields) - whole_payload_fields
            )
            if missing_whole_payload_fields:
                issues.append(
                    _contract_issue(
                        family,
                        type_spec.source_type,
                        f"payload 模型 {contract.payload_model} 的 whole_payload "
                        "covered_fields 缺少真实字段: "
                        + ", ".join(missing_whole_payload_fields),
                    )
                )
        else:
            covered = payload_fields
            undispositioned = sorted(set(model_fields) - covered)
            if undispositioned:
                issues.append(
                    _contract_issue(
                        family,
                        type_spec.source_type,
                        f"payload 模型 {contract.payload_model} 存在未处置字段"
                        "（未映射、未保留、未显式省略）: "
                        + ", ".join(undispositioned),
                    )
                )
    return issues


def _verify_jsonl_contract(
    family: str, type_spec: MappingTypeSpec
) -> list[MappingContractIssue]:
    contract = type_spec.source_contract
    assert contract.kind == "jsonl_snapshot"
    assert contract.snapshot_file is not None and contract.snapshot_constants
    source_text = _read_source_text(contract.source_file)
    if source_text is None:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"无法读取声明的合约文件 {contract.source_file}",
            )
        ]
    constants = _jsonl_snapshot_constants(source_text)
    missing_constants = [
        name for name in contract.snapshot_constants if name not in constants
    ]
    if missing_constants:
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"模块 {contract.source_file} 未声明快照常量: "
                + ", ".join(missing_constants),
            )
        ]
    values = [constants[name] for name in contract.snapshot_constants]
    if not any(contract.snapshot_file in value for value in values):
        return [
            _contract_issue(
                family,
                type_spec.source_type,
                f"快照常量未指向声明的快照文件 {contract.snapshot_file}",
            )
        ]
    issues: list[MappingContractIssue] = []
    for name in _rule_source_names(type_spec):
        if f'"{name}"' not in source_text and f"'{name}'" not in source_text:
            issues.append(
                _contract_issue(
                    family,
                    type_spec.source_type,
                    f"JSONL 行字段 {name!r} 未在模块 {contract.source_file} "
                    "的代码中出现",
                )
            )
    return issues


def verify_mapping_spec_contracts(spec: MappingSpec) -> MappingContractVerification:
    """Verify every declared source contract against the checked-in v2
    contracts, purely and read-only.

    For each declared source type the verifier proves (without opening any
    database or service): Pydantic model symbols and every declared
    identity/revision/payload/field-rule field exist in ``model_fields``;
    SQLite tables and every declared physical column exist in the
    source-controlled DDL text; JSONL snapshots bind to the declared snapshot
    constants and row fields appear in the module source.

    Returns an immutable :class:`MappingContractVerification` whose
    ``verified`` flag is True only when no drift issue was found.
    """

    issues: list[MappingContractIssue] = []
    verified_types: list[str] = []
    for family, family_spec in sorted(spec.families.items()):
        for type_spec in family_spec.types:
            source_type = type_spec.source_type
            verified_types.append(f"{family}/{source_type}")
            contract = type_spec.source_contract
            if contract.kind == "pydantic_model":
                issues.extend(_verify_pydantic_contract(family, type_spec))
            elif contract.kind == "sqlite_table":
                issues.extend(_verify_sqlite_contract(family, type_spec))
            else:
                issues.extend(_verify_jsonl_contract(family, type_spec))
    issues.sort(key=lambda issue: (issue.family, issue.source_type, issue.message))
    return MappingContractVerification(
        spec_sha256=spec.spec_sha256,
        source_type_count=len(verified_types),
        verified_types=tuple(sorted(verified_types)),
        issues=tuple(issues),
    )
