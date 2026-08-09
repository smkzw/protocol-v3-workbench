from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from packages.contracts.workbench_contracts import (
    SourceRegistrationResult,
    SourceRegistryEntry,
)
from services.api.app.monitoring_batch_repository import MonitoringBatchRepository
from services.api.app.monitoring_gold_case_authority import (
    MonitoringGoldCaseAuthority,
    MonitoringGoldCaseAuthorityError,
    _canonical_row_locator,
    monitoring_batch_revision,
    monitoring_source_revision,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    RulePackLifecycleError,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    RuleGoldRecordFieldBinding,
    RuleGoldSourceRowBinding,
    RuleGoldStandardCase,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from tests.test_monitoring_protocol_rules import (
    _fact,
    _gold_case_source,
    _rule,
    _store_p7c_release_evidence,
    _version,
)


@dataclass(frozen=True)
class _RegistryReader:
    results: tuple[SourceRegistrationResult, ...]

    def list_results(self, project_id: str) -> list[SourceRegistrationResult]:
        return [
            result
            for result in self.results
            if result.entry.project_id == project_id
        ]


def _registration(
    *,
    project_id: str,
    entry_id: str,
    content_hash: str,
    source_kind: str = "edc_data_listing",
    title: str = "listing.xlsx",
) -> SourceRegistrationResult:
    return SourceRegistrationResult(
        entry=SourceRegistryEntry(
            entry_id=entry_id,
            project_id=project_id,
            module="medical_monitoring",
            source_kind=source_kind,
            public_title=title,
            content_hash=content_hash,
            size_bytes=1,
            parser_status="parsed",
            parser_version="listing-parser-v1",
            created_at=datetime.now(timezone.utc),
        ),
        spans=[],
    )


def _frozen_authority_fixture(
    root: Path,
    *,
    project_id: str = "proj_authority",
    role: str = "edc_data_listing",
    source_class: str = "raw_full_snapshot",
    freeze: bool = True,
    base_unit: str = "count",
    legacy_primary_locator: bool = False,
    primary_source_entry_id: str | None = None,
    extra_rows: tuple[dict[str, object], ...] = (),
) -> tuple[
    MonitoringGoldCaseAuthority,
    MonitoringBatchRepository,
    RuleGoldStandardCase,
    SourceRegistrationResult,
]:
    file_path = root / "listing.xlsx"
    file_path.write_bytes(b"PK\x03\x04authoritative-listing")
    content_hash = sha256(file_path.read_bytes()).hexdigest()
    entry_id = f"listing-{content_hash[:16]}"
    registration = _registration(
        project_id=project_id,
        entry_id=entry_id,
        content_hash=content_hash,
    )
    registry = _RegistryReader((registration,))
    batches = MonitoringBatchRepository(
        root / "batches.sqlite3",
        root / "batch_objects",
    )
    source = batches.register_source(
        project_id=project_id,
        source_entry_id=entry_id,
        validation_id="validation-authority-1",
        validation_revision=1,
        validator_version="source-content-v2",
        validation_use_status="allowed",
        role=role,
        source_class=source_class,
        file_path=file_path,
        parser_version="listing-parser-v1",
    )
    created = batches.create_batch(
        project_id=project_id,
        idempotency_key="authority:create",
        expected_domains=("AE",),
    )
    attached = batches.attach_source(
        batch_id=created.batch.batch_id,
        source_id=source.source_id,
        expected_version=created.batch.version,
        idempotency_key="authority:attach",
    )
    primary_source_locator = (
        {
            "source_entry_id": primary_source_entry_id or entry_id,
            "locator": "listing:sheet:AE:row:2",
            "sheet_name": "AE",
            "row_number": 2,
        }
        if legacy_primary_locator
        else {
            "source_entry_id": entry_id,
            "source_content_sha256": content_hash,
            "sheet": "AE",
            "row": 2,
        }
    )
    materialized = batches.replace_rows(
        batch_id=created.batch.batch_id,
        rows=(
            {
                "business_key": "AE:001",
                "domain": "AE",
                "data": {
                    "USUBJID": "001",
                    "AETERM": "头痛",
                    "UNIT": base_unit,
                },
                "source_locator": primary_source_locator,
            },
            *extra_rows,
        ),
        expected_version=attached.batch.version,
        idempotency_key="authority:rows",
    )
    batch = materialized.batch
    if freeze:
        parsed = batches.transition_batch(
            batch_id=batch.batch_id,
            target_state="parsed",
            expected_version=batch.version,
            idempotency_key="authority:parsed",
        )
        evidenced = batches.record_validation_evidence(
            batch_id=batch.batch_id,
            mapping_revision="mapping-v1",
            mapping={"AE": {"USUBJID": "USUBJID", "AETERM": "AETERM"}},
            expected_domains=("AE",),
            full_snapshot_proof={
                "confirmed": True,
                "basis": "完整 listing",
                "confirmed_by": "medical_manager",
            },
            expected_version=parsed.batch.version,
            idempotency_key="authority:evidence",
        )
        validated = batches.transition_batch(
            batch_id=batch.batch_id,
            target_state="validated",
            expected_version=evidenced.batch.version,
            idempotency_key="authority:validated",
        )
        confirmed = batches.transition_batch(
            batch_id=batch.batch_id,
            target_state="confirmed",
            expected_version=validated.batch.version,
            idempotency_key="authority:confirmed",
        )
        batch = batches.transition_batch(
            batch_id=batch.batch_id,
            target_state="frozen",
            expected_version=confirmed.batch.version,
            idempotency_key="authority:frozen",
        ).batch
    normalized_row = batches.list_rows(batch.batch_id)[0]
    source_locator = f"listing:{content_hash}:sheet:AE:row:2"
    case = RuleGoldStandardCase.create(
        project_id=project_id,
        rule_key="ae_mh.pre_treatment_event_without_same_day_history",
        rule_revision_id="monrule_authority_test",
        source_entry_id=entry_id,
        source_content_sha256=content_hash,
        source_revision=monitoring_source_revision(source),
        batch_revision=monitoring_batch_revision(batch.batch_id, batch.version),
        case_label="authoritative listing case",
        input_record={
            "USUBJID": "001",
            "AETERM": "头痛",
            "__source_locator__": source_locator,
        },
        observed_domains=("AE",),
        expected_match=True,
        medical_rationale="仅验证权威来源绑定。",
        evidence_locators=(source_locator,),
        source_row_bindings=(
            RuleGoldSourceRowBinding.create(
                business_key=normalized_row.business_key,
                domain=normalized_row.domain,
                source_locator=source_locator,
                row_fingerprint=normalized_row.row_fingerprint,
                record_roles=("current",),
                field_bindings=(
                    RuleGoldRecordFieldBinding.create(
                        record_role="current",
                        record_field="USUBJID",
                        source_field="USUBJID",
                    ),
                    RuleGoldRecordFieldBinding.create(
                        record_role="current",
                        record_field="AETERM",
                        source_field="AETERM",
                    ),
                ),
            ),
        ),
    )
    return MonitoringGoldCaseAuthority(registry, batches), batches, case, registration


def test_authority_binds_legacy_row_locator_to_registered_source_hash() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(
            Path(directory),
            legacy_primary_locator=True,
        )

        authority.validate(case, _authority_rule(case))


def test_authority_rejects_explicit_locator_with_wrong_source_hash() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        content_hash = sha256(b"PK\x03\x04authoritative-listing").hexdigest()
        wrong_hash = sha256(b"another-listing").hexdigest()
        authority, _, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {
                        "USUBJID": "001",
                        "AETERM": "恶心",
                    },
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "locator": (
                            f"listing:{wrong_hash}:sheet:AE:row:3"
                        ),
                        "sheet_name": "AE",
                        "row_number": 3,
                    },
                },
            ),
        )

        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="explicit source locator hash",
        ):
            authority.validate(case, _authority_rule(case))


def test_authority_rejects_noncanonical_source_hash_bytes() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        authority, batches, case, registration = _frozen_authority_fixture(root)
        tampered_registration = registration.model_copy(
            update={
                "entry": registration.entry.model_copy(
                    update={"content_hash": case.source_content_sha256.upper()}
                )
            }
        )
        tampered_authority = MonitoringGoldCaseAuthority(
            _RegistryReader((tampered_registration,)),
            batches,
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="source hash does not match Source Registry",
        ):
            tampered_authority.validate(case, _authority_rule(case))

        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="source locator hash does not match",
        ):
            _canonical_row_locator(
                {
                    "source_content_sha256": case.source_content_sha256.upper(),
                    "sheet": "AE",
                    "row": 2,
                },
                fallback_hash=case.source_content_sha256,
            )

        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="explicit source locator hash",
        ):
            _canonical_row_locator(
                {
                    "locator": (
                        f"listing:{case.source_content_sha256.upper()}:"
                        "sheet:AE:row:2"
                    )
                },
                fallback_hash=case.source_content_sha256,
            )


def test_authority_rejects_legacy_locator_bound_to_another_source_entry() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(
            Path(directory),
            legacy_primary_locator=True,
            primary_source_entry_id="listing-from-another-source",
        )

        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="belongs to another source",
        ):
            authority.validate(case, _authority_rule(case))


def test_authority_rejects_ambiguous_legacy_rows_at_same_locator() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        content_hash = sha256(b"PK\x03\x04authoritative-listing").hexdigest()
        authority, _, case, _ = _frozen_authority_fixture(
            root,
            legacy_primary_locator=True,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {
                        "USUBJID": "001",
                        "AETERM": "恶心",
                    },
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "locator": "listing:sheet:AE:row:2",
                        "sheet_name": "AE",
                        "row_number": 2,
                    },
                },
            ),
        )

        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="does not resolve to one frozen batch row",
        ):
            authority.validate(case, _authority_rule(case))


@pytest.mark.parametrize(
    "source_locator",
    (
        {"sheet_name": "AE"},
        {"row_number": 3},
        {"sheet_name": "AE", "row_number": 0},
    ),
)
def test_authority_rejects_legacy_locator_with_missing_or_invalid_fields(
    source_locator: dict[str, object],
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        content_hash = sha256(b"PK\x03\x04authoritative-listing").hexdigest()
        authority, _, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {
                        "USUBJID": "001",
                        "AETERM": "恶心",
                    },
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        **source_locator,
                    },
                },
            ),
        )

        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="lacks a canonical source locator",
        ):
            authority.validate(case, _authority_rule(case))


def _rebuild_case(
    case: RuleGoldStandardCase,
    *,
    input_record: dict[str, object] | None = None,
    related_records: dict[str, list[dict[str, object]]] | None = None,
    evidence_locators: tuple[str, ...] | None = None,
    source_row_bindings: tuple[RuleGoldSourceRowBinding, ...] | None = None,
    observed_domains: tuple[str, ...] | None = None,
) -> RuleGoldStandardCase:
    return RuleGoldStandardCase.create(
        project_id=case.project_id,
        rule_key=case.rule_key,
        rule_revision_id=case.rule_revision_id,
        source_entry_id=case.source_entry_id,
        source_content_sha256=case.source_content_sha256,
        source_revision=case.source_revision,
        batch_revision=case.batch_revision,
        case_label=case.case_label,
        input_record=input_record or case.input_record,
        previous_record=case.previous_record,
        related_records=related_records or case.related_records,
        observed_domains=observed_domains or case.observed_domains,
        expected_match=case.expected_match,
        medical_rationale=case.medical_rationale,
        evidence_locators=evidence_locators or case.evidence_locators,
        source_row_bindings=source_row_bindings or case.source_row_bindings,
    )


def _authority_rule(case: RuleGoldStandardCase):
    version = _version(case.project_id, "V1.0", "2026-01-01")
    base = _rule(
        version,
        _fact(version),
        rule_key=case.rule_key,
    )
    return replace(
        base,
        rule_revision_id=case.rule_revision_id,
        project_id=case.project_id,
        rule_key=case.rule_key,
        required_domains=("AE",),
        field_lineage={
            "subject_id": {
                "field": "USUBJID",
                "domain": "AE",
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        "listing:authority:sheet:AE:header:1:field:USUBJID"
                    ),
                },
            },
            "event_term": {
                "field": "AETERM",
                "domain": "AE",
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        "listing:authority:sheet:AE:header:1:field:AETERM"
                    ),
                },
            },
        },
    )


def _derived_unit_rule(
    case: RuleGoldStandardCase,
    unit_contract: dict[str, str],
):
    return replace(
        _authority_rule(case),
        field_lineage={
            "raw_subject_id": {
                "field": "USUBJID",
                "domain": "AE",
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        "listing:authority:sheet:AE:header:1:field:USUBJID"
                    ),
                },
            },
            "raw_unit": {
                "field": "UNIT",
                "domain": "AE",
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        "listing:authority:sheet:AE:header:1:field:UNIT"
                    ),
                },
            },
            "derived_subject_id": {
                "field": "DERIVED_SUBJECT",
                "domain": "AE",
                "lineage": {
                    "source_type": "auditable_base_value",
                    "input_field_roles": ["raw_subject_id", "raw_unit"],
                    "calculation_expression": "minimum(raw_subject_id)",
                    **unit_contract,
                    "source_locator": (
                        "listing:authority:derived:field:DERIVED_SUBJECT:"
                        "header-source"
                    ),
                },
            },
        },
    )


def _derived_unit_case(
    case: RuleGoldStandardCase,
    *,
    unit: str,
    raw_unit: str = "count",
    input_locators: tuple[str, ...] | None = None,
    source_row_bindings: tuple[RuleGoldSourceRowBinding, ...] | None = None,
) -> RuleGoldStandardCase:
    locators = input_locators or case.evidence_locators
    source_locator: object = (
        locators[0] if len(locators) == 1 else list(locators)
    )
    bindings = source_row_bindings or case.source_row_bindings
    first = bindings[0]
    bindings = (
        RuleGoldSourceRowBinding.create(
            business_key=first.business_key,
            domain=first.domain,
            source_locator=first.source_locator,
            row_fingerprint=first.row_fingerprint,
            record_roles=first.record_roles,
            field_bindings=(
                *first.field_bindings,
                RuleGoldRecordFieldBinding.create(
                    record_role="current",
                    record_field="UNIT",
                    source_field="UNIT",
                ),
            ),
        ),
        *bindings[1:],
    )
    return _rebuild_case(
        case,
        input_record={
            **case.input_record,
            "UNIT": raw_unit,
            "DERIVED_SUBJECT": "001",
            "__source_locator__": source_locator,
            "__auditable_base_values__": {
                "DERIVED_SUBJECT": {
                    "source_type": "auditable_base_value",
                    "input_fields": ["USUBJID", "UNIT"],
                    "input_locators": list(locators),
                    "calculation_expression": "minimum(raw_subject_id)",
                    "unit": unit,
                    "calculated_value": "001",
                },
            },
        },
        evidence_locators=locators,
        source_row_bindings=bindings,
    )


def test_authority_accepts_registered_frozen_full_listing() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        authority.validate(case, _authority_rule(case))


def test_authority_rejects_literal_unit_metadata_mismatch() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        derived = _derived_unit_case(case, unit="events")
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="unit conflicts with canonical lineage",
        ):
            authority.validate(
                derived,
                _derived_unit_rule(case, {"unit_literal": "count"}),
            )


def test_authority_resolves_unit_field_role_from_frozen_domain_and_field() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        derived = _derived_unit_case(case, unit="count")
        authority.validate(
            derived,
            _derived_unit_rule(case, {"unit_field_role": "raw_unit"}),
        )


def test_authority_rejects_missing_unit_field_value() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(
            Path(directory),
            base_unit="",
        )
        derived = _derived_unit_case(case, unit="count", raw_unit="")
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="does not resolve to one non-missing frozen source value",
        ):
            authority.validate(
                derived,
                _derived_unit_rule(case, {"unit_field_role": "raw_unit"}),
            )


def test_authority_rejects_conflicting_frozen_unit_values() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provisional = root / "listing.xlsx"
        provisional.write_bytes(b"PK\x03\x04authoritative-listing")
        content_hash = sha256(provisional.read_bytes()).hexdigest()
        authority, batches, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {
                        "USUBJID": "001",
                        "AETERM": "恶心",
                        "UNIT": "events",
                    },
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "source_content_sha256": content_hash,
                        "sheet": "AE",
                        "row": 3,
                    },
                },
            ),
        )
        batch_id = case.batch_revision.rsplit("@v", 1)[0]
        rows = {row.business_key: row for row in batches.list_rows(batch_id)}
        second_locator = f"listing:{content_hash}:sheet:AE:row:3"
        locators = (case.evidence_locators[0], second_locator)
        second_binding = RuleGoldSourceRowBinding.create(
            business_key="AE:002",
            domain="AE",
            source_locator=second_locator,
            row_fingerprint=rows["AE:002"].row_fingerprint,
            record_roles=("current",),
            field_bindings=(
                RuleGoldRecordFieldBinding.create(
                    record_role="current",
                    record_field="USUBJID",
                    source_field="USUBJID",
                ),
            ),
        )
        derived = _derived_unit_case(
            case,
            unit="count",
            input_locators=locators,
            source_row_bindings=(
                case.source_row_bindings[0],
                second_binding,
            ),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="does not resolve to one non-missing frozen source value",
        ):
            authority.validate(
                derived,
                _derived_unit_rule(case, {"unit_field_role": "raw_unit"}),
            )


def test_authority_rejects_locator_that_is_not_a_frozen_batch_row() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        forged_locator = (
            f"listing:{case.source_content_sha256}:sheet:AE:row:999999"
        )
        forged_binding = RuleGoldSourceRowBinding.create(
            business_key="AE:forged",
            domain="AE",
            source_locator=forged_locator,
            row_fingerprint=sha256(b"forged-row").hexdigest(),
            record_roles=("current",),
            field_bindings=(
                RuleGoldRecordFieldBinding.create(
                    record_role="current",
                    record_field="USUBJID",
                    source_field="USUBJID",
                ),
                RuleGoldRecordFieldBinding.create(
                    record_role="current",
                    record_field="AETERM",
                    source_field="AETERM",
                ),
            ),
        )
        forged = _rebuild_case(
            case,
            input_record={
                "USUBJID": "001",
                "AETERM": "头痛",
                "__source_locator__": forged_locator,
            },
            evidence_locators=(forged_locator,),
            source_row_bindings=(forged_binding,),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="does not resolve to one frozen batch row",
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_record_value_not_present_in_bound_row() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        forged = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "USUBJID": "NOT-IN-BATCH",
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match=(
                "explicit subject identity binding|"
                "record field conflicts with its frozen batch row"
            ),
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_unbound_rule_driving_field_and_domain_injection() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        forged = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "SUBJID": "FORGED-SUBJECT",
                "EXDESC": "漏服",
                "date": "2026-01-14",
                "visit": "D1",
            },
            observed_domains=("EX",),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
                match=(
                    "observed domains do not match|contains unbound source fields|"
                    "record role does not resolve to one subject"
                ),
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_case_declared_formula_for_rule_driving_injection() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        fake_metadata = {
            "source_type": "auditable_base_value",
            "input_fields": ["USUBJID"],
            "input_locators": list(case.evidence_locators),
            "calculation_expression": "minimum(subject_id)",
            "unit": "text",
            "calculated_value": "FORGED-SUBJECT",
        }
        forged = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "SUBJID": "FORGED-SUBJECT",
                "__auditable_base_values__": {
                    "SUBJID": fake_metadata,
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match=(
                "not uniquely declared by the exact rule revision|"
                "record role does not resolve to one subject"
            ),
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_recomputes_canonical_derived_value_from_frozen_row() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        rule = replace(
            _authority_rule(case),
            field_lineage={
                "raw_subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:authority:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
                "derived_subject_id": {
                    "field": "DERIVED_SUBJECT",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "auditable_base_value",
                        "input_field_roles": ["raw_subject_id"],
                        "calculation_expression": "minimum(raw_subject_id)",
                        "unit": "text",
                        "source_locator": (
                            "listing:authority:derived:field:DERIVED_SUBJECT:"
                            "header-source"
                        ),
                    },
                },
            },
        )
        metadata = {
            "source_type": "auditable_base_value",
            "input_fields": ["USUBJID"],
            "input_locators": list(case.evidence_locators),
            "calculation_expression": "minimum(raw_subject_id)",
            "unit": "text",
            "calculated_value": "001",
        }
        valid = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "DERIVED_SUBJECT": "001",
                "__auditable_base_values__": {
                    "DERIVED_SUBJECT": metadata,
                },
            },
        )
        authority.validate(valid, rule)

        formula_forged = _rebuild_case(
            valid,
            input_record={
                **valid.input_record,
                "__auditable_base_values__": {
                    "DERIVED_SUBJECT": {
                        **metadata,
                        "calculation_expression": "minimum(raw_subject_id) + 1",
                    },
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="calculation_expression",
        ):
            authority.validate(formula_forged, rule)

        value_forged = _rebuild_case(
            valid,
            input_record={
                **valid.input_record,
                "DERIVED_SUBJECT": "FORGED",
                "__auditable_base_values__": {
                    "DERIVED_SUBJECT": {
                        **metadata,
                        "calculated_value": "FORGED",
                    },
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="server-side recalculation",
        ):
            authority.validate(value_forged, rule)

        prefixed_input_field = _rebuild_case(
            valid,
            input_record={
                **valid.input_record,
                "__auditable_base_values__": {
                    "DERIVED_SUBJECT": {
                        **metadata,
                        "input_fields": ["LB.USUBJID"],
                    },
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="input_fields",
        ):
            authority.validate(prefixed_input_field, rule)


def test_authority_rejects_duplicate_record_source_locator() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        locator = case.evidence_locators[0]
        forged = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "__source_locator__": [locator, locator],
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="duplicate source locators",
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_exact_rule_domain_mismatch() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        mismatched_rule = replace(
            _authority_rule(case),
            required_domains=("EX",),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="exact rule revision",
        ):
            authority.validate(case, mismatched_rule)


def test_authority_rejects_raw_value_for_canonical_derived_field() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        rule = replace(
            _authority_rule(case),
            field_lineage={
                "raw_subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:authority:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
                "derived_event_term": {
                    "field": "AETERM",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "auditable_base_value",
                        "input_field_roles": ["raw_subject_id"],
                        "calculation_expression": "minimum(raw_subject_id)",
                        "unit": "text",
                        "source_locator": (
                            "listing:authority:derived:field:AETERM:header-source"
                        ),
                    },
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match=(
                "raw field occurrence conflicts with the exact rule lineage|"
                "derived rule field was supplied as a raw field"
            ),
        ):
            authority.validate(case, rule)


def test_authority_rejects_cross_subject_record_role_splice() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provisional_path = root / "listing.xlsx"
        provisional_path.write_bytes(b"PK\x03\x04authoritative-listing")
        content_hash = sha256(provisional_path.read_bytes()).hexdigest()
        authority, batches, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {"USUBJID": "002", "AETERM": "恶心"},
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "source_content_sha256": content_hash,
                        "sheet": "AE",
                        "row": 3,
                    },
                },
            ),
        )
        batch_id = case.batch_revision.rsplit("@v", 1)[0]
        rows = {
            row.business_key: row for row in batches.list_rows(batch_id)
        }
        first_locator = case.evidence_locators[0]
        second_locator = f"listing:{content_hash}:sheet:AE:row:3"
        forged = _rebuild_case(
            case,
            input_record={
                "USUBJID": "001",
                "AETERM": "恶心",
                "__source_locator__": [first_locator, second_locator],
            },
            evidence_locators=(first_locator, second_locator),
            source_row_bindings=(
                RuleGoldSourceRowBinding.create(
                    business_key="AE:001",
                    domain="AE",
                    source_locator=first_locator,
                    row_fingerprint=rows["AE:001"].row_fingerprint,
                    record_roles=("current",),
                    field_bindings=(
                        RuleGoldRecordFieldBinding.create(
                            record_role="current",
                            record_field="USUBJID",
                            source_field="USUBJID",
                        ),
                    ),
                ),
                RuleGoldSourceRowBinding.create(
                    business_key="AE:002",
                    domain="AE",
                    source_locator=second_locator,
                    row_fingerprint=rows["AE:002"].row_fingerprint,
                    record_roles=("current",),
                    field_bindings=(
                        RuleGoldRecordFieldBinding.create(
                            record_role="current",
                            record_field="AETERM",
                            source_field="AETERM",
                        ),
                    ),
                ),
            ),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match=(
                "explicit subject identity binding|"
                "record role does not resolve to one subject"
            ),
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_mixed_subject_identity_namespaces() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provisional_path = root / "listing.xlsx"
        provisional_path.write_bytes(b"PK\x03\x04authoritative-listing")
        content_hash = sha256(provisional_path.read_bytes()).hexdigest()
        authority, batches, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:USUBJID",
                    "domain": "AE",
                    "data": {"USUBJID": "001", "SITEID": "A"},
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "source_content_sha256": content_hash,
                        "sheet": "AE",
                        "row": 3,
                    },
                },
                {
                    "business_key": "AE:SUBJID",
                    "domain": "AE",
                    "data": {
                        "SUBJID": "001",
                        "SITEID": "B",
                        "AETERM": "恶心",
                    },
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "source_content_sha256": content_hash,
                        "sheet": "AE",
                        "row": 4,
                    },
                },
            ),
        )
        batch_id = case.batch_revision.rsplit("@v", 1)[0]
        rows = {
            row.business_key: row for row in batches.list_rows(batch_id)
        }
        locator_a = f"listing:{content_hash}:sheet:AE:row:3"
        locator_b = f"listing:{content_hash}:sheet:AE:row:4"
        forged = _rebuild_case(
            case,
            input_record={
                "USUBJID": "001",
                "AETERM": "恶心",
                "__source_locator__": [locator_a, locator_b],
            },
            evidence_locators=(locator_a, locator_b),
            source_row_bindings=(
                RuleGoldSourceRowBinding.create(
                    business_key="AE:USUBJID",
                    domain="AE",
                    source_locator=locator_a,
                    row_fingerprint=rows["AE:USUBJID"].row_fingerprint,
                    record_roles=("current",),
                    field_bindings=(
                        RuleGoldRecordFieldBinding.create(
                            record_role="current",
                            record_field="USUBJID",
                            source_field="USUBJID",
                        ),
                    ),
                ),
                RuleGoldSourceRowBinding.create(
                    business_key="AE:SUBJID",
                    domain="AE",
                    source_locator=locator_b,
                    row_fingerprint=rows["AE:SUBJID"].row_fingerprint,
                    record_roles=("current",),
                    field_bindings=(
                        RuleGoldRecordFieldBinding.create(
                            record_role="current",
                            record_field="USUBJID",
                            source_field="SUBJID",
                        ),
                        RuleGoldRecordFieldBinding.create(
                            record_role="current",
                            record_field="AETERM",
                            source_field="AETERM",
                        ),
                    ),
                ),
            ),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="mixes subject identity namespaces",
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_raw_derived_collision_across_record_roles() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provisional_path = root / "listing.xlsx"
        provisional_path.write_bytes(b"PK\x03\x04authoritative-listing")
        content_hash = sha256(provisional_path.read_bytes()).hexdigest()
        authority, batches, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {"USUBJID": "001", "AETERM": "恶心"},
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "source_content_sha256": content_hash,
                        "sheet": "AE",
                        "row": 3,
                    },
                },
            ),
        )
        batch_id = case.batch_revision.rsplit("@v", 1)[0]
        rows = {
            row.business_key: row for row in batches.list_rows(batch_id)
        }
        current_locator = case.evidence_locators[0]
        related_locator = f"listing:{content_hash}:sheet:AE:row:3"
        rule = replace(
            _authority_rule(case),
            field_lineage={
                "raw_subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:authority:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
                "derived_event_term": {
                    "field": "AETERM",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "auditable_base_value",
                        "input_field_roles": ["raw_subject_id"],
                        "calculation_expression": (
                            "count_non_missing(raw_subject_id)"
                        ),
                        "unit": "count",
                        "source_locator": (
                            "listing:authority:derived:field:AETERM:header-source"
                        ),
                    },
                },
            },
        )
        forged = _rebuild_case(
            case,
            related_records={
                "AE": [
                    {
                        "USUBJID": "001",
                        "AETERM": "2",
                        "__source_locator__": related_locator,
                        "__auditable_base_values__": {
                            "AETERM": {
                                "source_type": "auditable_base_value",
                                "input_fields": ["USUBJID"],
                                "input_locators": [
                                    current_locator,
                                    related_locator,
                                ],
                                "calculation_expression": (
                                    "count_non_missing(raw_subject_id)"
                                ),
                                "unit": "count",
                                "calculated_value": "2",
                            },
                        },
                    },
                ],
            },
            evidence_locators=(current_locator, related_locator),
            source_row_bindings=(
                case.source_row_bindings[0],
                RuleGoldSourceRowBinding.create(
                    business_key="AE:002",
                    domain="AE",
                    source_locator=related_locator,
                    row_fingerprint=rows["AE:002"].row_fingerprint,
                    record_roles=("related:AE:0",),
                    field_bindings=(
                        RuleGoldRecordFieldBinding.create(
                            record_role="related:AE:0",
                            record_field="USUBJID",
                            source_field="USUBJID",
                        ),
                    ),
                ),
            ),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="raw field occurrence conflicts with the exact rule lineage",
        ):
            authority.validate(forged, rule)


def test_authority_rejects_duplicate_locator_count_inflation() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        rule = replace(
            _authority_rule(case),
            field_lineage={
                "raw_subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:authority:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
                "derived_subject_count": {
                    "field": "DERIVED_COUNT",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "auditable_base_value",
                        "input_field_roles": ["raw_subject_id"],
                        "calculation_expression": (
                            "count_non_missing(raw_subject_id)"
                        ),
                        "unit": "count",
                        "source_locator": (
                            "listing:authority:derived:field:DERIVED_COUNT:"
                            "header-source"
                        ),
                    },
                },
            },
        )
        locator = case.evidence_locators[0]
        forged = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "DERIVED_COUNT": "2",
                "__auditable_base_values__": {
                    "DERIVED_COUNT": {
                        "source_type": "auditable_base_value",
                        "input_fields": ["USUBJID"],
                        "input_locators": [locator, locator],
                        "calculation_expression": (
                            "count_non_missing(raw_subject_id)"
                        ),
                        "unit": "count",
                        "calculated_value": "2",
                    },
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="duplicate_input_locators",
        ):
            authority.validate(forged, rule)


def test_authority_rejects_omitted_same_subject_row_from_aggregate_scope() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provisional_path = root / "listing.xlsx"
        provisional_path.write_bytes(b"PK\x03\x04authoritative-listing")
        content_hash = sha256(provisional_path.read_bytes()).hexdigest()
        authority, _, case, _ = _frozen_authority_fixture(
            root,
            extra_rows=(
                {
                    "business_key": "AE:002",
                    "domain": "AE",
                    "data": {"USUBJID": "001", "AETERM": "恶心"},
                    "source_locator": {
                        "source_entry_id": f"listing-{content_hash[:16]}",
                        "source_content_sha256": content_hash,
                        "sheet": "AE",
                        "row": 3,
                    },
                },
            ),
        )
        rule = replace(
            _authority_rule(case),
            field_lineage={
                "raw_subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:authority:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
                "derived_subject_count": {
                    "field": "DERIVED_COUNT",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "auditable_base_value",
                        "input_field_roles": ["raw_subject_id"],
                        "calculation_expression": (
                            "count_non_missing(raw_subject_id)"
                        ),
                        "unit": "count",
                        "source_locator": (
                            "listing:authority:derived:field:DERIVED_COUNT:"
                            "header-source"
                        ),
                    },
                },
            },
        )
        forged = _rebuild_case(
            case,
            input_record={
                **case.input_record,
                "DERIVED_COUNT": "1",
                "__auditable_base_values__": {
                    "DERIVED_COUNT": {
                        "source_type": "auditable_base_value",
                        "input_fields": ["USUBJID"],
                        "input_locators": list(case.evidence_locators),
                        "calculation_expression": (
                            "count_non_missing(raw_subject_id)"
                        ),
                        "unit": "count",
                        "calculated_value": "1",
                    },
                },
            },
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="complete input scope is not fully bound",
        ):
            authority.validate(forged, rule)


def test_authority_reads_but_rejects_legacy_row_binding_without_field_sources() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        binding = case.source_row_bindings[0]
        legacy_binding = RuleGoldSourceRowBinding.from_mapping(
            {
                "business_key": binding.business_key,
                "domain": binding.domain,
                "source_locator": binding.source_locator,
                "row_fingerprint": binding.row_fingerprint,
                "record_roles": binding.record_roles,
            }
        )
        assert legacy_binding.field_bindings == ()
        legacy = _rebuild_case(
            case,
            source_row_bindings=(legacy_binding,),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="record role lacks field-level source bindings",
        ):
            authority.validate(legacy, _authority_rule(legacy))


def test_authority_rejects_forged_row_fingerprint() -> None:
    with TemporaryDirectory() as directory:
        authority, _, case, _ = _frozen_authority_fixture(Path(directory))
        binding = case.source_row_bindings[0]
        forged = _rebuild_case(
            case,
            source_row_bindings=(
                replace(
                    binding,
                    row_fingerprint=sha256(b"forged-fingerprint").hexdigest(),
                ),
            ),
        )
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="source row binding is stale or forged",
        ):
            authority.validate(forged, _authority_rule(forged))


def test_authority_rejects_noncanonical_frozen_row_identity_bytes() -> None:
    with TemporaryDirectory() as directory:
        authority, batches, case, _ = _frozen_authority_fixture(Path(directory))
        row = batches.list_rows(case.batch_revision.split("@v", 1)[0])[0]

        batches.list_rows = lambda _batch_id: [  # type: ignore[method-assign]
            replace(
                row,
                row_fingerprint=row.row_fingerprint.upper(),
            )
        ]
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="source row binding is stale or forged",
        ):
            authority.validate(case, _authority_rule(case))

        batches.list_rows = lambda _batch_id: [  # type: ignore[method-assign]
            replace(
                row,
                source_locator={
                    **row.source_locator,
                    "source_content_sha256": case.source_content_sha256.upper(),
                },
            )
        ]
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="source locator hash does not match",
        ):
            authority.validate(case, _authority_rule(case))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("source_revision", "source revision"),
        ("batch_revision", "batch revision"),
        ("source_kind", "EDC data listing"),
        ("duplicate_registry", "not uniquely registered"),
        ("not_frozen", "must be frozen"),
        ("wrong_role", "role is not"),
    ),
)
def test_authority_rejects_forged_or_non_release_evidence(
    mutation: str,
    message: str,
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        authority, batches, case, registration = _frozen_authority_fixture(
            root,
            freeze=mutation != "not_frozen",
            role="other_listing_role" if mutation == "wrong_role" else "edc_data_listing",
        )
        if mutation == "source_revision":
            case = replace(case, source_revision="forged-source-revision")
        elif mutation == "batch_revision":
            case = replace(case, batch_revision=case.batch_revision.rsplit("@v", 1)[0] + "@v999")
        elif mutation == "source_kind":
            authority = MonitoringGoldCaseAuthority(
                _RegistryReader(
                    (
                        _registration(
                            project_id=case.project_id,
                            entry_id=case.source_entry_id,
                            content_hash=case.source_content_sha256,
                            source_kind="protocol",
                        ),
                    )
                ),
                batches,
            )
        elif mutation == "duplicate_registry":
            authority = MonitoringGoldCaseAuthority(
                _RegistryReader(
                    (
                        registration,
                        registration.model_copy(
                            update={
                                "entry": registration.entry.model_copy(
                                    update={"public_title": "conflicting-listing.xlsx"}
                                )
                            }
                        ),
                    )
                ),
                batches,
            )
        with pytest.raises(MonitoringGoldCaseAuthorityError, match=message):
            authority.validate(case, _authority_rule(case))


def test_authority_rejects_missing_or_corrupted_content_object() -> None:
    with TemporaryDirectory() as directory:
        authority, batches, case, _ = _frozen_authority_fixture(Path(directory))
        source_id = case.source_revision.split("@", 1)[0]
        batches.object_path(source_id).unlink()
        with pytest.raises(
            MonitoringGoldCaseAuthorityError,
            match="object failed integrity",
        ):
            authority.validate(case, _authority_rule(case))


class _SwitchableAuthority:
    def __init__(self) -> None:
        self.allowed = True
        self.calls = 0

    def validate(self, _case: RuleGoldStandardCase, _rule: object) -> None:
        self.calls += 1
        if not self.allowed:
            raise ValueError("authoritative source drift")


def _lifecycle_ready_for_stage(
    root: Path,
    authority: _SwitchableAuthority,
) -> tuple[
    MonitoringProtocolRuleRepository,
    MonitoringRuleLifecycleService,
    object,
    object,
]:
    repository = MonitoringProtocolRuleRepository(
        root / "rules.sqlite3",
        gold_case_authority=authority.validate,
    )
    version = repository.register_protocol_version(
        _version(
            "proj_alpha",
            "V1.0",
            "2026-01-01",
            effective_from="2026-01-10",
        )
    )
    fact = repository.store_fact(_fact(version))
    rule = replace(_rule(version, fact), status="candidate")
    lifecycle = MonitoringRuleLifecycleService(
        repository,
        clock=lambda: "2026-01-15T00:00:00+00:00",
    )
    draft = lifecycle.create_draft(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=(rule,),
        created_by="rule_author",
    )
    confirmed_rule = lifecycle.confirm_rule(
        rule.rule_revision_id,
        expected_state_version=1,
        confirmed_by="medical_manager",
    )
    shadow = lifecycle.start_shadow(
        draft.rule_pack_id,
        started_by="shadow_operator",
    )
    locator, source = _gold_case_source(confirmed_rule, "authority-recheck")
    case = RuleGoldStandardCase.create(
        **source,
        project_id=version.project_id,
        rule_key=confirmed_rule.rule_key,
        case_label="authority-recheck",
        input_record={"SUBJID": "AUTH-001", "EXDESC": "按计划服药"},
        observed_domains=confirmed_rule.required_domains,
        expected_match=False,
        medical_rationale="验证生命周期重复校验。",
        evidence_locators=(locator,),
    )
    repository.store_gold_cases((case,))
    _store_p7c_release_evidence(repository, [confirmed_rule])
    return repository, lifecycle, shadow, version


@pytest.mark.parametrize("stage", ("shadow", "confirm", "publish", "current"))
def test_authority_is_rechecked_at_every_release_stage(stage: str) -> None:
    with TemporaryDirectory() as directory:
        authority = _SwitchableAuthority()
        repository, lifecycle, shadow, version = _lifecycle_ready_for_stage(
            Path(directory),
            authority,
        )
        service = MonitoringProtocolRuleService(repository)
        if stage == "shadow":
            authority.allowed = False
            with pytest.raises(RulePackLifecycleError, match="source drift"):
                service.run_shadow_validation(
                    rule_pack_id=shadow.rule_pack_id,
                    batch_id="authority-shadow",
                )
            return
        run = service.run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id="authority-shadow",
        )
        if stage == "confirm":
            authority.allowed = False
            with pytest.raises(RulePackLifecycleError, match="source drift"):
                lifecycle.confirm_shadow(
                    shadow.rule_pack_id,
                    shadow_run_id=run.shadow_run_id,
                    confirmed_by="medical_manager",
                )
            return
        confirmed = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by="medical_manager",
        )
        if stage == "publish":
            authority.allowed = False
            with pytest.raises(RulePackLifecycleError, match="source drift"):
                lifecycle.publish(
                    confirmed.rule_pack_id,
                    published_by="medical_manager",
                )
            return
        published = lifecycle.publish(
            confirmed.rule_pack_id,
            published_by="medical_manager",
        )
        authority.allowed = False
        with pytest.raises(RulePackLifecycleError, match="source drift"):
            repository.current_published_pack(
                version.project_id,
                as_of=published.published_at[:10],
            )
