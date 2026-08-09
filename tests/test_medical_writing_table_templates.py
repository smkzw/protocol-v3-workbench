from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.medical_writing_table_templates import (
    MedicalWritingTableTemplateService,
)
from services.api.app.medical_writing_table_domain_profiles import (
    MedicalWritingTableDomainProfileService,
)
from services.api.app.medical_writing_tables import MedicalWritingTableService


def test_catalog_covers_reusable_protocol_table_domains_without_project_rules():
    catalog = MedicalWritingTableTemplateService().catalog()
    ids = {item["template_id"] for item in catalog}
    assert {
        "schedule_of_activities",
        "objectives_endpoints",
        "sample_size_assumptions",
        "treatment_dose",
        "dose_modification",
        "stopping_rules",
        "ae_management",
        "laboratory_panel",
        "pk_immunogenicity_schedule",
        "analysis_sets",
        "version_history",
        "generic_table",
    }.issubset(ids)
    serialized = str(catalog)
    for project_specific_token in ("RUX-03-002", "CMS-D001", "MG-K10", "MY009"):
        assert project_specific_token not in serialized
    assert next(
        item for item in catalog if item["template_id"] == "schedule_of_activities"
    )["designer_kind"] == "schedule_of_activities"


def test_domain_profile_catalog_promotes_only_real_evidence_backed_domains():
    profiles = MedicalWritingTableDomainProfileService().catalog()
    by_domain = {item["domain"]: item for item in profiles}
    assert set(by_domain) == {
        "objectives_endpoints",
        "sample_size_assumptions",
        "treatment_dose",
        "dose_modification",
        "laboratory_panel",
        "pk_immunogenicity_schedule",
        "analysis_sets",
        "version_history",
    }
    assert by_domain["dose_modification"]["evidence_grade"] == "B"
    assert by_domain["dose_modification"]["designer_status"] == "guarded"
    serialized = str(profiles)
    for forbidden in (
        "RUX-03-002",
        "CMS-D001",
        "ALT >",
        "AST >",
        "ANC <",
    ):
        assert forbidden not in serialized
    dose_profile = by_domain["dose_modification"]
    assert "不是合并用药（CM）" in dose_profile["warning_text"]
    assert all(
        "CM" not in role["role_id"] and "CM" not in str(role["options"])
        for role in dose_profile["column_roles"]
    )
    assert by_domain["sample_size_assumptions"]["evidence_grade"] == "A"
    assert by_domain["sample_size_assumptions"]["designer_status"] == "promoted"
    assert by_domain["analysis_sets"]["evidence_grade"] == "A"
    assert by_domain["analysis_sets"]["designer_status"] == "promoted"
    assert by_domain["pk_immunogenicity_schedule"]["evidence_grade"] == "A"
    assert by_domain["pk_immunogenicity_schedule"]["designer_status"] == "promoted"
    assert "固定" in by_domain["pk_immunogenicity_schedule"]["warning_text"]


def test_promoted_templates_attach_typed_roles_without_medical_content_approval():
    service = MedicalWritingTableTemplateService()
    for template_id in (
        "objectives_endpoints",
        "sample_size_assumptions",
        "treatment_dose",
        "dose_modification",
        "laboratory_panel",
        "pk_immunogenicity_schedule",
        "analysis_sets",
        "version_history",
    ):
        block = service.instantiate(template_id, instance_id=f"profile-{template_id}")
        table = MedicalWritingTableService().from_table_block(block)
        profile_state = table.word_layout["domain_profile"]
        assert profile_state["profile_id"] == template_id
        assert profile_state["mapping_status"] == "template_roles_attached"
        assert profile_state["confirmed_by_user"] is False
        assert all(column.semantic_role for column in table.columns)
        assert table.review_state.value == "ai_draft"


def test_additional_profiles_keep_source_faithful_core_roles_and_flexible_sampling_layout():
    service = MedicalWritingTableTemplateService()
    profiles = MedicalWritingTableDomainProfileService()

    sample_size = MedicalWritingTableService().from_table_block(
        service.instantiate("sample_size_assumptions", instance_id="sample-size-profile")
    )
    assert [column.semantic_role for column in sample_size.columns] == [
        "parameter",
        "base_assumption",
        "source_basis",
        "sensitivity_scenario",
        "pending_confirmation",
    ]
    sample_required = {
        role.role_id
        for role in profiles.for_domain("sample_size_assumptions").column_roles
        if role.required
    }
    assert sample_required == {"parameter", "base_assumption"}

    analysis_sets = MedicalWritingTableService().from_table_block(
        service.instantiate("analysis_sets", instance_id="analysis-sets-profile")
    )
    assert [column.semantic_role for column in analysis_sets.columns[:2]] == [
        "set_name",
        "definition",
    ]
    analysis_required = {
        role.role_id
        for role in profiles.for_domain("analysis_sets").column_roles
        if role.required
    }
    assert analysis_required == {"set_name", "definition"}
    assert [row.cells[0].text for row in analysis_sets.rows[1:]] == [
        "全分析集（FAS）",
        "符合方案集（PPS）",
        "安全性集（SS）",
    ]
    assert all(
        cell.text.strip()
        for row in analysis_sets.rows[1:]
        for cell in row.cells
    )

    sampling_profile = profiles.for_domain("pk_immunogenicity_schedule")
    assert not any(role.required for role in sampling_profile.column_roles)
    assert {
        "assessment_type",
        "sampling_timepoint",
        "dose_relation",
        "analyte",
        "specimen_matrix",
        "sample_reference_id",
        "handling_storage_shipping",
        "conditional_trigger",
    }.issubset({role.role_id for role in sampling_profile.column_roles})


def test_two_column_analysis_set_and_uncoerced_sampling_matrix_can_be_confirmed():
    templates = MedicalWritingTableTemplateService()
    profiles = MedicalWritingTableDomainProfileService()
    table_service = MedicalWritingTableService()

    analysis = table_service.from_table_block(
        templates.instantiate("analysis_sets", instance_id="source-faithful-two-column")
    )
    kept_columns = analysis.columns[:2]
    kept_ids = {column.column_id for column in kept_columns}
    analysis.columns = kept_columns
    for row in analysis.rows:
        row.cells = [cell for cell in row.cells if cell.column_id in kept_ids]
    analysis.word_layout["domain_profile"].update(
        {
            "mapping_status": "confirmed_by_user",
            "confirmed_by_user": True,
        }
    )
    analysis_findings = profiles.validate(analysis)
    assert not any(item["code"] == "required_role_unmapped" for item in analysis_findings)
    assert not any(item["severity"] == "error" for item in analysis_findings)

    sampling = table_service.from_table_block(
        templates.instantiate("pk_immunogenicity_schedule", instance_id="source-matrix")
    )
    for column in sampling.columns:
        column.semantic_role = ""
    sampling.word_layout["domain_profile"].update(
        {
            "mapping_status": "confirmed_by_user",
            "confirmed_by_user": True,
            "record_axis": "semantic_only",
        }
    )
    sampling_findings = profiles.validate(sampling)
    assert not any(item["code"] == "required_role_unmapped" for item in sampling_findings)
    assert not any(item["severity"] == "error" for item in sampling_findings)


def test_profile_validation_rejects_unknown_role_but_returns_review_warnings():
    templates = MedicalWritingTableTemplateService()
    profiles = MedicalWritingTableDomainProfileService()
    block = templates.instantiate("objectives_endpoints", instance_id="validation")
    table = MedicalWritingTableService().from_table_block(block)
    table.columns[0].semantic_role = "not_a_real_role"
    findings = profiles.validate(table)
    assert any(item["severity"] == "error" for item in findings)
    try:
        profiles.assert_valid(table)
    except ValueError as exc:
        assert "not_a_real_role" in str(exc)
    else:
        raise AssertionError("unknown semantic roles must fail closed")

    table.columns[0].semantic_role = "hierarchy"
    table.word_layout["domain_profile"]["mapping_status"] = "pending_user_confirmation"
    findings = profiles.validate(table)
    assert not any(item["severity"] == "error" for item in findings)
    assert any(item["code"] == "mapping_pending" for item in findings)


def test_row_record_profiles_warn_for_missing_required_content_without_blocking_save():
    templates = MedicalWritingTableTemplateService()
    profiles = MedicalWritingTableDomainProfileService()
    table = MedicalWritingTableService().from_table_block(
        templates.instantiate("objectives_endpoints", instance_id="row-validation")
    )
    findings = profiles.validate(table)
    assert any(item["code"] == "required_cell_empty" for item in findings)
    assert not any(item["severity"] == "error" for item in findings)
    profiles.assert_valid(table)

    table.word_layout["domain_profile"]["record_axis"] = "semantic_only"
    findings = profiles.validate(table)
    assert not any(item["code"] == "required_cell_empty" for item in findings)


def test_instantiated_template_is_editable_structured_generated_block():
    service = MedicalWritingTableTemplateService()
    block = service.instantiate(
        "objectives_endpoints",
        title="研究目的与终点表",
        instance_id="unit-test-001",
    )
    assert block["block_id"].startswith("mwgenerated_")
    assert block["table_id"].startswith("mwgenerated_")
    assert block["source_kind"] == "medical_writing_template"
    assert block["source_locator"].startswith(
        "generated:medical_writing_template:objectives_endpoints:"
    )
    assert block["template_id"] == "objectives_endpoints"
    assert block["editable"] is True
    assert block["title"] == "研究目的与终点表"
    table = MedicalWritingTableService().from_table_block(block)
    assert table.title == "研究目的与终点表"
    assert table.header_row_count == 1
    assert len(table.columns) == 6
    assert len(table.rows) == 4
    assert table.columns[0].semantic_role == "hierarchy"


def test_generic_table_uses_user_dimensions_headers_orientation_and_notes_area():
    service = MedicalWritingTableTemplateService()
    block = service.instantiate(
        "generic_table",
        title="研究访视补充评估表",
        instance_id="custom-table-001",
        row_count=7,
        column_count=4,
        header_row_count=2,
        orientation="portrait",
        notes_area=True,
    )
    table = MedicalWritingTableService().from_table_block(block)

    assert table.domain.value == "generic"
    assert table.title == "研究访视补充评估表"
    assert len(table.columns) == 4
    assert len(table.rows) == 7
    assert table.header_row_count == 2
    assert [column.label for column in table.columns] == ["列 1", "列 2", "列 3", "列 4"]
    assert all(row.style_role == "header" for row in table.rows[:2])
    assert all(cell.style_role == "header" for row in table.rows[:2] for cell in row.cells)
    assert table.word_layout["orientation"] == "portrait"
    assert table.word_layout["notes_area_enabled"] is True
    assert table.word_layout["width_policy"] == "autofit"


def test_generic_table_rejects_invalid_custom_dimensions():
    service = MedicalWritingTableTemplateService()
    for kwargs in (
        {"row_count": 1},
        {"column_count": 21},
        {"row_count": 4, "header_row_count": 4},
        {"orientation": "diagonal"},
    ):
        try:
            service.instantiate("generic_table", **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid generic table options must fail: {kwargs}")


def test_repository_accepts_multiple_templates_and_rejects_identity_collision():
    service = MedicalWritingTableTemplateService()
    first = service.instantiate(
        "dose_modification",
        instance_id="template-one",
    )
    second = service.instantiate(
        "laboratory_panel",
        instance_id="template-two",
    )
    MedicalWritingRuntimeRepository._validate_working_copy_blocks([], [first, second])

    duplicate = service.instantiate(
        "analysis_sets",
        instance_id="template-one",
    )
    try:
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            [],
            [first, duplicate],
        )
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate generated table identity must be rejected")


def test_every_template_round_trips_through_table_contract():
    service = MedicalWritingTableTemplateService()
    for index, item in enumerate(service.catalog()):
        block = service.instantiate(
            item["template_id"],
            instance_id=f"roundtrip-{index}",
        )
        table = MedicalWritingTableService().from_table_block(block)
        assert table.domain.value == item["domain"]
        assert table.title == item["label"]
        assert all(row.cells for row in table.rows)


def test_semantic_roles_and_profile_state_survive_block_round_trip():
    block = MedicalWritingTableTemplateService().instantiate(
        "laboratory_panel",
        instance_id="semantic-roundtrip",
    )
    table_service = MedicalWritingTableService()
    first = table_service.from_table_block(block)
    exported = table_service.to_table_block(first)
    second = table_service.from_table_block(exported)
    assert [column.semantic_role for column in second.columns] == [
        "panel",
        "analyte",
        "specimen_preparation",
        "unit_reference_range",
        "collection_visit",
        "abnormality_retest_rule",
    ]
    assert second.word_layout["domain_profile"] == first.word_layout["domain_profile"]
