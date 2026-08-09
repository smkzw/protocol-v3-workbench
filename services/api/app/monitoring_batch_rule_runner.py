from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .monitoring_batch_repository import DiffReadyBatch, NormalizedRow
from .monitoring_capability_guard import (
    MonitoringCapabilityContractError,
    require_monitoring_capability_snapshot,
    required_capabilities_for_rule,
)
from .monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
    RuleEvaluationNotSupported,
)
from .monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    validate_rule_field_lineage,
)


_SUBJECT_FIELDS = ("USUBJID", "SUBJID", "SUBJECT_ID", "SUBJECTID")
_STUDY_TREATMENT_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_ALLOWED_DERIVATION_FUNCTIONS = frozenset({"abs", "minimum", "maximum"})
_NUMERIC_RE = re.compile(
    r"^\s*(?:<=|>=|<|>)?\s*"
    r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


class MonitoringBatchRuleRunnerError(RuntimeError):
    pass


class _IndeterminateDerivation(ValueError):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class BatchRuleDiagnostic:
    diagnostic_id: str
    code: str
    message: str
    batch_id: str
    rule_pack_id: str
    rule_key: str = ""
    rule_revision_id: str = ""
    subject_id: str = ""
    current_domain: str = ""
    current_business_key: str = ""
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["details"] = dict(self.details or {})
        return value


@dataclass(frozen=True)
class BatchRuleCandidate:
    candidate_id: str
    project_id: str
    batch_id: str
    batch_version: int
    mapping_revision: str
    rule_pack_id: str
    rule_revision_id: str
    rule_key: str
    subject_id: str
    current_domain: str
    current_business_key: str
    severity: str
    confidence: str
    evidence_summary: str
    evaluation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BatchRuleRunResult:
    run_id: str
    project_id: str
    batch_id: str
    batch_version: int
    mapping_revision: str
    rule_pack_id: str
    rule_revision_ids: tuple[str, ...]
    evaluated_record_count: int
    candidates: tuple[BatchRuleCandidate, ...]
    diagnostics: tuple[BatchRuleDiagnostic, ...]
    output_sha256: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["rule_revision_ids"] = list(self.rule_revision_ids)
        value["candidates"] = [item.to_dict() for item in self.candidates]
        value["diagnostics"] = [item.to_dict() for item in self.diagnostics]
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BatchRuleRunResult":
        payload = dict(value)
        output_sha256 = payload.get("output_sha256")
        if not isinstance(output_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", output_sha256
        ) is None:
            raise MonitoringBatchRuleRunnerError(
                "persisted batch rule result output hash is noncanonical"
            )
        try:
            candidates = tuple(
                BatchRuleCandidate(**dict(item))
                for item in payload.get("candidates") or ()
            )
            diagnostics = tuple(
                BatchRuleDiagnostic(**dict(item))
                for item in payload.get("diagnostics") or ()
            )
            result = cls(
                run_id=str(payload["run_id"]),
                project_id=str(payload["project_id"]),
                batch_id=str(payload["batch_id"]),
                batch_version=int(payload["batch_version"]),
                mapping_revision=str(payload["mapping_revision"]),
                rule_pack_id=str(payload["rule_pack_id"]),
                rule_revision_ids=tuple(
                    str(item) for item in payload["rule_revision_ids"]
                ),
                evaluated_record_count=int(payload["evaluated_record_count"]),
                candidates=candidates,
                diagnostics=diagnostics,
                output_sha256=output_sha256,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringBatchRuleRunnerError(
                "persisted batch rule result is malformed"
            ) from exc
        integrity_payload = result.to_dict()
        integrity_payload.pop("output_sha256", None)
        if _json_sha256(integrity_payload) != result.output_sha256:
            raise MonitoringBatchRuleRunnerError(
                "persisted batch rule result failed output hash validation"
            )
        return result


class MonitoringBatchRuleRunner:
    """Run published deterministic rules against one immutable listing batch."""

    def __init__(self, rule_service: MonitoringProtocolRuleService):
        self.rule_service = rule_service

    def run(
        self,
        batch: DiffReadyBatch,
        *,
        rule_pack_id: str,
        capability_states: Any = None,
    ) -> BatchRuleRunResult:
        if batch.state != "frozen":
            raise MonitoringBatchRuleRunnerError(
                "batch must be frozen before deterministic rule execution"
            )
        if not str(batch.mapping_revision or "").strip():
            raise MonitoringBatchRuleRunnerError(
                "frozen batch requires an active mapping revision"
            )

        pack, all_rules = self.rule_service.repository.rule_pack(rule_pack_id)
        if pack.status != "published":
            raise MonitoringBatchRuleRunnerError(
                "only a published rule pack may be executed"
            )
        if pack.project_id != batch.project_id:
            raise MonitoringBatchRuleRunnerError(
                "rule pack and batch belong to different projects"
            )

        rules = tuple(
            sorted(
                (rule for rule in all_rules if rule.status == "enabled"),
                key=lambda item: (item.rule_key, item.rule_revision_id),
            )
        )
        revision_ids = tuple(rule.rule_revision_id for rule in rules)
        run_id = _stable_id(
            "monbatchrun",
            batch.project_id,
            batch.batch_id,
            batch.version,
            batch.mapping_revision,
            rule_pack_id,
            revision_ids,
        )
        rows_by_subject, grouping_diagnostics = _group_rows_by_subject(
            batch,
            rule_pack_id=rule_pack_id,
        )
        available_domains = {
            row.domain.upper() for row in batch.rows
        } | {
            domain.upper() for domain, _field, _sheet in batch.schema_fields
        }

        candidates: list[BatchRuleCandidate] = []
        diagnostics = list(grouping_diagnostics)
        evaluated_count = 0
        if not rules:
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    code="no_enabled_rules",
                    message="published rule pack contains no enabled rules",
                )
            )

        for rule in rules:
            if capability_states is not None:
                blocked = self._capability_diagnostics(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    capability_states=capability_states,
                )
                if blocked:
                    diagnostics.extend(blocked)
                    continue
            rule_diagnostics = self._run_rule(
                batch=batch,
                rule_pack_id=rule_pack_id,
                rule=rule,
                rows_by_subject=rows_by_subject,
                available_domains=available_domains,
            )
            candidates.extend(rule_diagnostics[0])
            diagnostics.extend(rule_diagnostics[1])
            evaluated_count += rule_diagnostics[2]

        candidates_value = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.rule_key,
                    item.subject_id,
                    item.current_business_key,
                    item.candidate_id,
                ),
            )
        )
        diagnostics_value = tuple(
            sorted(
                diagnostics,
                key=lambda item: (
                    item.rule_key,
                    item.subject_id,
                    item.current_business_key,
                    item.code,
                    item.diagnostic_id,
                ),
            )
        )
        output_payload = {
            "run_id": run_id,
            "project_id": batch.project_id,
            "batch_id": batch.batch_id,
            "batch_version": batch.version,
            "mapping_revision": batch.mapping_revision,
            "rule_pack_id": rule_pack_id,
            "rule_revision_ids": revision_ids,
            "evaluated_record_count": evaluated_count,
            "candidates": [item.to_dict() for item in candidates_value],
            "diagnostics": [item.to_dict() for item in diagnostics_value],
        }
        return BatchRuleRunResult(
            run_id=run_id,
            project_id=batch.project_id,
            batch_id=batch.batch_id,
            batch_version=batch.version,
            mapping_revision=str(batch.mapping_revision),
            rule_pack_id=rule_pack_id,
            rule_revision_ids=revision_ids,
            evaluated_record_count=evaluated_count,
            candidates=candidates_value,
            diagnostics=diagnostics_value,
            output_sha256=_json_sha256(output_payload),
        )

    @staticmethod
    def _capability_diagnostics(
        *,
        batch: DiffReadyBatch,
        rule_pack_id: str,
        rule: MonitoringRuleDefinition,
        capability_states: Any,
    ) -> list[BatchRuleDiagnostic]:
        diagnostics: list[BatchRuleDiagnostic] = []
        for capability_id in required_capabilities_for_rule(rule):
            try:
                require_monitoring_capability_snapshot(
                    capability_states,
                    capability_id,
                )
            except MonitoringCapabilityContractError as exc:
                diagnostics.append(
                    _diagnostic(
                        batch=batch,
                        rule_pack_id=rule_pack_id,
                        rule=rule,
                        code=exc.code,
                        message=exc.message,
                        details={
                            "capability_id": capability_id,
                            "capability_state": exc.state,
                            "limitation_codes": list(
                                exc.limitation_codes
                            ),
                            "rule_execution_skipped": True,
                        },
                    )
                )
        return diagnostics

    def _run_rule(
        self,
        *,
        batch: DiffReadyBatch,
        rule_pack_id: str,
        rule: MonitoringRuleDefinition,
        rows_by_subject: Mapping[str, Mapping[str, Sequence[NormalizedRow]]],
        available_domains: set[str],
    ) -> tuple[
        list[BatchRuleCandidate],
        list[BatchRuleDiagnostic],
        int,
    ]:
        candidates: list[BatchRuleCandidate] = []
        diagnostics: list[BatchRuleDiagnostic] = []
        evaluated_count = 0
        try:
            lineage = validate_rule_field_lineage(
                field_lineage=dict(rule.field_lineage),
                preconditions=rule.preconditions,
                trigger_expression=rule.trigger_expression,
                exclusions=rule.exclusions,
                evidence_template=rule.evidence_template,
                required_domains=rule.required_domains,
            )
        except MonitoringProtocolRuleError as exc:
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    code="invalid_field_lineage",
                    message=str(exc),
                )
            )
            return candidates, diagnostics, evaluated_count

        current_fields, related_domains = _current_predicate_fields(rule)
        anchor_domain = _anchor_domain(
            rule,
            lineage,
            current_fields=current_fields,
            related_domains=related_domains,
        )
        if not anchor_domain:
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    code="ambiguous_anchor_domain",
                    message="rule current-record domain cannot be determined",
                )
            )
            return candidates, diagnostics, evaluated_count
        if anchor_domain not in available_domains:
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    code="missing_anchor_domain",
                    message=f"current-record domain {anchor_domain} is absent",
                    current_domain=anchor_domain,
                    details={
                        "required_domain": anchor_domain,
                        "available_domains": sorted(available_domains),
                        "study_treatment_domains_are_distinct": (
                            anchor_domain in _STUDY_TREATMENT_DOMAINS
                        ),
                    },
                )
            )
            return candidates, diagnostics, evaluated_count

        for subject_id, subject_domains in sorted(rows_by_subject.items()):
            anchor_rows = tuple(subject_domains.get(anchor_domain, ()))
            for current_row in anchor_rows:
                record, materialization_diagnostics = _materialize_record(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    lineage=lineage,
                    subject_id=subject_id,
                    anchor_domain=anchor_domain,
                    current_row=current_row,
                    subject_domains=subject_domains,
                    current_fields=current_fields,
                    related_domains=related_domains,
                )
                diagnostics.extend(materialization_diagnostics)
                related_records = {
                    domain: [
                        _record_from_row(batch, row)
                        for row in subject_domains.get(domain, ())
                    ]
                    for domain in sorted(available_domains)
                }
                try:
                    evaluation = self.rule_service.evaluate_record(
                        rule,
                        record,
                        observed_domains=available_domains,
                        related_records=related_records,
                    )
                except (MonitoringProtocolRuleError, RuleEvaluationNotSupported) as exc:
                    diagnostics.append(
                        _diagnostic(
                            batch=batch,
                            rule_pack_id=rule_pack_id,
                            rule=rule,
                            subject_id=subject_id,
                            current_domain=anchor_domain,
                            current_business_key=current_row.business_key,
                            code="rule_not_executable",
                            message=str(exc),
                        )
                    )
                    continue
                evaluated_count += 1
                evaluation_payload = evaluation.public_dict()
                evaluation_state = str(
                    evaluation.evidence.get("evaluation_state") or ""
                ).lower()
                if evaluation.matched:
                    candidates.append(
                        BatchRuleCandidate(
                            candidate_id=_stable_id(
                                "moncandidate",
                                batch.batch_id,
                                batch.version,
                                batch.mapping_revision,
                                rule_pack_id,
                                rule.rule_revision_id,
                                subject_id,
                                anchor_domain,
                                current_row.business_key,
                            ),
                            project_id=batch.project_id,
                            batch_id=batch.batch_id,
                            batch_version=batch.version,
                            mapping_revision=str(batch.mapping_revision),
                            rule_pack_id=rule_pack_id,
                            rule_revision_id=rule.rule_revision_id,
                            rule_key=rule.rule_key,
                            subject_id=subject_id,
                            current_domain=anchor_domain,
                            current_business_key=current_row.business_key,
                            severity=rule.severity,
                            confidence=rule.confidence,
                            evidence_summary=evaluation.evidence_summary,
                            evaluation=evaluation_payload,
                        )
                    )
                elif evaluation_state == "indeterminate":
                    diagnostics.append(
                        _diagnostic(
                            batch=batch,
                            rule_pack_id=rule_pack_id,
                            rule=rule,
                            subject_id=subject_id,
                            current_domain=anchor_domain,
                            current_business_key=current_row.business_key,
                            code="evaluation_indeterminate",
                            message=evaluation.evidence_summary,
                            details={
                                "missing_required_domains": list(
                                    evaluation.missing_required_domains
                                ),
                                "missing_evidence": list(
                                    evaluation.evidence.get("missing_evidence")
                                    or ()
                                ),
                            },
                        )
                    )
        return candidates, diagnostics, evaluated_count


def _group_rows_by_subject(
    batch: DiffReadyBatch,
    *,
    rule_pack_id: str,
) -> tuple[
    dict[str, dict[str, list[NormalizedRow]]],
    tuple[BatchRuleDiagnostic, ...],
]:
    grouped: dict[str, dict[str, list[NormalizedRow]]] = {}
    diagnostics: list[BatchRuleDiagnostic] = []
    for row in sorted(batch.rows, key=lambda item: item.business_key):
        subject_id, conflict = _subject_id(row.data)
        if not subject_id:
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    code=(
                        "conflicting_subject_identifiers"
                        if conflict
                        else "missing_subject_identifier"
                    ),
                    message=(
                        "row contains conflicting subject identifiers"
                        if conflict
                        else "row has no deterministic subject identifier"
                    ),
                    current_domain=row.domain,
                    current_business_key=row.business_key,
                    details={"subject_fields": list(_SUBJECT_FIELDS)},
                )
            )
            continue
        grouped.setdefault(subject_id, {}).setdefault(
            row.domain.upper(), []
        ).append(row)
    return grouped, tuple(diagnostics)


def _subject_id(data: Mapping[str, Any]) -> tuple[str, bool]:
    values: list[str] = []
    normalized_data = {str(key).upper(): value for key, value in data.items()}
    for field in _SUBJECT_FIELDS:
        value = normalized_data.get(field)
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    if len(values) == 1:
        return values[0], False
    return "", len(values) > 1


def _anchor_domain(
    rule: MonitoringRuleDefinition,
    lineage: Mapping[str, Mapping[str, Any]],
    *,
    current_fields: set[str] | None = None,
    related_domains: set[str] | None = None,
) -> str:
    if current_fields is None or related_domains is None:
        current_fields, related_domains = _current_predicate_fields(rule)
    scores: dict[str, int] = {}
    for field_name in current_fields:
        bindings = [
            binding
            for binding in lineage.values()
            if str(binding["field"]) == field_name
            and str(binding["domain"]).upper() not in related_domains
        ]
        for binding in bindings:
            domain = str(binding["domain"]).upper()
            scores[domain] = scores.get(domain, 0) + 1
    if not scores:
        return ""
    top_score = max(scores.values())
    winners = sorted(
        domain for domain, score in scores.items() if score == top_score
    )
    return winners[0] if len(winners) == 1 else ""


def _current_predicate_fields(
    rule: MonitoringRuleDefinition,
) -> tuple[set[str], set[str]]:
    fields: set[str] = set()
    related_domains: set[str] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, Mapping) or len(node) != 1:
            return
        operator, operand = next(iter(node.items()))
        if operator in {"all", "any"}:
            for child in operand:
                visit(child)
            return
        if operator == "not":
            visit(operand)
            return
        if not isinstance(operand, Mapping):
            return
        if operator == "no_corresponding_record":
            domain = str(operand.get("domain") or "").upper()
            if domain:
                related_domains.add(domain)
            for condition in operand.get("match") or ():
                current = str(condition.get("current_field") or "").strip()
                if current:
                    fields.add(current)
            window = operand.get("date_window") or {}
            current_date = str(
                window.get("current_date_field") or ""
            ).strip()
            if current_date:
                fields.add(current_date)
            return
        for key in (
            "field",
            "other_field",
            "numerator_field",
            "denominator_field",
            "current_field",
            "current_date_field",
        ):
            value = str(operand.get(key) or "").strip()
            if value:
                fields.add(value)

    for expression in (
        rule.preconditions,
        rule.trigger_expression,
        rule.exclusions,
    ):
        visit(expression)
    return fields, related_domains


def _materialize_record(
    *,
    batch: DiffReadyBatch,
    rule_pack_id: str,
    rule: MonitoringRuleDefinition,
    lineage: Mapping[str, Mapping[str, Any]],
    subject_id: str,
    anchor_domain: str,
    current_row: NormalizedRow,
    subject_domains: Mapping[str, Sequence[NormalizedRow]],
    current_fields: set[str],
    related_domains: set[str],
) -> tuple[dict[str, Any], tuple[BatchRuleDiagnostic, ...]]:
    record = _record_from_row(batch, current_row)
    diagnostics: list[BatchRuleDiagnostic] = []
    raw_role_values: dict[str, Any] = {}
    raw_role_locators: dict[str, list[Any]] = {}

    for role, binding in sorted(lineage.items()):
        lineage_value = binding["lineage"]
        if lineage_value["source_type"] != "raw_listing_field":
            continue
        domain = str(binding["domain"]).upper()
        field_name = str(binding["field"])
        try:
            value, locators = _raw_role_value(
                field_name=field_name,
                domain=domain,
                anchor_domain=anchor_domain,
                current_row=current_row,
                subject_domains=subject_domains,
            )
        except _IndeterminateDerivation as exc:
            diagnostics.append(
                _materialization_diagnostic(
                    exc,
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    subject_id=subject_id,
                    current_row=current_row,
                    anchor_domain=anchor_domain,
                    details={"field_role": role, "field": field_name, "domain": domain},
                )
            )
            continue
        raw_role_values[role] = value
        raw_role_locators[role] = locators
        is_current_field = (
            field_name in current_fields and domain not in related_domains
        )
        if is_current_field and isinstance(value, list):
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    subject_id=subject_id,
                    current_domain=anchor_domain,
                    current_business_key=current_row.business_key,
                    code="ambiguous_raw_field",
                    message=(
                        f"cannot select one value for current field "
                        f"{domain}.{field_name}"
                    ),
                    details={
                        "field_role": role,
                        "field": field_name,
                        "domain": domain,
                        "value_count": len(value),
                    },
                )
            )
        elif is_current_field:
            record[field_name] = value
            _extend_record_locators(record, locators)

    derived_metadata: dict[str, Any] = {}
    for role, binding in sorted(lineage.items()):
        lineage_value = binding["lineage"]
        if lineage_value["source_type"] != "auditable_base_value":
            continue
        field_name = str(binding["field"])
        input_roles = tuple(lineage_value["input_field_roles"])
        missing_roles = [
            input_role
            for input_role in input_roles
            if input_role not in raw_role_values
        ]
        if missing_roles:
            diagnostics.append(
                _diagnostic(
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    subject_id=subject_id,
                    current_domain=anchor_domain,
                    current_business_key=current_row.business_key,
                    code="derived_input_missing",
                    message=f"cannot derive {field_name}: raw inputs are incomplete",
                    details={
                        "field_role": role,
                        "field": field_name,
                        "missing_input_roles": missing_roles,
                    },
                )
            )
            continue
        try:
            calculated = _evaluate_derivation(
                str(lineage_value["calculation_expression"]),
                {
                    input_role: raw_role_values[input_role]
                    for input_role in input_roles
                },
            )
            unit = _derived_unit(
                lineage_value,
                raw_role_values=raw_role_values,
            )
        except _IndeterminateDerivation as exc:
            diagnostics.append(
                _materialization_diagnostic(
                    exc,
                    batch=batch,
                    rule_pack_id=rule_pack_id,
                    rule=rule,
                    subject_id=subject_id,
                    current_row=current_row,
                    anchor_domain=anchor_domain,
                    details={"field_role": role, "field": field_name},
                )
            )
            continue
        value = _public_scalar(calculated)
        input_locators = _dedupe_values(
            locator
            for input_role in input_roles
            for locator in raw_role_locators[input_role]
        )
        record[field_name] = value
        derived_metadata[field_name] = {
            "source_type": "auditable_base_value",
            "input_fields": [
                str(lineage[input_role]["field"]) for input_role in input_roles
            ],
            "input_field_roles": list(input_roles),
            "input_locators": input_locators,
            "calculation_expression": lineage_value["calculation_expression"],
            "unit": unit,
            "calculated_value": value,
            "batch_id": batch.batch_id,
            "mapping_revision": batch.mapping_revision,
            "rule_revision_id": rule.rule_revision_id,
        }
        _extend_record_locators(record, input_locators)
    if derived_metadata:
        record["__auditable_base_values__"] = derived_metadata
    return record, tuple(diagnostics)


def _raw_role_value(
    *,
    field_name: str,
    domain: str,
    anchor_domain: str,
    current_row: NormalizedRow,
    subject_domains: Mapping[str, Sequence[NormalizedRow]],
) -> tuple[Any, list[Any]]:
    if domain == anchor_domain:
        if field_name not in current_row.data or _missing(current_row.data[field_name]):
            raise _IndeterminateDerivation(
                "raw_field_missing",
                f"current row is missing {domain}.{field_name}",
            )
        return current_row.data[field_name], [current_row.source_locator]

    rows = tuple(subject_domains.get(domain, ()))
    values = [
        (row.data[field_name], row.source_locator)
        for row in rows
        if field_name in row.data and not _missing(row.data[field_name])
    ]
    if not values:
        raise _IndeterminateDerivation(
            "raw_field_missing",
            f"subject search set is missing {domain}.{field_name}",
        )
    unique_values = _unique_scalars(value for value, _locator in values)
    locators = _dedupe_values(locator for _value, locator in values)
    if len(unique_values) == 1:
        return unique_values[0], locators
    return [value for value, _locator in values], locators


def _record_from_row(
    batch: DiffReadyBatch,
    row: NormalizedRow,
) -> dict[str, Any]:
    return {
        **dict(row.data),
        "__source_locator__": [dict(row.source_locator)],
        "__batch_row__": {
            "batch_id": batch.batch_id,
            "batch_version": batch.version,
            "mapping_revision": batch.mapping_revision,
            "business_key": row.business_key,
            "domain": row.domain,
            "row_fingerprint": row.row_fingerprint,
        },
    }


def _extend_record_locators(record: dict[str, Any], locators: Iterable[Any]) -> None:
    current = list(record.get("__source_locator__") or ())
    record["__source_locator__"] = _dedupe_values([*current, *locators])


def _evaluate_derivation(expression: str, values: Mapping[str, Any]) -> Any:
    if len(expression) > 2_000:
        raise _IndeterminateDerivation(
            "unsupported_derivation",
            "derivation expression is too long",
        )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise _IndeterminateDerivation(
            "unsupported_derivation",
            "derivation expression is not valid deterministic DSL",
        ) from exc
    return _eval_derivation_node(tree.body, values)


def _eval_derivation_node(node: ast.AST, values: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise _IndeterminateDerivation(
                "derived_input_missing",
                f"unknown derivation input role: {node.id}",
            )
        return values[node.id]
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _IndeterminateDerivation(
                "unsupported_derivation",
                "only numeric constants are permitted",
            )
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(
        node.op, (ast.UAdd, ast.USub)
    ):
        value = _numeric_scalar(_eval_derivation_node(node.operand, values))
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
    ):
        left = _numeric_scalar(_eval_derivation_node(node.left, values))
        right = _numeric_scalar(_eval_derivation_node(node.right, values))
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise _IndeterminateDerivation(
                "division_by_zero",
                "derivation denominator is zero",
            )
        return left / right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = node.func.id
        if (
            function not in _ALLOWED_DERIVATION_FUNCTIONS
            or node.keywords
            or len(node.args) != 1
        ):
            raise _IndeterminateDerivation(
                "unsupported_derivation",
                "derivation function is outside the strict whitelist",
                {"allowed_functions": sorted(_ALLOWED_DERIVATION_FUNCTIONS)},
            )
        value = _eval_derivation_node(node.args[0], values)
        if function == "abs":
            return abs(_numeric_scalar(value))
        return _deterministic_extreme(value, minimum=function == "minimum")
    raise _IndeterminateDerivation(
        "unsupported_derivation",
        f"unsupported derivation syntax: {type(node).__name__}",
        {"allowed_functions": sorted(_ALLOWED_DERIVATION_FUNCTIONS)},
    )


def _numeric_scalar(value: Any) -> Decimal:
    values = value if isinstance(value, (list, tuple)) else [value]
    if len(values) != 1:
        raise _IndeterminateDerivation(
            "ambiguous_derived_input",
            "ordinary arithmetic requires one deterministic value per input",
            {"value_count": len(values)},
        )
    raw = values[0]
    if isinstance(raw, bool) or raw is None:
        raise _IndeterminateDerivation(
            "invalid_numeric_input",
            "derivation input is not numeric",
        )
    if isinstance(raw, Decimal):
        return raw
    match = _NUMERIC_RE.fullmatch(str(raw))
    if not match:
        raise _IndeterminateDerivation(
            "invalid_numeric_input",
            f"derivation input is not a deterministic number: {raw!r}",
        )
    try:
        return Decimal(match.group("number"))
    except InvalidOperation as exc:
        raise _IndeterminateDerivation(
            "invalid_numeric_input",
            f"derivation input is not a deterministic number: {raw!r}",
        ) from exc


def _deterministic_extreme(value: Any, *, minimum: bool) -> Any:
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    values = [item for item in values if not _missing(item)]
    if not values:
        raise _IndeterminateDerivation(
            "derived_input_missing",
            "minimum/maximum input set is empty",
        )
    numeric: list[Decimal] = []
    for item in values:
        try:
            numeric.append(_numeric_scalar(item))
        except _IndeterminateDerivation:
            numeric = []
            break
    if numeric:
        return min(numeric) if minimum else max(numeric)

    dated: list[tuple[datetime, str]] = []
    for item in values:
        text = str(item).strip()
        try:
            parsed = (
                datetime.fromisoformat(text.replace("Z", "+00:00"))
                if "T" in text
                else datetime.combine(date.fromisoformat(text), datetime.min.time())
            )
        except ValueError as exc:
            raise _IndeterminateDerivation(
                "invalid_ordered_input",
                "minimum/maximum accepts only deterministic numbers or full ISO dates",
                {"value": text},
            ) from exc
        dated.append((parsed, text))
    selected = min(dated) if minimum else max(dated)
    return selected[1]


def _derived_unit(
    lineage: Mapping[str, Any],
    *,
    raw_role_values: Mapping[str, Any],
) -> str:
    if "unit_literal" in lineage:
        return str(lineage["unit_literal"])
    unit_role = str(lineage.get("unit_field_role") or "")
    value = raw_role_values.get(unit_role)
    values = _unique_scalars(
        value if isinstance(value, (list, tuple)) else [value]
    )
    if len(values) != 1 or _missing(values[0]):
        raise _IndeterminateDerivation(
            "ambiguous_unit",
            "derived value unit is missing or ambiguous",
            {"unit_field_role": unit_role},
        )
    return str(values[0])


def _materialization_diagnostic(
    exc: _IndeterminateDerivation,
    *,
    batch: DiffReadyBatch,
    rule_pack_id: str,
    rule: MonitoringRuleDefinition,
    subject_id: str,
    current_row: NormalizedRow,
    anchor_domain: str,
    details: Mapping[str, Any],
) -> BatchRuleDiagnostic:
    return _diagnostic(
        batch=batch,
        rule_pack_id=rule_pack_id,
        rule=rule,
        subject_id=subject_id,
        current_domain=anchor_domain,
        current_business_key=current_row.business_key,
        code=exc.code,
        message=str(exc),
        details={**details, **exc.details},
    )


def _diagnostic(
    *,
    batch: DiffReadyBatch,
    rule_pack_id: str,
    code: str,
    message: str,
    rule: MonitoringRuleDefinition | None = None,
    subject_id: str = "",
    current_domain: str = "",
    current_business_key: str = "",
    details: Mapping[str, Any] | None = None,
) -> BatchRuleDiagnostic:
    rule_key = rule.rule_key if rule else ""
    rule_revision_id = rule.rule_revision_id if rule else ""
    details_value = dict(details or {})
    return BatchRuleDiagnostic(
        diagnostic_id=_stable_id(
            "mondiagnostic",
            batch.batch_id,
            batch.version,
            batch.mapping_revision,
            rule_pack_id,
            rule_revision_id,
            subject_id,
            current_domain,
            current_business_key,
            code,
            details_value,
        ),
        code=code,
        message=message,
        batch_id=batch.batch_id,
        rule_pack_id=rule_pack_id,
        rule_key=rule_key,
        rule_revision_id=rule_revision_id,
        subject_id=subject_id,
        current_domain=current_domain,
        current_business_key=current_business_key,
        details=details_value,
    )


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _unique_scalars(values: Iterable[Any]) -> list[Any]:
    unique: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = _canonical_json(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _dedupe_values(values: Iterable[Any]) -> list[Any]:
    return _unique_scalars(values)


def _public_scalar(value: Any) -> Any:
    if not isinstance(value, Decimal):
        return value
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _json_sha256(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{_json_sha256(parts)[:24]}"
