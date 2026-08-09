from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
import json
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping


LISTING_ID_COLUMNS = (
    "__STUDYOID",
    "__STUDYEVENTOID",
    "__STUDYEVENTREPEATKEY",
    "DOMAIN",
    "USUBJID",
    "PAGE",
    "FORM",
    "LINE",
)
ODM_LISTING_ID_COLUMNS = (
    "__STUDYOID",
    "__SUBJECTKEY",
    "__STUDYEVENTOID",
    "__STUDYEVENTREPEATKEY",
    "__FORMOID",
    "__FORMREPEATKEY",
    "__ITEMGROUPOID",
    "LINE",
)
EDC_LISTING_ID_COLUMNS = (
    "STUDYID",
    "SITEID",
    "SUBJID",
    "VISTOID",
    "VISTREP",
    "FORMOID",
    "FORMREP",
    "RECREP",
)
EDC_VISIT_FALLBACK_COLUMN = "VISIT"
COMPARISON_ONLY_COLUMNS = {"状态", "CHANGE_FLAG", "_CHANGE_TYPE"}
SUMMARY_SHEETS = {"TOC", "目录", "报告总结"}
MONITORING_BATCH_DIFF_ALGORITHM_VERSION = "monitoring_batch_diff.v3"
MONITORING_ROW_IDENTITY_VERSION = "monitoring_row_identity.v2"
IDENTITY_MATCH_SAMPLE_LIMIT = 50


@dataclass(frozen=True)
class MonitoringRowDiff:
    new_keys: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)
    persisting_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    requires_rereview_keys: list[str] = field(default_factory=list)
    missing_current_domains: list[str] = field(default_factory=list)
    removal_resolution_blocked_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MonitoringFieldChange:
    domain: str
    business_key: str
    field_name: str
    previous_value: Any
    current_value: Any
    change_kind: str
    previous_locator: str = ""
    current_locator: str = ""


@dataclass(frozen=True)
class MonitoringSchemaDiff:
    domain: str
    added_fields: list[str] = field(default_factory=list)
    removed_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MonitoringIdentityMatch:
    previous_business_key: str
    current_business_key: str
    match_basis: str


@dataclass(frozen=True)
class MonitoringDetailedDiff:
    row_diff: MonitoringRowDiff
    field_changes: list[MonitoringFieldChange] = field(default_factory=list)
    schema_diffs: list[MonitoringSchemaDiff] = field(default_factory=list)
    identity_match_counts: dict[str, int] = field(default_factory=dict)
    identity_match_samples: list[MonitoringIdentityMatch] = field(default_factory=list)
    removal_eligible_keys: list[str] = field(default_factory=list)
    removal_blocked_keys: list[str] = field(default_factory=list)
    full_snapshot_proven: bool = False
    algorithm_version: str = MONITORING_BATCH_DIFF_ALGORITHM_VERSION
    output_sha256: str = ""


def normalize_listing_sheets(sheets: Iterable[Any]) -> list[dict[str, Any]]:
    sheet_list = list(sheets)
    identity_rows = [
        row
        for sheet in sheet_list
        if str(sheet.sheet_name).strip() not in SUMMARY_SHEETS
        for row in sheet.rows
        if (
            row.get("__STUDYOID")
            or row.get("USUBJID")
            or row.get("STUDYID")
            or row.get("SUBJID")
        )
    ]
    odm_identity_rows = sum(1 for row in identity_rows if row.get("__SUBJECTKEY"))
    batch_uses_odm_identity = bool(identity_rows) and (
        odm_identity_rows / len(identity_rows) >= 0.95
    )
    normalized: list[dict[str, Any]] = []
    for sheet in sheet_list:
        sheet_name = str(sheet.sheet_name).strip()
        if sheet_name in SUMMARY_SHEETS:
            continue
        row_numbers = list(getattr(sheet, "row_numbers", []) or [])
        for row_index, source_row in enumerate(sheet.rows):
            if batch_uses_odm_identity and source_row.get("__SUBJECTKEY"):
                identity_profile = "odm"
                identity_columns = ODM_LISTING_ID_COLUMNS
                identity_scope = ""
            elif source_row.get("__STUDYOID") or source_row.get("USUBJID"):
                identity_profile = "cdisc"
                identity_columns = LISTING_ID_COLUMNS
                identity_scope = sheet_name
            else:
                identity_profile = "edc"
                identity_columns = EDC_LISTING_ID_COLUMNS
                identity_scope = sheet_name
            identity_values = [str(source_row.get(column) or "").strip() for column in identity_columns]
            if (
                identity_profile == "edc"
                and not str(source_row.get("VISTOID") or "").strip()
            ):
                # Some EDC full listings omit the stable visit OID while keeping
                # one row per visit/test. The displayed visit is then the only
                # cross-export visit identity; physical row numbers are locators,
                # not business identity.
                identity_values.append(
                    str(source_row.get(EDC_VISIT_FALLBACK_COLUMN) or "").strip()
                )
            if not any(identity_values):
                continue
            domain = str(
                source_row.get("DOMAIN")
                or source_row.get("FORMOID")
                or sheet_name.split("--", 1)[0]
            ).strip().upper()
            business_key = "|".join(
                [
                    identity_profile,
                    domain,
                    identity_scope,
                    *identity_values,
                ]
            )
            data = {
                str(key): value
                for key, value in source_row.items()
                if str(key) not in COMPARISON_ONLY_COLUMNS
            }
            physical_row = row_numbers[row_index] if row_index < len(row_numbers) else None
            locator_text = (
                f"listing:sheet:{sheet_name}:row:{physical_row}"
                if physical_row is not None
                else f"listing:sheet:{sheet_name}:parsed_row:{row_index + 1}"
            )
            identity_aliases = []
            if identity_profile == "edc":
                display_identity_values = [
                    str(source_row.get(column) or "").strip()
                    for column in (
                        "STUDYID",
                        "SITEID",
                        "SUBJID",
                        "VISIT",
                        "VISTREP",
                        "FORMNM",
                        "FORMREP",
                        "RECREP",
                    )
                ]
                identity_aliases.append(
                    "|".join(
                        [
                            "edc-display-v1",
                            domain,
                            sheet_name.split("--", 1)[0].strip().upper(),
                            *display_identity_values,
                        ]
                    )
                )
            normalized.append(
                {
                    "domain": domain,
                    "business_key": business_key,
                    "data": data,
                    "source_locator": {
                        "type": "listing_row",
                        "sheet_name": sheet_name,
                        "row_number": physical_row,
                        "parsed_row_number": row_index + 1,
                        "locator": locator_text,
                        "identity_version": MONITORING_ROW_IDENTITY_VERSION,
                        "identity_base_key": business_key,
                        "identity_aliases": identity_aliases,
                        "identity_resolution": "stable_primary",
                    },
                }
            )
    return _disambiguate_multirecord_rows(normalized)


def _disambiguate_multirecord_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["business_key"])].append(row)

    for base_key, candidates in grouped.items():
        if len(candidates) == 1:
            continue
        by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in candidates:
            variant_sha256 = sha256(
                json.dumps(
                    {
                        "domain": str(row.get("domain") or "").strip().upper(),
                        "data": row.get("data") or {},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            by_variant[variant_sha256].append(row)
        for variant_sha256, variant_rows in sorted(by_variant.items()):
            variant_rows.sort(key=_locator_text)
            for copy_ordinal, row in enumerate(variant_rows, start=1):
                row["business_key"] = (
                    f"{base_key}|instance:{variant_sha256[:20]}:{copy_ordinal}"
                )
                locator = dict(row["source_locator"])
                locator.update(
                    {
                        "identity_resolution": "content_variant_multirecord",
                        "identity_variant_sha256": variant_sha256,
                        "identity_copy_ordinal": copy_ordinal,
                    }
                )
                row["source_locator"] = locator
    return rows


def listing_schema_fields(sheets: Iterable[Any]) -> list[dict[str, str]]:
    """Preserve fields from header-only domains without inventing row evidence."""

    manifest: set[tuple[str, str, str]] = set()
    for sheet in sheets:
        sheet_name = str(sheet.sheet_name).strip()
        if not sheet_name or sheet_name in SUMMARY_SHEETS:
            continue
        rows = list(getattr(sheet, "rows", ()) or ())
        headers = {
            str(field).strip()
            for field in (getattr(sheet, "headers", ()) or ())
            if str(field).strip()
            and not str(field).strip().startswith("UNNAMED_")
            and str(field).strip() not in COMPARISON_ONLY_COLUMNS
        }
        row_domains: set[str] = set()
        for row in rows:
            domain = str(
                row.get("DOMAIN")
                or row.get("FORMOID")
                or sheet_name.split("--", 1)[0]
            ).strip().upper()
            if not domain:
                continue
            row_domains.add(domain)
            for raw_field in row:
                field_name = str(raw_field).strip()
                if (
                    field_name
                    and field_name not in COMPARISON_ONLY_COLUMNS
                    and not field_name.startswith("UNNAMED_")
                ):
                    manifest.add((domain, field_name, sheet_name))
        if len(row_domains) == 1:
            domain = next(iter(row_domains))
            manifest.update((domain, field, sheet_name) for field in headers)
        elif not row_domains and headers:
            domain = sheet_name.split("--", 1)[0].strip().upper()
            if domain:
                manifest.update((domain, field, sheet_name) for field in headers)
    return [
        {"domain": domain, "field": field, "source_sheet": source_sheet}
        for domain, field, source_sheet in sorted(manifest)
    ]


def _rows_by_key(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = str(row.get("business_key") or "").strip()
        if not key:
            raise ValueError("monitoring row business_key is required")
        if key in indexed:
            raise ValueError(f"duplicate monitoring row business_key: {key}")
        indexed[key] = row
    return indexed


@dataclass(frozen=True)
class _IdentityResolution:
    previous_by_current: dict[str, str]
    basis_by_current: dict[str, str]
    unmatched_previous: set[str]
    unmatched_current: set[str]
    ambiguous_previous: set[str]


def _identity_aliases(row: Mapping[str, Any]) -> tuple[str, ...]:
    locator = row.get("source_locator")
    if not isinstance(locator, Mapping):
        return ()
    aliases = locator.get("identity_aliases")
    if not isinstance(aliases, (tuple, list)):
        return ()
    return tuple(
        sorted(
            {
                str(alias).strip()
                for alias in aliases
                if str(alias).strip()
            }
        )
    )


def _projected_payload(
    row: Mapping[str, Any],
    fields: set[str],
) -> str:
    data = row.get("data")
    values = data if isinstance(data, Mapping) else {}
    return json.dumps(
        {field_name: values.get(field_name) for field_name in sorted(fields)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _common_group_fields(
    previous_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[Mapping[str, Any]],
) -> set[str]:
    previous_fields = {
        str(field_name)
        for row in previous_rows
        for field_name in (row.get("data") or {})
        if str(field_name) not in COMPARISON_ONLY_COLUMNS
    }
    current_fields = {
        str(field_name)
        for row in current_rows
        for field_name in (row.get("data") or {})
        if str(field_name) not in COMPARISON_ONLY_COLUMNS
    }
    return previous_fields & current_fields


def _resolve_row_identities(
    previous_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[Mapping[str, Any]],
) -> _IdentityResolution:
    previous = _rows_by_key(previous_rows)
    current = _rows_by_key(current_rows)
    previous_by_current = {
        key: key for key in sorted(set(previous) & set(current))
    }
    basis_by_current = {
        key: "business_key" for key in previous_by_current
    }
    unmatched_previous = set(previous) - set(previous_by_current.values())
    unmatched_current = set(current) - set(previous_by_current)
    ambiguous_previous: set[str] = set()

    previous_aliases: dict[str, set[str]] = defaultdict(set)
    current_aliases: dict[str, set[str]] = defaultdict(set)
    for key in unmatched_previous:
        for alias in _identity_aliases(previous[key]):
            previous_aliases[alias].add(key)
    for key in unmatched_current:
        for alias in _identity_aliases(current[key]):
            current_aliases[alias].add(key)

    for alias in sorted(set(previous_aliases) & set(current_aliases)):
        previous_keys = sorted(previous_aliases[alias] & unmatched_previous)
        current_keys = sorted(current_aliases[alias] & unmatched_current)
        if not previous_keys or not current_keys:
            continue
        if len(previous_keys) == 1 and len(current_keys) == 1:
            previous_key = previous_keys[0]
            current_key = current_keys[0]
            previous_by_current[current_key] = previous_key
            basis_by_current[current_key] = "identity_alias_unique"
            unmatched_previous.remove(previous_key)
            unmatched_current.remove(current_key)
            continue

        common_fields = _common_group_fields(
            (previous[key] for key in previous_keys),
            (current[key] for key in current_keys),
        )
        if common_fields:
            previous_payloads: dict[str, list[str]] = defaultdict(list)
            current_payloads: dict[str, list[str]] = defaultdict(list)
            for key in previous_keys:
                previous_payloads[
                    _projected_payload(previous[key], common_fields)
                ].append(key)
            for key in current_keys:
                current_payloads[
                    _projected_payload(current[key], common_fields)
                ].append(key)
            for payload in sorted(set(previous_payloads) & set(current_payloads)):
                for previous_key, current_key in zip(
                    sorted(previous_payloads[payload]),
                    sorted(current_payloads[payload]),
                ):
                    if (
                        previous_key not in unmatched_previous
                        or current_key not in unmatched_current
                    ):
                        continue
                    previous_by_current[current_key] = previous_key
                    basis_by_current[current_key] = (
                        "identity_alias_common_payload"
                    )
                    unmatched_previous.remove(previous_key)
                    unmatched_current.remove(current_key)

        remaining_previous = sorted(set(previous_keys) & unmatched_previous)
        remaining_current = sorted(set(current_keys) & unmatched_current)
        if len(remaining_previous) == 1 and len(remaining_current) == 1:
            previous_key = remaining_previous[0]
            current_key = remaining_current[0]
            previous_by_current[current_key] = previous_key
            basis_by_current[current_key] = "identity_alias_single_residual"
            unmatched_previous.remove(previous_key)
            unmatched_current.remove(current_key)
        elif remaining_previous and remaining_current:
            ambiguous_previous.update(remaining_previous)

    return _IdentityResolution(
        previous_by_current=previous_by_current,
        basis_by_current=basis_by_current,
        unmatched_previous=unmatched_previous,
        unmatched_current=unmatched_current,
        ambiguous_previous=ambiguous_previous,
    )


def _paired_rows_equal(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    common_fields = _common_group_fields((previous,), (current,))
    if not common_fields:
        return False
    return _projected_payload(previous, common_fields) == _projected_payload(
        current,
        common_fields,
    )


def _field_change_kind(field_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", field_name.lower())
    if (
        "单位" in normalized
        or re.search(r"(?:orresu|stresu|unit|units)$", normalized)
    ):
        return "unit"
    if any(
        token in normalized
        for token in (
            "reflow",
            "refhigh",
            "nrlo",
            "nrhi",
            "lowerlimit",
            "upperlimit",
            "参考下限",
            "参考上限",
            "参考范围",
        )
    ):
        return "reference_range"
    return "value"


def _locator_text(row: Mapping[str, Any]) -> str:
    locator = row.get("source_locator")
    if isinstance(locator, Mapping):
        return str(locator.get("locator") or "")
    return str(locator or "")


def _schema_field_parts(schema_field: Any) -> tuple[str, str]:
    if isinstance(schema_field, Mapping):
        domain = schema_field.get("domain")
        field_name = schema_field.get("field", schema_field.get("field_name"))
    elif isinstance(schema_field, (tuple, list)) and len(schema_field) >= 2:
        domain, field_name = schema_field[0], schema_field[1]
    else:
        domain = getattr(schema_field, "domain", "")
        field_name = getattr(
            schema_field,
            "field",
            getattr(schema_field, "field_name", ""),
        )
    return str(domain or "").strip().upper(), str(field_name or "").strip()


def _schema_manifest_by_domain(
    schema_fields: Iterable[Any] | None,
) -> dict[str, set[str]]:
    schema: dict[str, set[str]] = {}
    for schema_field in schema_fields or ():
        domain, field_name = _schema_field_parts(schema_field)
        if (
            not domain
            or not field_name
            or field_name in COMPARISON_ONLY_COLUMNS
            or field_name.startswith("UNNAMED_")
        ):
            continue
        schema.setdefault(domain, set()).add(field_name)
    return schema


def _schema_by_domain(
    rows: Iterable[Mapping[str, Any]],
    schema_fields: Iterable[Any] | None = None,
) -> dict[str, set[str]]:
    schema = _schema_manifest_by_domain(schema_fields)
    for row in rows:
        domain = str(row.get("domain") or "").strip().upper()
        if not domain:
            continue
        schema.setdefault(domain, set()).update(
            str(key)
            for key in (row.get("data") or {}).keys()
            if str(key) not in COMPARISON_ONLY_COLUMNS
            and not str(key).startswith("UNNAMED_")
        )
    return schema


def monitoring_diff_output_sha256(result: MonitoringDetailedDiff) -> str:
    """Return a deterministic digest of the complete diff result."""

    payload = asdict(result)
    payload.pop("output_sha256", None)
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def diff_monitoring_rows(
    previous_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[Mapping[str, Any]],
    *,
    previous_mapping_revision: str = "",
    current_mapping_revision: str = "",
    expected_domains: set[str] | None = None,
    current_schema_fields: Iterable[Any] | None = None,
) -> MonitoringRowDiff:
    previous_row_list = list(previous_rows)
    current_row_list = list(current_rows)
    previous = _rows_by_key(previous_row_list)
    current = _rows_by_key(current_row_list)
    resolution = _resolve_row_identities(previous_row_list, current_row_list)
    matched_current_keys = set(resolution.previous_by_current)
    removed_keys = set(resolution.unmatched_previous)
    current_domains = {
        str(row.get("domain") or "").strip().upper()
        for row in current_row_list
        if str(row.get("domain") or "").strip()
    }
    current_domains.update(_schema_manifest_by_domain(current_schema_fields))
    missing_current_domains = sorted((expected_domains or set()) - current_domains)
    previous_domain_by_key = {
        str(row.get("business_key") or "").strip(): str(row.get("domain") or "").strip()
        for row in previous_row_list
    }
    # A mapping revision appearing or disappearing is itself a semantic change.
    # Treating that asymmetric case as "unchanged" would let a batch with an
    # unconfirmed mapping inherit the prior batch's risk interpretation.
    mapping_changed = bool(
        (previous_mapping_revision or current_mapping_revision)
        and previous_mapping_revision != current_mapping_revision
    )
    changed_keys = []
    persisting_keys = []
    for current_key in sorted(matched_current_keys):
        previous_key = resolution.previous_by_current[current_key]
        if _paired_rows_equal(previous[previous_key], current[current_key]):
            persisting_keys.append(current_key)
        else:
            changed_keys.append(current_key)
    return MonitoringRowDiff(
        new_keys=sorted(resolution.unmatched_current),
        changed_keys=changed_keys,
        persisting_keys=persisting_keys,
        removed_keys=sorted(removed_keys),
        requires_rereview_keys=sorted(matched_current_keys) if mapping_changed else [],
        missing_current_domains=missing_current_domains,
        removal_resolution_blocked_keys=sorted(
            key
            for key in removed_keys
            if (
                previous_domain_by_key.get(key) in missing_current_domains
                or key in resolution.ambiguous_previous
            )
        ),
    )


def diff_monitoring_batches(
    previous_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[Mapping[str, Any]],
    *,
    previous_mapping_revision: str = "",
    current_mapping_revision: str = "",
    expected_domains: set[str] | None = None,
    full_snapshot_proven: bool = False,
    previous_schema_fields: Iterable[Any] | None = None,
    current_schema_fields: Iterable[Any] | None = None,
) -> MonitoringDetailedDiff:
    previous_row_list = list(previous_rows)
    current_row_list = list(current_rows)
    resolution = _resolve_row_identities(previous_row_list, current_row_list)
    row_diff = diff_monitoring_rows(
        previous_row_list,
        current_row_list,
        previous_mapping_revision=previous_mapping_revision,
        current_mapping_revision=current_mapping_revision,
        expected_domains=expected_domains,
        current_schema_fields=current_schema_fields,
    )
    previous_by_key = _rows_by_key(previous_row_list)
    current_by_key = _rows_by_key(current_row_list)
    field_changes: list[MonitoringFieldChange] = []
    for business_key in row_diff.changed_keys:
        previous_key = resolution.previous_by_current[business_key]
        previous = previous_by_key[previous_key]
        current = current_by_key[business_key]
        previous_data = previous.get("data") or {}
        current_data = current.get("data") or {}
        for field_name in sorted(set(previous_data) & set(current_data)):
            previous_value = previous_data.get(field_name)
            current_value = current_data.get(field_name)
            if previous_value == current_value:
                continue
            field_changes.append(
                MonitoringFieldChange(
                    domain=str(current.get("domain") or previous.get("domain") or ""),
                    business_key=business_key,
                    field_name=str(field_name),
                    previous_value=previous_value,
                    current_value=current_value,
                    change_kind=_field_change_kind(str(field_name)),
                    previous_locator=_locator_text(previous),
                    current_locator=_locator_text(current),
                )
            )

    previous_schema = _schema_by_domain(previous_row_list, previous_schema_fields)
    current_schema = _schema_by_domain(current_row_list, current_schema_fields)
    schema_diffs = []
    for domain in sorted(set(previous_schema) | set(current_schema)):
        added_fields = sorted(current_schema.get(domain, set()) - previous_schema.get(domain, set()))
        removed_fields = sorted(previous_schema.get(domain, set()) - current_schema.get(domain, set()))
        if added_fields or removed_fields:
            schema_diffs.append(
                MonitoringSchemaDiff(
                    domain=domain,
                    added_fields=added_fields,
                    removed_fields=removed_fields,
                )
            )

    removal_blocked = set(row_diff.removal_resolution_blocked_keys)
    if not full_snapshot_proven:
        removal_blocked.update(row_diff.removed_keys)
    removal_eligible = set(row_diff.removed_keys) - removal_blocked
    identity_match_counts: dict[str, int] = defaultdict(int)
    identity_match_samples: list[MonitoringIdentityMatch] = []
    for current_key, previous_key in sorted(
        resolution.previous_by_current.items()
    ):
        if previous_key == current_key:
            continue
        match_basis = resolution.basis_by_current[current_key]
        identity_match_counts[match_basis] += 1
        if len(identity_match_samples) < IDENTITY_MATCH_SAMPLE_LIMIT:
            identity_match_samples.append(
                MonitoringIdentityMatch(
                    previous_business_key=previous_key,
                    current_business_key=current_key,
                    match_basis=match_basis,
                )
            )

    result = MonitoringDetailedDiff(
        row_diff=row_diff,
        field_changes=field_changes,
        schema_diffs=schema_diffs,
        identity_match_counts=dict(sorted(identity_match_counts.items())),
        identity_match_samples=identity_match_samples,
        removal_eligible_keys=sorted(removal_eligible),
        removal_blocked_keys=sorted(removal_blocked),
        full_snapshot_proven=full_snapshot_proven,
    )
    return replace(result, output_sha256=monitoring_diff_output_sha256(result))
