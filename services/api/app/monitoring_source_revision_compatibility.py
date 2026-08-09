"""Fail-closed source-revision lineage comparison for Phase B review.

Legacy dispositions may contain a meaning token without the source token that
bound the original listing/protocol bytes.  This module compares the explicit
identity components only.  It never chooses a candidate source revision,
opens a source file, or grants migration authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Sequence


_TOKEN_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MonitoringSourceRevisionCompatibilityError(ValueError):
    """Raised when source-revision evidence is malformed or ambiguous."""


class SourceRevisionRelation(str, Enum):
    EXACT = "exact_after_identity"
    LEGACY_SOURCE_TOKEN_MISSING = "legacy_source_revision_missing_same_meaning"
    TOKEN_MISMATCH = "source_revision_token_mismatch"
    MALFORMED = "malformed_source_revision"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringSourceRevisionCompatibilityError(
            "source-revision payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} must be a string"
        )
    text = value.strip()
    if not text:
        raise MonitoringSourceRevisionCompatibilityError(f"{field_name} is required")
    if not _TOKEN_RE.fullmatch(text):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} contains unsupported characters"
        )
    return text


def _sha256(value: Any, field_name: str) -> str:
    text = _required(value, field_name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} must be a lowercase SHA-256"
        )
    return text


def _revision_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} must be a string"
        )
    text = value.strip()
    if not text:
        raise MonitoringSourceRevisionCompatibilityError(f"{field_name} is required")
    if not _REVISION_RE.fullmatch(text):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} contains unsupported characters"
        )
    return text


def _unique_ids(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} must be a string array"
        )
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} must contain non-empty strings"
        )
    normalized = tuple(_required(value, f"{field_name} item") for value in values)
    if len(normalized) != len(set(normalized)):
        raise MonitoringSourceRevisionCompatibilityError(
            f"{field_name} must not repeat"
        )
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class MonitoringSourceRevisionIdentity:
    """Parsed family/rule/source/meaning identity; source may be legacy-empty."""

    raw: str
    family: str
    rule_id: str
    source_token: str
    meaning_token: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", _revision_text(self.raw, "source_revision.raw"))
        object.__setattr__(
            self, "family", _required(self.family, "source_revision.family")
        )
        object.__setattr__(
            self, "rule_id", _required(self.rule_id, "source_revision.rule_id")
        )
        object.__setattr__(
            self,
            "meaning_token",
            _required(self.meaning_token, "source_revision.meaning_token"),
        )
        if self.source_token is None:
            source = ""
        elif not isinstance(self.source_token, str):
            raise MonitoringSourceRevisionCompatibilityError(
                "source_revision.source_token must be a string"
            )
        else:
            source = self.source_token.strip()
        if source:
            source = _required(source, "source_revision.source_token")
        object.__setattr__(self, "source_token", source)

    @property
    def has_source_token(self) -> bool:
        return bool(self.source_token)

    def to_dict(self) -> dict[str, str]:
        return {
            "raw": self.raw,
            "family": self.family,
            "rule_id": self.rule_id,
            "source_token": self.source_token,
            "meaning_token": self.meaning_token,
        }


def parse_monitoring_source_revision(raw: str) -> MonitoringSourceRevisionIdentity:
    """Parse the supported monitoring/rux source-revision formats."""

    value = _revision_text(raw, "source_revision")
    parts = value.split(":")
    if len(parts) == 3 and parts[0] == "monitoring":
        family, rule_id, meaning_token = parts
        return MonitoringSourceRevisionIdentity(
            raw=value,
            family=family,
            rule_id=rule_id,
            source_token="",
            meaning_token=meaning_token,
        )
    if len(parts) == 4 and parts[0] in {"monitoring", "rux-p0"}:
        family, rule_id, source_token, meaning_token = parts
        return MonitoringSourceRevisionIdentity(
            raw=value,
            family=family,
            rule_id=rule_id,
            source_token=source_token,
            meaning_token=meaning_token,
        )
    raise MonitoringSourceRevisionCompatibilityError(
        "source_revision must use monitoring:<rule>:<meaning> or "
        "<family>:<rule>:<source>:<meaning>"
    )


@dataclass(frozen=True)
class MonitoringSourceRevisionComparison:
    """Comparison result for one legacy disposition record."""

    record_id: str
    project_id: str
    relation: SourceRevisionRelation | str
    legacy_source_revision: str
    expected_source_revision: str
    candidate_source_revision_ids: tuple[str, ...] = ()
    reason: str = ""
    comparison_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _required(self.record_id, "comparison.record_id")
        )
        object.__setattr__(
            self, "project_id", _required(self.project_id, "comparison.project_id")
        )
        try:
            relation = SourceRevisionRelation(self.relation)
        except ValueError as exc:
            raise MonitoringSourceRevisionCompatibilityError(
                "comparison.relation is unsupported"
            ) from exc
        object.__setattr__(self, "relation", relation)
        object.__setattr__(
            self,
            "legacy_source_revision",
            _revision_text(
                self.legacy_source_revision,
                "comparison.legacy_source_revision",
            ),
        )
        object.__setattr__(
            self,
            "expected_source_revision",
            _revision_text(
                self.expected_source_revision,
                "comparison.expected_source_revision",
            ),
        )
        candidates = _unique_ids(
            self.candidate_source_revision_ids,
            "comparison.candidate_source_revision_ids",
        )
        object.__setattr__(self, "candidate_source_revision_ids", candidates)
        if not isinstance(self.reason, str):
            raise MonitoringSourceRevisionCompatibilityError(
                "comparison.reason must be a string"
            )
        reason = self.reason.strip()
        if not reason:
            raise MonitoringSourceRevisionCompatibilityError(
                "comparison.reason is required"
            )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "comparison_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "project_id": self.project_id,
            "relation": self.relation.value,
            "legacy_source_revision": self.legacy_source_revision,
            "expected_source_revision": self.expected_source_revision,
            "candidate_source_revision_ids": list(self.candidate_source_revision_ids),
            "reason": self.reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "comparison_sha256": self.comparison_sha256}


@dataclass(frozen=True)
class MonitoringSourceRevisionCase:
    """Input row for source-token revalidation; no source content is included."""

    record_id: str
    project_id: str
    legacy_source_revision: str
    expected_source_revision: str
    candidate_source_revision_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _required(self.record_id, "case.record_id")
        )
        object.__setattr__(
            self, "project_id", _required(self.project_id, "case.project_id")
        )
        object.__setattr__(
            self,
            "legacy_source_revision",
            _revision_text(self.legacy_source_revision, "case.legacy_source_revision"),
        )
        object.__setattr__(
            self,
            "expected_source_revision",
            _revision_text(
                self.expected_source_revision, "case.expected_source_revision"
            ),
        )
        object.__setattr__(
            self,
            "candidate_source_revision_ids",
            _unique_ids(
                self.candidate_source_revision_ids,
                "case.candidate_source_revision_ids",
            ),
        )


def compare_monitoring_source_revisions(
    case: MonitoringSourceRevisionCase,
) -> MonitoringSourceRevisionComparison:
    """Compare identity tokens without inferring missing source lineage."""

    if not isinstance(case, MonitoringSourceRevisionCase):
        raise MonitoringSourceRevisionCompatibilityError(
            "case must be a MonitoringSourceRevisionCase"
        )
    try:
        legacy = parse_monitoring_source_revision(case.legacy_source_revision)
        expected = parse_monitoring_source_revision(case.expected_source_revision)
    except MonitoringSourceRevisionCompatibilityError as exc:
        return MonitoringSourceRevisionComparison(
            record_id=case.record_id,
            project_id=case.project_id,
            relation=SourceRevisionRelation.MALFORMED,
            legacy_source_revision=case.legacy_source_revision,
            expected_source_revision=case.expected_source_revision,
            candidate_source_revision_ids=case.candidate_source_revision_ids,
            reason=str(exc),
        )

    if legacy.family != expected.family or legacy.rule_id != expected.rule_id:
        relation = SourceRevisionRelation.TOKEN_MISMATCH
        reason = "source-revision family or rule identity differs"
    elif legacy.meaning_token != expected.meaning_token:
        relation = SourceRevisionRelation.TOKEN_MISMATCH
        reason = "source-revision meaning token differs"
    elif not legacy.source_token and expected.source_token:
        relation = SourceRevisionRelation.LEGACY_SOURCE_TOKEN_MISSING
        reason = (
            "legacy identity preserves meaning but lacks the source token; candidate revisions "
            "require explicit source-content revalidation"
        )
    elif legacy.source_token == expected.source_token and legacy.source_token:
        relation = SourceRevisionRelation.EXACT
        reason = "family, rule, source token and meaning token match"
    else:
        relation = SourceRevisionRelation.TOKEN_MISMATCH
        reason = "source-revision source token is absent or differs"
    return MonitoringSourceRevisionComparison(
        record_id=case.record_id,
        project_id=case.project_id,
        relation=relation,
        legacy_source_revision=case.legacy_source_revision,
        expected_source_revision=case.expected_source_revision,
        candidate_source_revision_ids=case.candidate_source_revision_ids,
        reason=reason,
    )


@dataclass(frozen=True)
class MonitoringSourceRevisionRevalidationReport:
    """Metadata-only source-token report; never a migration or approval gate."""

    comparisons: tuple[MonitoringSourceRevisionComparison, ...]
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        comparisons = tuple(self.comparisons)
        if not comparisons:
            raise MonitoringSourceRevisionCompatibilityError(
                "source-revision revalidation report must contain a comparison"
            )
        if any(
            not isinstance(item, MonitoringSourceRevisionComparison)
            for item in comparisons
        ):
            raise MonitoringSourceRevisionCompatibilityError(
                "source-revision report contains an invalid comparison"
            )
        record_ids = tuple(item.record_id for item in comparisons)
        if len(record_ids) != len(set(record_ids)):
            raise MonitoringSourceRevisionCompatibilityError(
                "source-revision comparisons must not repeat record IDs"
            )
        ordered = tuple(
            sorted(comparisons, key=lambda item: (item.project_id, item.record_id))
        )
        object.__setattr__(self, "comparisons", ordered)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    @property
    def exact_count(self) -> int:
        return sum(
            item.relation is SourceRevisionRelation.EXACT for item in self.comparisons
        )

    @property
    def revalidation_required_count(self) -> int:
        return sum(
            item.relation is not SourceRevisionRelation.EXACT
            for item in self.comparisons
        )

    @property
    def source_revalidation_complete(self) -> bool:
        return self.revalidation_required_count == 0

    @property
    def migration_ready(self) -> bool:
        """Always false: source-token equality is not authority or aggregate replay."""

        return False

    def _payload(self) -> dict[str, Any]:
        return {"comparisons": [item.to_dict() for item in self.comparisons]}

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "exact_count": self.exact_count,
            "revalidation_required_count": self.revalidation_required_count,
            "source_revalidation_complete": self.source_revalidation_complete,
            "migration_ready": self.migration_ready,
            "report_sha256": self.report_sha256,
        }


def build_monitoring_source_revision_revalidation_report(
    cases: Sequence[MonitoringSourceRevisionCase],
) -> MonitoringSourceRevisionRevalidationReport:
    """Build a deterministic source-token report from metadata-only cases."""

    normalized = tuple(cases)
    if any(not isinstance(case, MonitoringSourceRevisionCase) for case in normalized):
        raise MonitoringSourceRevisionCompatibilityError(
            "source-revision cases must contain MonitoringSourceRevisionCase values"
        )
    return MonitoringSourceRevisionRevalidationReport(
        comparisons=tuple(
            compare_monitoring_source_revisions(case) for case in normalized
        )
    )


__all__ = [
    "MonitoringSourceRevisionCase",
    "MonitoringSourceRevisionCompatibilityError",
    "MonitoringSourceRevisionComparison",
    "MonitoringSourceRevisionIdentity",
    "MonitoringSourceRevisionRevalidationReport",
    "SourceRevisionRelation",
    "build_monitoring_source_revision_revalidation_report",
    "compare_monitoring_source_revisions",
    "parse_monitoring_source_revision",
]
