from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from pathlib import Path
from pathlib import PureWindowsPath
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .monitoring_ai_field_profile_cache import MonitoringFieldProfileCache
from .monitoring_batch_repository import (
    CompletenessGateError,
    DiffReadyBatch,
    FieldProfileBatchIdentity,
    MonitoringBatchRepository,
    NormalizedRow,
)


FIELD_PROFILE_SCHEMA_VERSION = "monitoring_ai_field_profile_v3"
FIELD_PROFILE_PROFILER_CONTRACT_VERSION = (
    "monitoring_ai_field_profiler_contract_v1"
)
DEFAULT_TOP_VALUE_LIMIT = 10
DEFAULT_REPRESENTATIVE_VALUE_LIMIT = 12
DEFAULT_ANOMALY_LIMIT = 10
DEFAULT_MAX_TEXT_LENGTH = 512
FIELD_RELATIONSHIP_TYPES = frozenset(
    {
        "term_code_pair",
        "site_identity_pair",
        "visit_identity_pair",
        "value_unit_pair",
        "performed_reason_pair",
    }
)
_DISPLAY_PREVIEW_LENGTH = 160
_MISSING = object()
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_DECIMAL_PATTERN = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?\d+)$"
)
_REPEATED_FIELD_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+?)(?P<suffix>__\d+)$")
_BOOLEAN_TEXT = frozenset({"true", "false", "yes", "no", "y", "n"})
_NON_FINITE_TEXT = frozenset(
    {
        "nan",
        "+nan",
        "-nan",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+infinity",
        "-infinity",
    }
)
_IDENTIFIER_FIELD_TOKENS = frozenset(
    {
        "SUBJID",
        "USUBJID",
        "SUBJECTID",
        "SUBJECT_ID",
        "PATIENTID",
        "PATIENT_ID",
        "SITEID",
        "SITE_ID",
        "CENTERID",
        "CENTER_ID",
        "受试者编号",
        "受试者ID",
        "中心编号",
        "中心ID",
    }
)
_TYPE_ORDER = {
    "boolean": 0,
    "integer": 1,
    "decimal": 2,
    "date": 3,
    "datetime": 4,
    "string": 5,
}


@dataclass(frozen=True)
class FieldValueFrequency:
    value: Any
    count: int
    observed_type: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FieldAnomalyExample:
    code: str
    business_key: str
    value: Any
    observed_type: str
    expected_type: Optional[str] = None
    length: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class MonitoringFieldProfile:
    domain: str
    field: str
    total_rows: int
    non_empty_count: int
    null_rate: float
    inferred_type: str
    unique_value_count: int
    top_values: Tuple[FieldValueFrequency, ...]
    representative_values: Tuple[Any, ...]
    anomaly_examples: Tuple[FieldAnomalyExample, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "field": self.field,
            "total_rows": self.total_rows,
            "non_empty_count": self.non_empty_count,
            "null_rate": self.null_rate,
            "inferred_type": self.inferred_type,
            "unique_value_count": self.unique_value_count,
            "top_values": [item.to_dict() for item in self.top_values],
            "representative_values": list(self.representative_values),
            "anomaly_examples": [item.to_dict() for item in self.anomaly_examples],
        }

    def to_ai_dict(self) -> Dict[str, Any]:
        identifier = _is_identifier_field(self.field)
        return {
            "domain": self.domain,
            "field": self.field,
            "total_rows": self.total_rows,
            "non_empty_count": self.non_empty_count,
            "null_rate": self.null_rate,
            "inferred_type": self.inferred_type,
            "unique_value_count": self.unique_value_count,
            "values_redacted": identifier,
            "top_values": [
                {
                    "value": ({"redacted": "identifier"} if identifier else item.value),
                    "count": item.count,
                    "observed_type": item.observed_type,
                }
                for item in self.top_values
            ],
            "representative_values": (
                [{"redacted": "identifier"}]
                if identifier
                else list(self.representative_values)
            ),
            "anomaly_examples": [
                {
                    key: value
                    for key, value in item.to_dict().items()
                    if key not in {"business_key", "value"}
                }
                for item in self.anomaly_examples
            ],
        }


@dataclass(frozen=True)
class FieldRelationshipProfile:
    domain: str
    left_field: str
    right_field: str
    relationship_type: str
    total_rows: int
    jointly_non_empty_count: int
    left_only_count: int
    right_only_count: int
    unique_pair_count: int
    left_values_with_multiple_right: int
    right_values_with_multiple_left: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitoringFieldProfileSnapshot:
    schema_version: str
    batch_id: str
    project_id: str
    batch_revision: int
    mapping_revision: Optional[str]
    expected_domains: Tuple[str, ...]
    source_bindings: Tuple[Tuple[str, str], ...]
    source_sha256s: Tuple[str, ...]
    row_count: int
    input_sha256: str
    fields: Tuple[MonitoringFieldProfile, ...]
    relationships: Tuple[FieldRelationshipProfile, ...]
    profile_sha256: str

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "MonitoringFieldProfileSnapshot":
        expected_keys = {
            "schema_version",
            "batch_id",
            "project_id",
            "batch_revision",
            "mapping_revision",
            "expected_domains",
            "source_bindings",
            "source_sha256s",
            "row_count",
            "input_sha256",
            "fields",
            "relationships",
            "profile_sha256",
        }
        if set(payload) != expected_keys:
            raise ValueError("cached field profile snapshot shape is invalid")
        if payload.get("schema_version") != FIELD_PROFILE_SCHEMA_VERSION:
            raise ValueError("cached field profile schema version is invalid")
        input_sha256 = _required_digest(
            payload.get("input_sha256"),
            "input_sha256",
        )
        profile_sha256 = _required_digest(
            payload.get("profile_sha256"),
            "profile_sha256",
        )
        source_bindings = tuple(
            (
                str(item["source_entry_id"]),
                _required_digest(
                    item["source_content_sha256"],
                    "source_content_sha256",
                ),
            )
            for item in _required_mapping_sequence(
                payload.get("source_bindings"),
                "source_bindings",
            )
        )
        fields = tuple(
            MonitoringFieldProfile(
                domain=str(item["domain"]),
                field=str(item["field"]),
                total_rows=_required_int(
                    item["total_rows"],
                    "fields.total_rows",
                    minimum=0,
                ),
                non_empty_count=_required_int(
                    item["non_empty_count"],
                    "fields.non_empty_count",
                    minimum=0,
                ),
                null_rate=_required_float(
                    item["null_rate"],
                    "fields.null_rate",
                    minimum=0.0,
                    maximum=1.0,
                ),
                inferred_type=str(item["inferred_type"]),
                unique_value_count=_required_int(
                    item["unique_value_count"],
                    "fields.unique_value_count",
                    minimum=0,
                ),
                top_values=tuple(
                    FieldValueFrequency(
                        value=frequency["value"],
                        count=_required_int(
                            frequency["count"],
                            "fields.top_values.count",
                            minimum=0,
                        ),
                        observed_type=str(frequency["observed_type"]),
                    )
                    for frequency in _required_mapping_sequence(
                        item.get("top_values"),
                        "top_values",
                    )
                ),
                representative_values=tuple(
                    _required_sequence(
                        item.get("representative_values"),
                        "representative_values",
                    )
                ),
                anomaly_examples=tuple(
                    FieldAnomalyExample(
                        code=str(anomaly["code"]),
                        business_key=str(anomaly["business_key"]),
                        value=anomaly["value"],
                        observed_type=str(anomaly["observed_type"]),
                        expected_type=(
                            str(anomaly["expected_type"])
                            if anomaly.get("expected_type") is not None
                            else None
                        ),
                        length=(
                            _required_int(
                                anomaly["length"],
                                "fields.anomaly_examples.length",
                                minimum=0,
                            )
                            if anomaly.get("length") is not None
                            else None
                        ),
                    )
                    for anomaly in _required_mapping_sequence(
                        item.get("anomaly_examples"),
                        "anomaly_examples",
                    )
                ),
            )
            for item in _required_mapping_sequence(
                payload.get("fields"),
                "fields",
            )
        )
        relationships = tuple(
            FieldRelationshipProfile(
                domain=str(item["domain"]),
                left_field=str(item["left_field"]),
                right_field=str(item["right_field"]),
                relationship_type=str(item["relationship_type"]),
                total_rows=_required_int(
                    item["total_rows"],
                    "relationships.total_rows",
                    minimum=0,
                ),
                jointly_non_empty_count=_required_int(
                    item["jointly_non_empty_count"],
                    "relationships.jointly_non_empty_count",
                    minimum=0,
                ),
                left_only_count=_required_int(
                    item["left_only_count"],
                    "relationships.left_only_count",
                    minimum=0,
                ),
                right_only_count=_required_int(
                    item["right_only_count"],
                    "relationships.right_only_count",
                    minimum=0,
                ),
                unique_pair_count=_required_int(
                    item["unique_pair_count"],
                    "relationships.unique_pair_count",
                    minimum=0,
                ),
                left_values_with_multiple_right=_required_int(
                    item["left_values_with_multiple_right"],
                    "relationships.left_values_with_multiple_right",
                    minimum=0,
                ),
                right_values_with_multiple_left=_required_int(
                    item["right_values_with_multiple_left"],
                    "relationships.right_values_with_multiple_left",
                    minimum=0,
                ),
            )
            for item in _required_mapping_sequence(
                payload.get("relationships"),
                "relationships",
            )
        )
        snapshot = cls(
            schema_version=FIELD_PROFILE_SCHEMA_VERSION,
            batch_id=str(payload["batch_id"]),
            project_id=str(payload["project_id"]),
            batch_revision=_required_int(
                payload["batch_revision"],
                "batch_revision",
                minimum=1,
            ),
            mapping_revision=(
                str(payload["mapping_revision"])
                if payload.get("mapping_revision") is not None
                else None
            ),
            expected_domains=tuple(
                str(item)
                for item in _required_sequence(
                    payload.get("expected_domains"),
                    "expected_domains",
                )
            ),
            source_bindings=source_bindings,
            source_sha256s=tuple(
                _required_digest(item, "source_sha256")
                for item in _required_sequence(
                    payload.get("source_sha256s"),
                    "source_sha256s",
                )
            ),
            row_count=_required_int(
                payload["row_count"],
                "row_count",
                minimum=0,
            ),
            input_sha256=input_sha256,
            fields=fields,
            relationships=relationships,
            profile_sha256=profile_sha256,
        )
        profile_payload = snapshot.to_dict()
        profile_payload.pop("profile_sha256")
        if _hash_payload(profile_payload) != profile_sha256:
            raise ValueError("cached field profile semantic digest mismatch")
        return snapshot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "batch_revision": self.batch_revision,
            "mapping_revision": self.mapping_revision,
            "expected_domains": list(self.expected_domains),
            "source_bindings": [
                {
                    "source_entry_id": source_entry_id,
                    "source_content_sha256": content_sha256,
                }
                for source_entry_id, content_sha256 in self.source_bindings
            ],
            "source_sha256s": list(self.source_sha256s),
            "row_count": self.row_count,
            "input_sha256": self.input_sha256,
            "fields": [field.to_dict() for field in self.fields],
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
            "profile_sha256": self.profile_sha256,
        }

    def to_ai_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "batch_revision": self.batch_revision,
            "mapping_revision": self.mapping_revision,
            "expected_domains": list(self.expected_domains),
            "source_bindings": [
                {
                    "source_entry_id": source_entry_id,
                    "source_content_sha256": content_sha256,
                }
                for source_entry_id, content_sha256 in self.source_bindings
            ],
            "source_sha256s": list(self.source_sha256s),
            "row_count": self.row_count,
            "input_sha256": self.input_sha256,
            "fields": [field.to_ai_dict() for field in self.fields],
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
            "profile_sha256": self.profile_sha256,
            "payload_policy": "field_statistics_without_row_or_identifier_values_v1",
        }


@dataclass(frozen=True)
class _Observation:
    business_key: str
    raw_value: Any
    observed_type: str
    identity: str
    sort_key: Tuple[int, str]
    display_value: Any


class MonitoringAIFieldProfiler:
    """Build deterministic field profiles from one complete frozen batch."""

    def __init__(
        self,
        repository: MonitoringBatchRepository,
        *,
        top_value_limit: int = DEFAULT_TOP_VALUE_LIMIT,
        representative_value_limit: int = DEFAULT_REPRESENTATIVE_VALUE_LIMIT,
        anomaly_limit: int = DEFAULT_ANOMALY_LIMIT,
        max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
        cache_root: Optional[Path] = None,
    ):
        self.repository = repository
        self.top_value_limit = _positive_limit(top_value_limit, "top_value_limit")
        self.representative_value_limit = _positive_limit(
            representative_value_limit,
            "representative_value_limit",
        )
        self.anomaly_limit = _positive_limit(anomaly_limit, "anomaly_limit")
        self.max_text_length = _positive_limit(max_text_length, "max_text_length")
        identity_loader = getattr(
            repository,
            "load_field_profile_cache_identity",
            None,
        )
        if cache_root is None and callable(identity_loader):
            object_root = getattr(repository, "object_root", None)
            if object_root is not None:
                cache_root = (
                    Path(object_root)
                    / "derived"
                    / "field_profile_cache"
                )
        self.cache = (
            MonitoringFieldProfileCache(cache_root)
            if cache_root is not None and callable(identity_loader)
            else None
        )

    def profile_frozen_batch(self, batch_id: str) -> MonitoringFieldProfileSnapshot:
        return self._profile_repository_batch(batch_id, require_frozen=True)

    def profile_batch(self, batch_id: str) -> MonitoringFieldProfileSnapshot:
        return self._profile_repository_batch(batch_id, require_frozen=False)

    def profile_loaded_batch(
        self,
        batch: DiffReadyBatch,
    ) -> MonitoringFieldProfileSnapshot:
        """Profile a batch already loaded through the repository readiness gate."""
        if batch.state not in {"parsed", "validated", "confirmed", "frozen"}:
            raise ValueError(
                "batch must be parsed before a field profile can be built"
            )
        return self._profile_batch(batch)

    def profiler_contract(self) -> Dict[str, Any]:
        return {
            "contract_version": FIELD_PROFILE_PROFILER_CONTRACT_VERSION,
            "schema_version": FIELD_PROFILE_SCHEMA_VERSION,
            "top_value_limit": self.top_value_limit,
            "representative_value_limit": self.representative_value_limit,
            "anomaly_limit": self.anomaly_limit,
            "max_text_length": self.max_text_length,
        }

    def _profile_repository_batch(
        self,
        batch_id: str,
        *,
        require_frozen: bool,
    ) -> MonitoringFieldProfileSnapshot:
        before_identity = self._cache_identity(batch_id)
        if before_identity is not None:
            if require_frozen and before_identity.state != "frozen":
                raise CompletenessGateError(
                    "batch must be frozen before a field profile can be built"
                )
            if self.cache is not None:
                lookup = self.cache.load(
                    batch_identity=before_identity.to_dict(),
                    profiler_contract=self.profiler_contract(),
                )
                if lookup.hit:
                    try:
                        snapshot = MonitoringFieldProfileSnapshot.from_dict(
                            lookup.snapshot_payload or {}
                        )
                        _validate_snapshot_identity(snapshot, before_identity)
                        return snapshot
                    except (KeyError, TypeError, ValueError):
                        pass

        batch = (
            self.repository.load_diff_ready_batch(batch_id)
            if require_frozen
            else self.repository.load_profile_ready_batch(batch_id)
        )
        snapshot = self._profile_batch(batch)
        if self.cache is None or before_identity is None:
            return snapshot
        after_identity = self._cache_identity(batch_id)
        if (
            after_identity is None
            or after_identity.identity_sha256 != before_identity.identity_sha256
        ):
            return snapshot
        _validate_snapshot_identity(snapshot, after_identity)
        self.cache.store(
            batch_identity=after_identity.to_dict(),
            profiler_contract=self.profiler_contract(),
            snapshot_payload=snapshot.to_dict(),
        )
        return snapshot

    def _cache_identity(
        self,
        batch_id: str,
    ) -> Optional[FieldProfileBatchIdentity]:
        loader = getattr(
            self.repository,
            "load_field_profile_cache_identity",
            None,
        )
        if self.cache is None or not callable(loader):
            return None
        try:
            identity = loader(batch_id)
        except (OSError, TypeError, ValueError):
            return None
        if not isinstance(identity, FieldProfileBatchIdentity):
            return None
        return identity

    def _profile_batch(
        self,
        batch: DiffReadyBatch,
    ) -> MonitoringFieldProfileSnapshot:
        rows_by_domain: Dict[str, List[NormalizedRow]] = defaultdict(list)
        for row in batch.rows:
            rows_by_domain[row.domain].append(row)
        schema_fields_by_domain: Dict[str, set[str]] = defaultdict(set)
        for domain, field, _source_sheet in batch.schema_fields:
            schema_fields_by_domain[domain].add(field)
            rows_by_domain.setdefault(domain, [])

        profiles: List[MonitoringFieldProfile] = []
        relationships: List[FieldRelationshipProfile] = []
        for domain in sorted(rows_by_domain):
            domain_rows = sorted(
                rows_by_domain[domain],
                key=lambda item: item.business_key,
            )
            field_names = sorted(
                {
                    str(field)
                    for row in domain_rows
                    for field in row.data
                } | schema_fields_by_domain.get(domain, set())
            )
            domain_profiles = [
                self._profile_field(domain, field_name, domain_rows)
                for field_name in field_names
            ]
            profiles.extend(domain_profiles)
            numeric_fields = {
                profile.field
                for profile in domain_profiles
                if profile.inferred_type in {"integer", "decimal"}
            }
            for left_field, right_field, relationship_type in (
                _candidate_field_relationships(
                    field_names,
                    numeric_fields=numeric_fields,
                )
            ):
                relationships.append(
                    self._profile_relationship(
                        domain,
                        left_field,
                        right_field,
                        relationship_type,
                        domain_rows,
                    )
                )

        input_sha256 = _hash_payload(_complete_input_payload(batch))
        profile_payload = {
            "schema_version": FIELD_PROFILE_SCHEMA_VERSION,
            "batch_id": batch.batch_id,
            "project_id": batch.project_id,
            "batch_revision": batch.version,
            "mapping_revision": batch.mapping_revision,
            "expected_domains": list(batch.expected_domains),
            "source_bindings": [
                {
                    "source_entry_id": source_entry_id,
                    "source_content_sha256": content_sha256,
                }
                for source_entry_id, content_sha256 in batch.source_bindings
            ],
            "source_sha256s": list(batch.source_hashes),
            "row_count": len(batch.rows),
            "input_sha256": input_sha256,
            "fields": [field.to_dict() for field in profiles],
            "relationships": [
                relationship.to_dict() for relationship in relationships
            ],
        }
        return MonitoringFieldProfileSnapshot(
            schema_version=FIELD_PROFILE_SCHEMA_VERSION,
            batch_id=batch.batch_id,
            project_id=batch.project_id,
            batch_revision=batch.version,
            mapping_revision=batch.mapping_revision,
            expected_domains=batch.expected_domains,
            source_bindings=batch.source_bindings,
            source_sha256s=batch.source_hashes,
            row_count=len(batch.rows),
            input_sha256=input_sha256,
            fields=tuple(profiles),
            relationships=tuple(relationships),
            profile_sha256=_hash_payload(profile_payload),
        )

    def _profile_field(
        self,
        domain: str,
        field_name: str,
        rows: Sequence[NormalizedRow],
    ) -> MonitoringFieldProfile:
        observations: List[_Observation] = []
        non_empty_values = [
            row.data.get(field_name, _MISSING)
            for row in rows
            if not _is_empty(row.data.get(field_name, _MISSING))
        ]
        allow_text_boolean = _all_values_are_boolean_like(non_empty_values)
        for row in rows:
            raw_value = row.data.get(field_name, _MISSING)
            if _is_empty(raw_value):
                continue
            observed_type = _infer_value_type(
                raw_value,
                allow_text_boolean=allow_text_boolean,
            )
            identity = _value_identity(raw_value)
            observations.append(
                _Observation(
                    business_key=row.business_key,
                    raw_value=raw_value,
                    observed_type=observed_type,
                    identity=identity,
                    sort_key=(_TYPE_ORDER[observed_type], identity),
                    display_value=_display_value(raw_value),
                )
            )

        inferred_type = (
            _infer_field_type(observations) if rows else "unknown"
        )
        frequencies = Counter(item.identity for item in observations)
        examples_by_identity: Dict[str, _Observation] = {}
        for item in observations:
            examples_by_identity.setdefault(item.identity, item)

        top_observations = sorted(
            examples_by_identity.values(),
            key=lambda item: (-frequencies[item.identity], item.sort_key),
        )[: self.top_value_limit]
        representative_observations = sorted(
            examples_by_identity.values(),
            key=lambda item: item.sort_key,
        )[: self.representative_value_limit]
        anomalies = self._anomalies(observations, inferred_type)

        total_rows = len(rows)
        non_empty_count = len(observations)
        null_rate = (
            round((total_rows - non_empty_count) / total_rows, 12)
            if total_rows
            else 0.0
        )
        return MonitoringFieldProfile(
            domain=domain,
            field=field_name,
            total_rows=total_rows,
            non_empty_count=non_empty_count,
            null_rate=null_rate,
            inferred_type=inferred_type,
            unique_value_count=len(frequencies),
            top_values=tuple(
                FieldValueFrequency(
                    value=item.display_value,
                    count=frequencies[item.identity],
                    observed_type=item.observed_type,
                )
                for item in top_observations
            ),
            representative_values=tuple(
                item.display_value for item in representative_observations
            ),
            anomaly_examples=tuple(anomalies[: self.anomaly_limit]),
        )

    @staticmethod
    def _profile_relationship(
        domain: str,
        left_field: str,
        right_field: str,
        relationship_type: str,
        rows: Sequence[NormalizedRow],
    ) -> FieldRelationshipProfile:
        pair_identities: set[tuple[str, str]] = set()
        right_by_left: Dict[str, set[str]] = defaultdict(set)
        left_by_right: Dict[str, set[str]] = defaultdict(set)
        jointly_non_empty_count = 0
        left_only_count = 0
        right_only_count = 0
        for row in rows:
            left = row.data.get(left_field, _MISSING)
            right = row.data.get(right_field, _MISSING)
            left_present = not _is_empty(left)
            right_present = not _is_empty(right)
            if left_present and right_present:
                jointly_non_empty_count += 1
                left_identity = _value_identity(left)
                right_identity = _value_identity(right)
                pair_identities.add((left_identity, right_identity))
                right_by_left[left_identity].add(right_identity)
                left_by_right[right_identity].add(left_identity)
            elif left_present:
                left_only_count += 1
            elif right_present:
                right_only_count += 1
        return FieldRelationshipProfile(
            domain=domain,
            left_field=left_field,
            right_field=right_field,
            relationship_type=relationship_type,
            total_rows=len(rows),
            jointly_non_empty_count=jointly_non_empty_count,
            left_only_count=left_only_count,
            right_only_count=right_only_count,
            unique_pair_count=len(pair_identities),
            left_values_with_multiple_right=sum(
                len(values) > 1 for values in right_by_left.values()
            ),
            right_values_with_multiple_left=sum(
                len(values) > 1 for values in left_by_right.values()
            ),
        )

    def _anomalies(
        self,
        observations: Sequence[_Observation],
        inferred_type: str,
    ) -> List[FieldAnomalyExample]:
        anomalies: List[FieldAnomalyExample] = []
        expected_type = (
            _dominant_compatible_type(observations)
            if inferred_type == "mixed"
            else None
        )
        for item in observations:
            non_finite = _non_finite_label(item.raw_value)
            if non_finite is not None:
                anomalies.append(
                    FieldAnomalyExample(
                        code="non_finite_number",
                        business_key=item.business_key,
                        value=item.display_value,
                        observed_type=item.observed_type,
                    )
                )
            if (
                isinstance(item.raw_value, str)
                and len(item.raw_value) > self.max_text_length
            ):
                anomalies.append(
                    FieldAnomalyExample(
                        code="text_too_long",
                        business_key=item.business_key,
                        value=item.display_value,
                        observed_type=item.observed_type,
                        length=len(item.raw_value),
                    )
                )
            if isinstance(item.raw_value, (Mapping, list, tuple, set, bytes)):
                anomalies.append(
                    FieldAnomalyExample(
                        code="unsupported_structured_value",
                        business_key=item.business_key,
                        value=item.display_value,
                        observed_type=item.observed_type,
                    )
                )
            if expected_type is not None and not _types_are_compatible(
                item.observed_type, expected_type
            ):
                anomalies.append(
                    FieldAnomalyExample(
                        code="type_conflict",
                        business_key=item.business_key,
                        value=item.display_value,
                        observed_type=item.observed_type,
                        expected_type=expected_type,
                    )
                )
        return sorted(
            anomalies,
            key=lambda item: (
                item.code,
                item.business_key,
                _canonical_json(item.value),
            ),
        )


def profile_monitoring_batch_fields(
    repository: MonitoringBatchRepository,
    batch_id: str,
    *,
    top_value_limit: int = DEFAULT_TOP_VALUE_LIMIT,
    representative_value_limit: int = DEFAULT_REPRESENTATIVE_VALUE_LIMIT,
    anomaly_limit: int = DEFAULT_ANOMALY_LIMIT,
    max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
) -> MonitoringFieldProfileSnapshot:
    return MonitoringAIFieldProfiler(
        repository,
        top_value_limit=top_value_limit,
        representative_value_limit=representative_value_limit,
        anomaly_limit=anomaly_limit,
        max_text_length=max_text_length,
    ).profile_frozen_batch(batch_id)


def _positive_limit(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _required_int(
    value: Any,
    field: str,
    *,
    minimum: Optional[int] = None,
) -> int:
    """Load cached numeric metadata without Python bool coercion."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"cached field profile {field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(
            f"cached field profile {field} must be at least {minimum}"
        )
    return value


def _required_float(
    value: Any,
    field: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    """Load cached bounded numeric metadata without bool/string coercion."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"cached field profile {field} must be a number")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"cached field profile {field} must be finite")
    if minimum is not None and numeric < minimum:
        raise ValueError(
            f"cached field profile {field} must be at least {minimum}"
        )
    if maximum is not None and numeric > maximum:
        raise ValueError(
            f"cached field profile {field} must be at most {maximum}"
        )
    return numeric


def _required_sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"cached field profile {field} must be a sequence")
    return value


def _required_mapping_sequence(
    value: Any,
    field: str,
) -> Sequence[Mapping[str, Any]]:
    sequence = _required_sequence(value, field)
    if any(not isinstance(item, Mapping) for item in sequence):
        raise ValueError(
            f"cached field profile {field} must contain objects"
        )
    return sequence  # type: ignore[return-value]


def _required_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"cached field profile {field} is invalid")
    return value


def _validate_snapshot_identity(
    snapshot: MonitoringFieldProfileSnapshot,
    identity: FieldProfileBatchIdentity,
) -> None:
    expected_source_bindings = tuple(
        sorted(
            {
                (
                    binding.source_entry_id,
                    binding.source_content_sha256,
                )
                for binding in identity.source_bindings
            }
        )
    )
    expected_source_hashes = tuple(
        sorted({content_sha256 for _, content_sha256 in expected_source_bindings})
    )
    if (
        snapshot.batch_id != identity.batch_id
        or snapshot.project_id != identity.project_id
        or snapshot.batch_revision != identity.batch_version
        or snapshot.mapping_revision != identity.mapping_revision
        or snapshot.expected_domains != identity.expected_domains
        or snapshot.source_bindings != expected_source_bindings
        or snapshot.source_sha256s != expected_source_hashes
        or snapshot.row_count != identity.row_count
    ):
        raise ValueError(
            "cached field profile does not match the current batch identity"
        )


def _candidate_field_relationships(
    field_names: Sequence[str],
    *,
    numeric_fields: Sequence[str] = (),
) -> Tuple[Tuple[str, str, str], ...]:
    pairs: set[tuple[str, str, str]] = set()
    fields_by_repeat_suffix: Dict[str, Dict[str, str]] = defaultdict(dict)
    numeric_fields_by_repeat_suffix: Dict[str, set[str]] = defaultdict(set)
    for field_name in field_names:
        base_field_name, repeat_suffix = _split_repeated_field_suffix(field_name)
        fields_by_repeat_suffix[repeat_suffix][
            _canonical_field_name(base_field_name)
        ] = field_name
    for field_name in numeric_fields:
        base_field_name, repeat_suffix = _split_repeated_field_suffix(field_name)
        numeric_fields_by_repeat_suffix[repeat_suffix].add(
            _canonical_field_name(base_field_name)
        )
    for repeat_suffix in sorted(fields_by_repeat_suffix):
        pairs.update(
            _candidate_group_field_relationships(
                fields_by_repeat_suffix[repeat_suffix],
                numeric_fields=numeric_fields_by_repeat_suffix.get(
                    repeat_suffix,
                    set(),
                ),
            )
        )
    return tuple(
        sorted(
            pairs,
            key=lambda item: (
                item[0].casefold(),
                item[0],
                item[1].casefold(),
                item[1],
            ),
        )
    )


def _candidate_group_field_relationships(
    by_canonical: Mapping[str, str],
    *,
    numeric_fields: set[str],
) -> set[tuple[str, str, str]]:
    """Return structural candidates within one exact repeated-header group."""
    pairs: set[tuple[str, str, str]] = set()
    known_pairs = (
        ("AETERM", "AEDECOD"),
        ("AELLT", "AELLTCD"),
        ("AEPT", "AEPTCD"),
        ("CMTRT", "CMDECOD"),
        ("MHTERM", "MHDECOD"),
    )
    for left, right in known_pairs:
        if left in by_canonical and right in by_canonical:
            pairs.add(
                (
                    by_canonical[left],
                    by_canonical[right],
                    "term_code_pair",
                )
            )
    for right_canonical, right_field in by_canonical.items():
        suffix_length = 0
        if right_canonical.endswith("CODE"):
            suffix_length = 4
        elif right_canonical.endswith("CD"):
            suffix_length = 2
        if not suffix_length:
            continue
        left_canonical = right_canonical[:-suffix_length]
        left_field = by_canonical.get(left_canonical)
        if left_field is not None and left_field != right_field:
            pairs.add((left_field, right_field, "term_code_pair"))
    # Common EDC exports use parallel CODE/TEXT or CD/NM names rather than a
    # simple code suffix. These candidates produce same-row counts only; they do
    # not identify a coding system or dictionary version, assign medical
    # meaning, or confirm a mapping.
    for code_suffix, text_suffix in (
        ("CODE", "TEXT"),
        ("CODE", "TERM"),
        ("CD", "NM"),
    ):
        for code_canonical, code_field in by_canonical.items():
            if not code_canonical.endswith(code_suffix):
                continue
            prefix = code_canonical[: -len(code_suffix)]
            text_field = by_canonical.get(prefix + text_suffix)
            if text_field is not None and text_field != code_field:
                pairs.add((text_field, code_field, "term_code_pair"))
    for term_canonical, code_canonical in (
        ("DRUGNAME", "DRUGCODE"),
        ("DRUGPTNM", "DRUGPTCD"),
    ):
        term_field = by_canonical.get(term_canonical)
        code_field = by_canonical.get(code_canonical)
        if term_field is not None and code_field is not None:
            pairs.add((term_field, code_field, "term_code_pair"))

    # These non-coding patterns expose only observed same-row counts. They do
    # not confirm a mapping or infer medical meaning from name similarity.
    for left_canonical, right_canonical, relationship_type in (
        ("SITEID", "SITENM", "site_identity_pair"),
        ("SITEID", "SITE", "site_identity_pair"),
        ("VISIT", "VISTOID", "visit_identity_pair"),
        ("VISIT", "VISITNUM", "visit_identity_pair"),
        ("CMDOSE", "CMDOSU", "value_unit_pair"),
    ):
        left_field = by_canonical.get(left_canonical)
        right_field = by_canonical.get(right_canonical)
        if left_field is not None and right_field is not None:
            pairs.add((left_field, right_field, relationship_type))

    for unit_field in by_canonical.values():
        unit_base_field, _repeat_suffix = _split_repeated_field_suffix(unit_field)
        unit_base_upper = unit_base_field.upper()
        if unit_base_upper.endswith("_UNIT"):
            value_base_field = unit_base_field[:-5]
        elif unit_base_upper.endswith("UNIT"):
            value_base_field = unit_base_field[:-4]
            if not value_base_field or value_base_field[-1] in " _-./":
                continue
        else:
            continue
        value_canonical = _canonical_field_name(value_base_field)
        if not value_canonical or value_canonical not in numeric_fields:
            continue
        value_field = by_canonical.get(value_canonical)
        if value_field is not None and value_field != unit_field:
            pairs.add((value_field, unit_field, "value_unit_pair"))

    for performed_canonical, performed_field in by_canonical.items():
        if not performed_canonical.endswith("PERF"):
            continue
        prefix = performed_canonical[:-4]
        if not prefix:
            continue
        reason_field = by_canonical.get(prefix + "REASND")
        if reason_field is not None and reason_field != performed_field:
            pairs.add(
                (
                    performed_field,
                    reason_field,
                    "performed_reason_pair",
                )
            )
    return pairs


def _split_repeated_field_suffix(value: str) -> Tuple[str, str]:
    match = _REPEATED_FIELD_SUFFIX_PATTERN.fullmatch(value)
    if match is None:
        return value, ""
    return match.group("base"), match.group("suffix")


def _canonical_field_name(value: str) -> str:
    return re.sub(r"[\s_\-./]+", "", value).upper()


def _is_empty(value: Any) -> bool:
    return (
        value is _MISSING
        or value is None
        or (isinstance(value, str) and not value.strip())
    )


def _infer_value_type(
    value: Any,
    *,
    allow_text_boolean: bool = True,
) -> str:
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "decimal"
    if not isinstance(value, str):
        return "string"

    text = value.strip()
    lowered = text.casefold()
    if allow_text_boolean and lowered in _BOOLEAN_TEXT:
        return "boolean"
    if _INTEGER_PATTERN.fullmatch(text):
        return "integer"
    if _DECIMAL_PATTERN.fullmatch(text) or lowered in _NON_FINITE_TEXT:
        return "decimal"
    if _is_iso_datetime(text):
        return "datetime"
    if _is_iso_date(text):
        return "date"
    return "string"


def _all_values_are_boolean_like(values: Sequence[Any]) -> bool:
    if not values:
        return False
    return all(
        isinstance(value, bool)
        or (
            isinstance(value, str)
            and value.strip().casefold() in _BOOLEAN_TEXT
        )
        for value in values
    )


def _infer_field_type(observations: Sequence[_Observation]) -> str:
    observed_types = {item.observed_type for item in observations}
    if not observed_types:
        return "string"
    if observed_types <= {"integer", "decimal"}:
        return "decimal" if "decimal" in observed_types else "integer"
    if len(observed_types) == 1:
        return next(iter(observed_types))
    return "mixed"


def _dominant_compatible_type(
    observations: Sequence[_Observation],
) -> str:
    numeric_type = (
        "decimal"
        if any(item.observed_type == "decimal" for item in observations)
        else "integer"
    )
    counts: Counter[str] = Counter(
        (
            numeric_type
            if item.observed_type in {"integer", "decimal"}
            else item.observed_type
        )
        for item in observations
    )
    return min(
        counts,
        key=lambda item: (-counts[item], _TYPE_ORDER[item]),
    )


def _types_are_compatible(observed_type: str, expected_type: str) -> bool:
    return observed_type == expected_type or (
        expected_type == "decimal" and observed_type == "integer"
    )


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_iso_datetime(value: str) -> bool:
    if "T" not in value and " " not in value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _non_finite_label(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, Decimal) and not value.is_finite():
        if value.is_nan():
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, str) and value.strip().casefold() in _NON_FINITE_TEXT:
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            return None
        if parsed.is_nan():
            return "NaN"
        return "Infinity" if parsed > 0 else "-Infinity"
    return None


def _value_identity(value: Any) -> str:
    return _canonical_json(
        {
            "storage_type": type(value).__name__,
            "value": _strict_json_value(value),
        }
    )


def _display_value(value: Any) -> Any:
    if isinstance(value, str):
        if _looks_like_absolute_path(value):
            return {
                "redacted": "absolute_path",
                "length": len(value),
                "sha256": sha256(value.encode("utf-8")).hexdigest(),
            }
        if len(value) > _DISPLAY_PREVIEW_LENGTH:
            return {
                "text_preview": value[:_DISPLAY_PREVIEW_LENGTH],
                "length": len(value),
                "sha256": sha256(value.encode("utf-8")).hexdigest(),
            }
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _display_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_display_value(item) for item in value]
    if isinstance(value, set):
        return sorted(
            (_display_value(item) for item in value),
            key=_canonical_json,
        )
    if isinstance(value, bytes):
        return {
            "bytes_length": len(value),
            "sha256": sha256(value).hexdigest(),
        }
    return _strict_json_value(value)


def _looks_like_absolute_path(value: str) -> bool:
    if value.startswith("/"):
        return True
    return PureWindowsPath(value).is_absolute()


def _is_identifier_field(field_name: str) -> bool:
    normalized = re.sub(r"[\s.-]+", "_", str(field_name or "").strip().upper())
    compact = normalized.replace("_", "")
    return normalized in _IDENTIFIER_FIELD_TOKENS or compact in {
        token.replace("_", "") for token in _IDENTIFIER_FIELD_TOKENS
    }


def _strict_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        non_finite = _non_finite_label(value)
        return {"non_finite": non_finite} if non_finite is not None else value
    if isinstance(value, Decimal):
        non_finite = _non_finite_label(value)
        return (
            {"non_finite": non_finite}
            if non_finite is not None
            else {"decimal": str(value)}
        )
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, Mapping):
        return {
            str(key): _strict_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_strict_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted(
            (_strict_json_value(item) for item in value),
            key=_canonical_json,
        )
    if isinstance(value, bytes):
        return {
            "bytes_length": len(value),
            "sha256": sha256(value).hexdigest(),
        }
    rendered = repr(value)
    return {
        "unsupported_type": type(value).__name__,
        "sha256": sha256(rendered.encode("utf-8")).hexdigest(),
    }


def _complete_input_payload(batch: DiffReadyBatch) -> Dict[str, Any]:
    ordered_rows = sorted(
        batch.rows,
        key=lambda row: (
            row.domain,
            row.business_key,
            row.row_fingerprint,
        ),
    )
    return {
        "batch_id": batch.batch_id,
        "project_id": batch.project_id,
        "state": batch.state,
        "batch_revision": batch.version,
        "expected_domains": list(batch.expected_domains),
        "mapping_revision": batch.mapping_revision,
        "source_bindings": [
            {
                "source_entry_id": source_entry_id,
                "source_content_sha256": content_sha256,
            }
            for source_entry_id, content_sha256 in batch.source_bindings
        ],
        "source_sha256s": list(batch.source_hashes),
        "schema_fields": [
            {
                "domain": domain,
                "field": field,
                "source_sheet": source_sheet,
            }
            for domain, field, source_sheet in batch.schema_fields
        ],
        "rows": [
            {
                "business_key": row.business_key,
                "domain": row.domain,
                "data": _strict_json_value(row.data),
                "source_locator": _strict_json_value(row.source_locator),
                "row_fingerprint": row.row_fingerprint,
            }
            for row in ordered_rows
        ],
    }


def _hash_payload(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
