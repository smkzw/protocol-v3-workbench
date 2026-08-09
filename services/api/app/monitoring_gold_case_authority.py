from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Mapping, Protocol

from .monitoring_batch_repository import (
    BASELINE_ELIGIBLE_SOURCE_CLASSES,
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
    SourceRegistration,
)
from .monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    RuleDiagnosticCase,
    RuleGoldStandardCase,
    normalize_rule_field_lineage_units,
)


class SourceRegistryReader(Protocol):
    def list_results(self, project_id: str) -> list[Any]: ...


class MonitoringGoldCaseAuthorityError(ValueError):
    pass


_BATCH_REVISION_RE = re.compile(r"^(?P<batch_id>monbatch_[a-f0-9]+)@v(?P<version>[1-9][0-9]*)$")
_CANONICAL_ROW_LOCATOR_RE = re.compile(
    r"^listing:(?P<hash>[0-9a-fA-F]{64}):sheet:"
    r"(?P<sheet>.+):row:(?P<row>[1-9][0-9]*)$"
)
_LEGACY_ROW_LOCATOR_RE = re.compile(
    r"^listing:sheet:(?P<sheet>.+):row:(?P<row>[1-9][0-9]*)$"
)


def _exact_sha256_equal(left: Any, right: Any) -> bool:
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and re.fullmatch(r"[0-9a-f]{64}", left) is not None
        and re.fullmatch(r"[0-9a-f]{64}", right) is not None
        and left == right
    )


def monitoring_source_revision(source: SourceRegistration) -> str:
    validation_identity = sha256(source.validation_id.encode("utf-8")).hexdigest()[:16]
    return (
        f"{source.source_id}@validation:{validation_identity}"
        f"@v{source.validation_revision}"
    )


def monitoring_batch_revision(batch_id: str, version: int) -> str:
    return f"{batch_id}@v{int(version)}"


def _canonical_row_locator(
    source_locator: Mapping[str, Any],
    *,
    fallback_hash: str,
) -> str:
    if not isinstance(fallback_hash, str) or re.fullmatch(
        r"[0-9a-f]{64}", fallback_hash
    ) is None:
        raise MonitoringGoldCaseAuthorityError(
            "normalized batch row lacks a canonical source locator"
        )
    fallback_hash = fallback_hash

    locator_hash_raw = source_locator.get("source_content_sha256")
    if locator_hash_raw not in (None, ""):
        if not _exact_sha256_equal(locator_hash_raw, fallback_hash):
            raise MonitoringGoldCaseAuthorityError(
                "normalized batch row source locator hash does not match "
                "the attached source"
            )
        locator_hash = locator_hash_raw
    else:
        locator_hash = fallback_hash

    def structured_sheet() -> str | None:
        values: list[str] = []
        for field in ("sheet", "sheet_name"):
            if field not in source_locator:
                continue
            value = str(source_locator.get(field) or "").strip()
            if not value:
                raise MonitoringGoldCaseAuthorityError(
                    "normalized batch row lacks a canonical source locator"
                )
            values.append(value)
        if len(set(values)) > 1:
            raise MonitoringGoldCaseAuthorityError(
                "normalized batch row has ambiguous source locator coordinates"
            )
        return values[0] if values else None

    def structured_row() -> int | None:
        values: list[int] = []
        for field in ("row", "row_number"):
            if field not in source_locator:
                continue
            raw = source_locator.get(field)
            if isinstance(raw, bool):
                raise MonitoringGoldCaseAuthorityError(
                    "normalized batch row lacks a canonical source locator"
                )
            if isinstance(raw, int):
                value = raw
            elif isinstance(raw, str) and re.fullmatch(
                r"[1-9][0-9]*",
                raw.strip(),
            ):
                value = int(raw.strip())
            else:
                raise MonitoringGoldCaseAuthorityError(
                    "normalized batch row lacks a canonical source locator"
                )
            if value < 1:
                raise MonitoringGoldCaseAuthorityError(
                    "normalized batch row lacks a canonical source locator"
                )
            values.append(value)
        if len(set(values)) > 1:
            raise MonitoringGoldCaseAuthorityError(
                "normalized batch row has ambiguous source locator coordinates"
            )
        return values[0] if values else None

    explicit = str(source_locator.get("locator") or "").strip()
    explicit_sheet: str | None = None
    explicit_row: int | None = None
    if explicit:
        canonical_match = _CANONICAL_ROW_LOCATOR_RE.fullmatch(explicit)
        legacy_match = _LEGACY_ROW_LOCATOR_RE.fullmatch(explicit)
        matched = canonical_match or legacy_match
        if matched is None:
            raise MonitoringGoldCaseAuthorityError(
                "normalized batch row lacks a canonical source locator"
            )
        if canonical_match is not None:
            explicit_hash = canonical_match.group("hash")
            if explicit_hash != explicit_hash.lower():
                raise MonitoringGoldCaseAuthorityError(
                    "normalized batch row explicit source locator hash must be "
                    "an exact lowercase SHA-256"
                )
            if explicit_hash != fallback_hash:
                raise MonitoringGoldCaseAuthorityError(
                    "normalized batch row explicit source locator hash does "
                    "not match the attached source"
                )
        explicit_sheet = str(matched.group("sheet") or "").strip()
        explicit_row = int(matched.group("row"))

    sheet = structured_sheet()
    row = structured_row()
    if explicit_sheet is not None:
        if sheet is not None and sheet != explicit_sheet:
            raise MonitoringGoldCaseAuthorityError(
                "normalized batch row has ambiguous source locator coordinates"
            )
        if row is not None and row != explicit_row:
            raise MonitoringGoldCaseAuthorityError(
                "normalized batch row has ambiguous source locator coordinates"
            )
        sheet = explicit_sheet
        row = explicit_row
    if not sheet or row is None:
        raise MonitoringGoldCaseAuthorityError(
            "normalized batch row lacks a canonical source locator"
        )
    return f"listing:{locator_hash}:sheet:{sheet}:row:{row}"


def _record_source_locators(record: Mapping[str, Any]) -> tuple[str, ...]:
    raw = record.get("__source_locator__")
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else ()
    if isinstance(raw, (list, tuple)):
        values = tuple(str(item or "").strip() for item in raw)
        if any(not item for item in values):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard record contains an empty source locator"
            )
        if len(set(values)) != len(values):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard record contains duplicate source locators"
            )
        return values
    if raw is None:
        return ()
    raise MonitoringGoldCaseAuthorityError(
        "gold standard record source locator must be text or a list of text"
    )


def _expected_record_roles(
    case: RuleGoldStandardCase | RuleDiagnosticCase,
) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {}

    def add(record: Mapping[str, Any], role: str) -> None:
        locators = _record_source_locators(record)
        if not locators:
            raise MonitoringGoldCaseAuthorityError(
                f"gold standard {role} record lacks an immutable source locator"
            )
        for locator in locators:
            roles.setdefault(locator, set()).add(role)

    add(case.input_record, "current")
    if case.previous_record:
        add(case.previous_record, "previous")
    for domain, records in sorted(case.related_records.items()):
        for index, record in enumerate(records):
            add(record, f"related:{domain}:{index}")
    return roles


def _records_by_role(
    case: RuleGoldStandardCase | RuleDiagnosticCase,
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {"current": case.input_record}
    if case.previous_record:
        records["previous"] = case.previous_record
    for domain, related in sorted(case.related_records.items()):
        for index, record in enumerate(related):
            records[f"related:{domain}:{index}"] = record
    return records


def _canonical_domain(domain: str) -> str:
    value = str(domain or "").strip().upper().split("--", 1)[0]
    for prefix, canonical in (
        ("CM", "CM"),
        ("LB", "LB"),
        ("AE", "AE"),
        ("MH", "MH"),
        ("SV", "SV"),
        ("ECA", "EC"),
        ("ECB", "EC"),
        ("EC", "EC"),
        ("DAB", "DA"),
        ("DAA", "DA"),
        ("DA", "DA"),
    ):
        if value.startswith(prefix):
            return canonical
    return value


def _decimal_value(value: Any) -> Decimal:
    normalized = re.sub(r"^\s*(?:<=|>=|<|>)\s*", "", str(value or "").strip())
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise MonitoringGoldCaseAuthorityError(
            f"deterministic calculation input is not numeric: {value!r}"
        ) from exc


def _scalar(values: Any) -> Any:
    if not isinstance(values, list):
        return values
    non_missing = [value for value in values if str(value or "").strip()]
    if not non_missing:
        raise MonitoringGoldCaseAuthorityError(
            "deterministic calculation input is missing"
        )
    distinct = {str(value) for value in non_missing}
    if len(distinct) != 1:
        raise MonitoringGoldCaseAuthorityError(
            "deterministic scalar calculation received multiple source values"
        )
    return non_missing[0]


def _ordered_value(values: list[Any], *, maximum: bool) -> Any:
    non_missing = [value for value in values if str(value or "").strip()]
    if not non_missing:
        raise MonitoringGoldCaseAuthorityError(
            "deterministic aggregate calculation has no source values"
        )
    try:
        decimals = [_decimal_value(value) for value in non_missing]
        return max(decimals) if maximum else min(decimals)
    except MonitoringGoldCaseAuthorityError:
        pass
    normalized_dates: list[date] = []
    try:
        normalized_dates = [date.fromisoformat(str(value).strip()) for value in non_missing]
    except ValueError:
        normalized_dates = []
    if normalized_dates:
        selected = max(normalized_dates) if maximum else min(normalized_dates)
        return selected.isoformat()
    return max(map(str, non_missing)) if maximum else min(map(str, non_missing))


def _evaluate_deterministic_expression(
    expression: str,
    role_values: Mapping[str, list[Any]],
) -> Any:
    """Evaluate the small lineage DSL without executing case-supplied code."""

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise MonitoringGoldCaseAuthorityError(
            "canonical lineage calculation is not valid deterministic DSL"
        ) from exc

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Name):
            if node.id not in role_values:
                raise MonitoringGoldCaseAuthorityError(
                    f"canonical lineage input role is unavailable: {node.id}"
                )
            return list(role_values[node.id])
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _decimal_value(_scalar(evaluate(node.operand)))
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.Div),
        ):
            left = _decimal_value(_scalar(evaluate(node.left)))
            right = _decimal_value(_scalar(evaluate(node.right)))
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise MonitoringGoldCaseAuthorityError(
                    "deterministic calculation attempted division by zero"
                )
            return left / right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords:
                raise MonitoringGoldCaseAuthorityError(
                    "deterministic calculation does not accept keyword arguments"
                )
            function = node.func.id
            arguments = [evaluate(argument) for argument in node.args]
            if function in {"minimum", "maximum"} and len(arguments) == 1:
                values = (
                    arguments[0]
                    if isinstance(arguments[0], list)
                    else [arguments[0]]
                )
                return _ordered_value(values, maximum=function == "maximum")
            if function == "abs" and len(arguments) == 1:
                return abs(_decimal_value(_scalar(arguments[0])))
            if function == "count_non_missing" and len(arguments) == 1:
                values = (
                    arguments[0]
                    if isinstance(arguments[0], list)
                    else [arguments[0]]
                )
                return Decimal(
                    sum(1 for value in values if str(value or "").strip())
                )
            if function == "round" and len(arguments) in {1, 2}:
                value = _decimal_value(_scalar(arguments[0]))
                digits = (
                    int(_decimal_value(_scalar(arguments[1])))
                    if len(arguments) == 2
                    else 0
                )
                return round(value, digits)
            if function == "date_diff_days" and len(arguments) == 2:
                left = date.fromisoformat(str(_scalar(arguments[0])).strip())
                right = date.fromisoformat(str(_scalar(arguments[1])).strip())
                return Decimal((left - right).days)
            raise MonitoringGoldCaseAuthorityError(
                f"unsupported deterministic lineage function: {function}"
            )
        raise MonitoringGoldCaseAuthorityError(
            "canonical lineage calculation contains a prohibited operation"
        )

    return evaluate(tree)


def _requires_complete_subject_scope(expression: str) -> bool:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise MonitoringGoldCaseAuthorityError(
            "canonical lineage calculation is not valid deterministic DSL"
        ) from exc
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"minimum", "maximum", "count_non_missing"}
        for node in ast.walk(tree)
    )


def _calculated_values_equal(expected: Any, actual: Any) -> bool:
    try:
        return _decimal_value(expected) == _decimal_value(actual)
    except MonitoringGoldCaseAuthorityError:
        return str(expected or "").strip() == str(actual or "").strip()


@dataclass(frozen=True)
class MonitoringGoldCaseAuthority:
    """Validates release evidence against the immutable source and batch stores."""

    source_registry_store: SourceRegistryReader
    batch_repository: MonitoringBatchRepository

    def validate(
        self,
        case: RuleGoldStandardCase | RuleDiagnosticCase,
        rule: MonitoringRuleDefinition,
    ) -> None:
        diagnostic_case = isinstance(case, RuleDiagnosticCase)
        if (
            rule.rule_revision_id != case.rule_revision_id
            or rule.project_id != case.project_id
            or rule.rule_key != case.rule_key
        ):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case is not bound to the supplied exact rule revision"
            )
        try:
            canonical_field_lineage = normalize_rule_field_lineage_units(
                rule.field_lineage
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringGoldCaseAuthorityError(
                "exact rule revision has invalid canonical field lineage"
            ) from exc
        registrations = [
            result
            for result in self.source_registry_store.list_results(case.project_id)
            if result.entry.entry_id == case.source_entry_id
        ]
        if len(registrations) != 1:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source_entry_id is not uniquely registered "
                "for the project"
            )
        entry = registrations[0].entry
        if entry.module != "medical_monitoring":
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source must belong to medical_monitoring"
            )
        if entry.source_kind != "edc_data_listing":
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source must be an EDC data listing"
            )
        if not _exact_sha256_equal(
            entry.content_hash,
            case.source_content_sha256,
        ):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source hash does not match Source Registry"
            )

        match = _BATCH_REVISION_RE.fullmatch(case.batch_revision)
        if match is None:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch_revision must use <batch_id>@v<version>"
            )
        batch_id = match.group("batch_id")
        expected_version = int(match.group("version"))
        try:
            summary = self.batch_repository.batch_summary(batch_id)
        except MonitoringBatchRepositoryError as exc:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch is not registered"
            ) from exc
        batch = summary["batch"]
        if batch["project_id"] != case.project_id:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch belongs to another project"
            )
        if batch["state"] != "frozen":
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch must be frozen"
            )
        if int(batch["version"]) != expected_version:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch revision is stale or forged"
            )
        if not batch.get("full_snapshot_proof"):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch lacks full-snapshot proof"
            )
        if not batch.get("active_mapping_revision"):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case batch lacks a frozen mapping revision"
            )

        attached = [
            source
            for source in summary["sources"]
            if source["source_entry_id"] == case.source_entry_id
            and _exact_sha256_equal(
                source["content_sha256"],
                case.source_content_sha256,
            )
        ]
        if len(attached) != 1:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source is not uniquely attached to its batch"
            )
        source = attached[0]
        validation_identity = sha256(
            source["validation_id"].encode("utf-8")
        ).hexdigest()[:16]
        expected_source_revision = (
            f"{source['source_id']}@validation:{validation_identity}"
            f"@v{int(source['validation_revision'])}"
        )
        if case.source_revision != expected_source_revision:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source revision is stale or forged"
            )
        if source["technical_status"] != "passed":
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source did not pass technical validation"
            )
        if source["validation_use_status"] not in {
            "allowed",
            "confirmed_after_warning",
        }:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source is not admitted for use"
            )
        if source["source_class"] not in BASELINE_ELIGIBLE_SOURCE_CLASSES:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source is not a full-snapshot listing"
            )
        if source["role"] != "edc_data_listing":
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source role is not edc_data_listing"
            )
        try:
            self.batch_repository.object_path(source["source_id"])
        except (MonitoringBatchRepositoryError, OSError) as exc:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard case source object failed integrity verification"
            ) from exc

        rows_by_locator: dict[str, list[Any]] = {}
        for row in self.batch_repository.list_rows(batch_id):
            locator = _canonical_row_locator(
                row.source_locator,
                fallback_hash=case.source_content_sha256,
            )
            rows_by_locator.setdefault(locator, []).append(row)

        expected_roles = _expected_record_roles(case)
        records_by_role = _records_by_role(case)
        if set(expected_roles) != set(case.evidence_locators):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard record locators must cover evidence locators exactly"
            )
        bindings_by_locator = {
            binding.source_locator: binding
            for binding in case.source_row_bindings
        }
        if set(bindings_by_locator) != set(case.evidence_locators):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard source row bindings must cover evidence locators exactly"
            )
        actual_domains: set[str] = set()
        bound_fields_by_role: dict[str, set[str]] = {
            role: set() for role in records_by_role
        }
        field_sources_by_role: dict[
            str,
            dict[str, list[tuple[str, str]]],
        ] = {role: {} for role in records_by_role}
        subject_values_by_role: dict[str, set[str]] = {
            role: set() for role in records_by_role
        }
        subject_namespaces_by_role: dict[str, set[str]] = {
            role: set() for role in records_by_role
        }
        site_values_by_role: dict[str, set[str]] = {
            role: set() for role in records_by_role
        }
        non_identity_locators_by_role_domain: dict[
            tuple[str, str],
            set[str],
        ] = {}
        for locator, binding in bindings_by_locator.items():
            matched_rows = rows_by_locator.get(locator, [])
            if len(matched_rows) != 1:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard evidence locator does not resolve to one frozen batch row"
                )
            row = matched_rows[0]
            if (
                row.business_key != binding.business_key
                or row.domain != binding.domain
                or row.row_fingerprint != binding.row_fingerprint
            ):
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard source row binding is stale or forged"
                )
            actual_domains.add(_canonical_domain(row.domain))
            locator_entry = str(
                row.source_locator.get("source_entry_id") or case.source_entry_id
            ).strip()
            locator_hash = str(
                row.source_locator.get("source_content_sha256")
                or case.source_content_sha256
            )
            if (
                locator_entry != case.source_entry_id
                or locator_hash != case.source_content_sha256
            ):
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard frozen row belongs to another source"
                )
            if set(binding.record_roles) != expected_roles[locator]:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard source row record roles are stale or forged"
                )
            for role in binding.record_roles:
                role_fields = [
                    item
                    for item in binding.field_bindings
                    if item.record_role == role
                ]
                if not role_fields:
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard record role lacks field-level source bindings"
                    )
                row_subject_identities = [
                    (field, str(row.data.get(field) or "").strip())
                    for field in ("USUBJID", "SUBJID")
                    if str(row.data.get(field) or "").strip()
                ]
                row_subjects = {
                    value for _namespace, value in row_subject_identities
                }
                if len(row_subjects) > 1:
                    raise MonitoringGoldCaseAuthorityError(
                        "frozen row contains conflicting subject identities"
                    )
                if not row_subject_identities:
                    raise MonitoringGoldCaseAuthorityError(
                        "subject-level gold case row lacks a subject identity"
                    )
                preferred_namespace = (
                    "USUBJID"
                    if any(
                        namespace == "USUBJID"
                        for namespace, _value in row_subject_identities
                    )
                    else "SUBJID"
                )
                preferred_value = next(
                    value
                    for namespace, value in row_subject_identities
                    if namespace == preferred_namespace
                )
                if not any(
                    field_binding.source_field == preferred_namespace
                    and field_binding.record_field in {"USUBJID", "SUBJID"}
                    and records_by_role[role].get(
                        field_binding.record_field
                    )
                    == preferred_value
                    for field_binding in role_fields
                ):
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard row lacks an explicit subject identity binding"
                    )
                subject_values_by_role[role].update(row_subjects)
                subject_namespaces_by_role[role].add(preferred_namespace)
                site_value = str(row.data.get("SITEID") or "").strip()
                if site_value:
                    site_values_by_role[role].add(site_value)
                if role.startswith("related:"):
                    declared_domain = role.split(":", 2)[1]
                    if _canonical_domain(row.domain) != _canonical_domain(
                        declared_domain
                    ):
                        raise MonitoringGoldCaseAuthorityError(
                            "gold standard related record role conflicts with frozen row domain"
                        )
                record = records_by_role[role]
                for field_binding in role_fields:
                    if (
                        field_binding.record_field not in record
                        or field_binding.source_field not in row.data
                        or record[field_binding.record_field]
                        != row.data[field_binding.source_field]
                    ):
                        raise MonitoringGoldCaseAuthorityError(
                            "gold standard record field conflicts with its frozen batch row"
                        )
                    bound_fields_by_role[role].add(
                        field_binding.record_field
                    )
                    field_sources_by_role[role].setdefault(
                        field_binding.record_field,
                        [],
                    ).append((_canonical_domain(row.domain), locator))
                    if field_binding.record_field not in {
                        "USUBJID",
                        "SUBJID",
                        "SITEID",
                    }:
                        non_identity_locators_by_role_domain.setdefault(
                            (role, _canonical_domain(row.domain)),
                            set(),
                        ).add(locator)

        for role, record in records_by_role.items():
            role_subjects = subject_values_by_role[role]
            if len(subject_namespaces_by_role[role]) != 1:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard record role mixes subject identity namespaces"
                )
            if len(site_values_by_role[role]) > 1:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard record role combines rows from different sites"
                )
            record_subjects = {
                str(record.get(field) or "").strip()
                for field in ("USUBJID", "SUBJID")
                if str(record.get(field) or "").strip()
            }
            if len(role_subjects) != 1 or len(record_subjects) > 1:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard record role does not resolve to one subject"
                )
            if record_subjects and record_subjects != role_subjects:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard record subject conflicts with frozen source rows"
                )
            record_site = str(record.get("SITEID") or "").strip()
            if (
                record_site
                and site_values_by_role[role]
                and site_values_by_role[role] != {record_site}
            ):
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard record site conflicts with frozen source rows"
                )
        if any(
            len(locators) > 1
            for locators in non_identity_locators_by_role_domain.values()
        ):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard record role combines event fields from multiple "
                "same-domain rows"
            )

        observed_domains = {
            _canonical_domain(domain) for domain in case.observed_domains
        }
        if actual_domains != observed_domains:
            raise MonitoringGoldCaseAuthorityError(
                "gold standard observed domains do not match frozen source rows"
            )
        required_domains = {
            _canonical_domain(domain) for domain in rule.required_domains
        }
        if (
            observed_domains != required_domains
            and (
                not diagnostic_case
                or not observed_domains.issubset(required_domains)
            )
        ):
            raise MonitoringGoldCaseAuthorityError(
                "gold standard observed domains do not match the exact rule revision"
            )

        lineage_by_output: dict[
            tuple[str, str],
            list[tuple[str, Mapping[str, Any]]],
        ] = {}
        for lineage_role, binding in canonical_field_lineage.items():
            if not isinstance(binding, Mapping):
                continue
            lineage_by_output.setdefault(
                (
                    _canonical_domain(str(binding.get("domain") or "")),
                    str(binding.get("field") or ""),
                ),
                [],
            ).append((lineage_role, binding))
        if any(len(bindings) != 1 for bindings in lineage_by_output.values()):
            raise MonitoringGoldCaseAuthorityError(
                "exact rule revision has ambiguous canonical field lineage"
            )

        for role, record in records_by_role.items():
            derived_fields = set(
                (record.get("__auditable_base_values__") or {}).keys()
            )
            for field_name, sources in field_sources_by_role[role].items():
                if field_name in derived_fields:
                    continue
                for source_domain, _locator in sources:
                    lineage_matches = lineage_by_output.get(
                        (source_domain, field_name),
                        [],
                    )
                    if not lineage_matches:
                        continue
                    if (
                        len(lineage_matches) != 1
                        or lineage_matches[0][1]["lineage"].get("source_type")
                        != "raw_listing_field"
                    ):
                        raise MonitoringGoldCaseAuthorityError(
                            "gold standard raw field occurrence conflicts with "
                            "the exact rule lineage"
                        )

        for (
            canonical_domain,
            field_name,
        ), lineage_matches in lineage_by_output.items():
            _lineage_role, canonical_binding = lineage_matches[0]
            canonical_lineage = canonical_binding.get("lineage")
            if not isinstance(canonical_lineage, Mapping):
                raise MonitoringGoldCaseAuthorityError(
                    "exact rule revision has invalid canonical field lineage"
                )
            occurrences = [
                (role, record)
                for role, record in records_by_role.items()
                if field_name in record
            ]
            if not occurrences:
                if (
                    diagnostic_case
                    and case.expected_diagnostic_category
                    in {
                        "missing_input",
                        "incomplete_evidence",
                        "unresolved_mapping",
                    }
                ):
                    continue
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard case does not cover every canonical rule field"
                )
            source_type = canonical_lineage.get("source_type")
            if source_type == "raw_listing_field":
                if not any(
                    field_name
                    not in (record.get("__auditable_base_values__") or {})
                    and any(
                        source_domain == canonical_domain
                        for source_domain, _locator in field_sources_by_role[
                            role
                        ].get(field_name, [])
                    )
                    for role, record in occurrences
                ):
                    raise MonitoringGoldCaseAuthorityError(
                        "canonical raw rule field is not bound to its declared domain"
                    )
            elif source_type == "auditable_base_value":
                if not any(
                    field_name in (record.get("__auditable_base_values__") or {})
                    for _role, record in occurrences
                ):
                    raise MonitoringGoldCaseAuthorityError(
                        "canonical derived rule field was supplied as a raw field"
                    )
            else:
                raise MonitoringGoldCaseAuthorityError(
                    "exact rule revision uses an unsupported lineage source type"
                )

        derived_lineage_by_field: dict[
            str,
            list[tuple[str, Mapping[str, Any]]],
        ] = {}
        for (_domain, field_name), bindings in lineage_by_output.items():
            if (
                bindings[0][1]["lineage"]["source_type"]
                == "auditable_base_value"
            ):
                derived_lineage_by_field.setdefault(field_name, []).extend(
                    bindings
                )

        for role, record in records_by_role.items():
            derived = record.get("__auditable_base_values__") or {}
            if not isinstance(derived, Mapping):
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard auditable base values must be a mapping"
                )
            derived_fields = set(derived)
            record_fields = {
                str(field)
                for field in record
                if not str(field).startswith("__")
            }
            if not derived_fields.issubset(record_fields):
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard derived field metadata references absent fields"
                )
            if bound_fields_by_role[role] != record_fields - derived_fields:
                raise MonitoringGoldCaseAuthorityError(
                    "gold standard record contains unbound source fields"
                )
            for field_name, metadata in derived.items():
                if not isinstance(metadata, Mapping):
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard derived field metadata is invalid"
                    )
                lineage_matches = derived_lineage_by_field.get(str(field_name), [])
                if len(lineage_matches) != 1:
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard derived field is not uniquely declared by "
                        "the exact rule revision"
                    )
                _derived_role, derived_binding = lineage_matches[0]
                canonical_lineage = derived_binding["lineage"]
                canonical_input_roles = tuple(
                    canonical_lineage["input_field_roles"]
                )
                raw_bindings: list[tuple[str, Mapping[str, Any]]] = []
                for input_role in canonical_input_roles:
                    raw_binding = canonical_field_lineage.get(input_role)
                    if (
                        not isinstance(raw_binding, Mapping)
                        or not isinstance(raw_binding.get("lineage"), Mapping)
                        or raw_binding["lineage"].get("source_type")
                        != "raw_listing_field"
                    ):
                        raise MonitoringGoldCaseAuthorityError(
                            "canonical derived lineage does not resolve to raw inputs"
                        )
                    raw_bindings.append((input_role, raw_binding))
                input_locators = metadata.get("input_locators")
                input_fields = metadata.get("input_fields")
                expression = str(
                    metadata.get("calculation_expression") or ""
                ).strip()
                expected_domains = {
                    _canonical_domain(str(binding["domain"]))
                    for _, binding in raw_bindings
                }
                record_locators = set(_record_source_locators(record))
                subject_values = {
                    str(record.get(field) or "").strip()
                    for field in ("USUBJID", "SUBJID")
                    if str(record.get(field) or "").strip()
                }
                complete_subject_scope = _requires_complete_subject_scope(
                    canonical_lineage["calculation_expression"]
                )
                if complete_subject_scope and not subject_values:
                    raise MonitoringGoldCaseAuthorityError(
                        "aggregate derived field lacks a record-level subject identity"
                    )

                def row_is_in_scope(locator: str, row: Any) -> bool:
                    if complete_subject_scope:
                        row_subjects = {
                            str(row.data.get(field) or "").strip()
                            for field in ("USUBJID", "SUBJID")
                            if str(row.data.get(field) or "").strip()
                        }
                        return bool(subject_values.intersection(row_subjects))
                    return locator in record_locators

                expected_input_locators = {
                    locator
                    for locator, matched_rows in rows_by_locator.items()
                    if len(matched_rows) == 1
                    and row_is_in_scope(locator, matched_rows[0])
                    and _canonical_domain(matched_rows[0].domain)
                    in expected_domains
                    and any(
                        _canonical_domain(matched_rows[0].domain)
                        == _canonical_domain(str(raw_binding["domain"]))
                        and str(raw_binding["field"]) in matched_rows[0].data
                        for _, raw_binding in raw_bindings
                    )
                }
                if not expected_input_locators.issubset(case.evidence_locators):
                    raise MonitoringGoldCaseAuthorityError(
                        "derived field complete input scope is not fully bound "
                        "as gold case evidence"
                    )
                expected_input_fields = {
                    str(binding["field"]) for _, binding in raw_bindings
                }
                normalized_input_fields = {
                    str(item or "").strip() for item in input_fields or []
                }
                expected_metadata_keys = {
                        "source_type",
                        "input_fields",
                        "input_locators",
                        "calculation_expression",
                        "unit",
                        "calculated_value",
                }
                lineage_issues: list[str] = []
                if set(metadata) != expected_metadata_keys:
                    lineage_issues.append("metadata_keys")
                if metadata.get("source_type") != "auditable_base_value":
                    lineage_issues.append("source_type")
                if not isinstance(input_locators, list) or not input_locators:
                    lineage_issues.append("input_locators_type")
                elif len(set(input_locators)) != len(input_locators):
                    lineage_issues.append("duplicate_input_locators")
                elif set(input_locators) != expected_input_locators:
                    missing_locators = sorted(
                        expected_input_locators - set(input_locators)
                    )
                    extra_locators = sorted(
                        set(input_locators) - expected_input_locators
                    )
                    lineage_issues.append(
                        "input_locator_scope"
                        f"(missing={len(missing_locators)},"
                        f"extra={len(extra_locators)},"
                        f"missing_sample={missing_locators[:2]},"
                        f"extra_sample={extra_locators[:2]})"
                    )
                if not isinstance(input_fields, list) or not input_fields:
                    lineage_issues.append("input_fields_type")
                elif len(
                    {
                        str(item or "").strip()
                        for item in input_fields
                    }
                ) != len(input_fields):
                    lineage_issues.append("duplicate_input_fields")
                elif normalized_input_fields != expected_input_fields:
                    lineage_issues.append("input_fields")
                if expression != canonical_lineage["calculation_expression"]:
                    lineage_issues.append("calculation_expression")
                if metadata.get("calculated_value") != record[field_name]:
                    lineage_issues.append("calculated_value")
                if lineage_issues:
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard derived field lacks auditable frozen-row "
                        f"lineage: {','.join(lineage_issues)}"
                    )
                if "unit_literal" in canonical_lineage:
                    expected_unit = str(canonical_lineage["unit_literal"])
                else:
                    unit_role = str(canonical_lineage["unit_field_role"])
                    unit_binding = canonical_field_lineage[unit_role]
                    unit_domain = _canonical_domain(str(unit_binding["domain"]))
                    unit_field = str(unit_binding["field"])
                    unit_source_values = {
                        str(row.data[unit_field]).strip()
                        for locator in input_locators
                        for row in rows_by_locator[locator]
                        if _canonical_domain(row.domain) == unit_domain
                        and unit_field in row.data
                        and str(row.data[unit_field] or "").strip()
                    }
                    if len(unit_source_values) != 1:
                        raise MonitoringGoldCaseAuthorityError(
                            "gold standard derived field unit_field_role does "
                            "not resolve to one non-missing frozen source value"
                        )
                    expected_unit = next(iter(unit_source_values))
                if str(metadata.get("unit") or "").strip() != expected_unit:
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard derived field unit conflicts with canonical lineage"
                    )
                role_values: dict[str, list[Any]] = {}
                for input_role, raw_binding in raw_bindings:
                    raw_domain = _canonical_domain(str(raw_binding["domain"]))
                    raw_field = str(raw_binding["field"])
                    values = [
                        row.data[raw_field]
                        for locator in input_locators
                        for row in rows_by_locator[locator]
                        if _canonical_domain(row.domain) == raw_domain
                        and raw_field in row.data
                    ]
                    if not values:
                        raise MonitoringGoldCaseAuthorityError(
                            "gold standard derived field input does not resolve "
                            "to frozen source values"
                        )
                    role_values[input_role] = values
                recalculated = _evaluate_deterministic_expression(
                    canonical_lineage["calculation_expression"],
                    role_values,
                )
                if not _calculated_values_equal(
                    record[field_name],
                    recalculated,
                ):
                    raise MonitoringGoldCaseAuthorityError(
                        "gold standard derived field does not match server-side "
                        "recalculation from frozen rows"
                    )
