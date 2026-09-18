"""Compound design is proposed, and retains period/arm/administration structure."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.protocol_workflow.agent2.clinical_worker import RegimenProposal


def regimen():
    return {"input_sha256": "a" * 64,
        "periods": [{"id": "period-first", "label": "首期", "timing": "第0至4周"},
                    {"id": "period-next", "label": "继续期", "timing": "第4至8周"}],
        "arms": [{"id": "arm-active", "label": "试验组"}, {"id": "arm-control", "label": "原对照组"}],
        "schedules": [{"period_id": period, "arm_id": arm, "steps": [
            {"kind": "loading", "timing": "本期首次", "frequency": "一次", "route": "皮下注射",
             "products": [{"name": "试验药X", "dose": {"value": 200, "unit": "mg"},
                           "volume": {"value": 2, "unit": "mL"}}],
             "references": [{"source_artifact_id": "source-fixture", "locator": "body/1", "quote": "合成给药依据"}]},
            {"kind": "maintenance", "timing": "首次之后", "frequency": "每2周一次", "route": "皮下注射",
             "products": [{"name": "试验药X", "dose": {"value": 100, "unit": "mg"}}],
             "references": [{"source_artifact_id": "source-fixture", "locator": "body/2", "quote": "合成维持依据"}]}]}
            for period in ("period-first", "period-next") for arm in ("arm-active", "arm-control")],
        "unresolved_questions": []}


def test_json_roundtrip_retains_all_four_cells_and_both_dose_steps():
    value = RegimenProposal.model_validate(regimen())
    restored = RegimenProposal.model_validate_json(value.model_dump_json())
    assert restored == value
    assert restored.canonical_state == "proposed"
    assert len(restored.schedules) == 4
    assert all([step.products[0].dose.value for step in schedule.steps] == [200, 100] for schedule in restored.schedules)
    assert restored.schedules[0].steps[0].products[0].volume.unit == "mL"


def test_unknown_arm_or_period_is_not_silently_dropped():
    payload = regimen()
    payload["schedules"][0]["arm_id"] = "arm-missing"
    with pytest.raises(ValidationError, match="regimen_schedule_target_unknown"):
        RegimenProposal.model_validate(payload)


def test_duplicate_cell_cannot_replace_the_other_arm():
    payload = regimen()
    payload["schedules"][1] = deepcopy(payload["schedules"][0])
    with pytest.raises(ValidationError, match="regimen_schedule_duplicate"):
        RegimenProposal.model_validate(payload)


def test_amount_text_is_not_coerced_and_proposal_cannot_claim_confirmation():
    payload = regimen()
    payload["schedules"][0]["steps"][0]["products"][0]["dose"]["value"] = "200"
    with pytest.raises(ValidationError):
        RegimenProposal.model_validate(payload)
    payload = regimen()
    payload["canonical_state"] = "confirmed"
    with pytest.raises(ValidationError):
        RegimenProposal.model_validate(payload)


def test_native_quantity_number_type_is_preserved():
    value = RegimenProposal.model_validate(regimen())
    assert type(value.schedules[0].steps[0].products[0].dose.value) is int
    payload = regimen()
    payload["schedules"][0]["steps"][0]["products"][0]["dose"]["value"] = 2.5
    value = RegimenProposal.model_validate(payload)
    assert type(value.schedules[0].steps[0].products[0].dose.value) is float


def test_design_input_keeps_full_sources_and_every_seed_candidate():
    from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
    from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
    request = prepare_seed_request("先整理已有资料", ())
    seed = read_seed_candidates(request, {"fields": {}})
    prepared = prepare_regimen_request(request, seed)
    payload = prepared.to_payload()
    assert payload["source_intake"] == request.to_payload()
    assert payload["seed_proposal"] == seed
    assert payload["output_schema"]["properties"]["coverage"]["type"] == "array"
    assert "regimen" in payload["output_schema"]["required"]
    seed["user_brief"] = "after compilation"
    assert prepared.to_payload()["seed_proposal"]["user_brief"] == "先整理已有资料"


def test_design_compilation_rejects_another_seed_input():
    from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
    from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
    original = prepare_seed_request("原意图", ())
    seed = read_seed_candidates(original, {"fields": {}})
    with pytest.raises(ValueError, match="design_candidate_input_mismatch"):
        prepare_regimen_request(prepare_seed_request("已改变意图", ()), seed)


def prepared_reference():
    from datetime import datetime, timezone
    import hashlib
    from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact
    from app.protocol_workflow.agent1.docx_parse import parse_docx
    from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
    from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
    from test_writing_reference_docx import build_docx, paragraph_xml
    data = build_docx(paragraph_xml("合成给药依据：200 mg，2 mL。") + paragraph_xml("合成维持依据：100 mg。"))
    source = SourceArtifact(source_artifact_id="source-fixture", logical_source_key="reference",
        content_sha256=hashlib.sha256(data).hexdigest(), source_role="company_style_only",
        source_version="1", jurisdiction="CN", mime_type="application/docx", captured_at=datetime.now(timezone.utc))
    intake = prepare_seed_request("只整理历史参考", ((source, parse_docx(data)),))
    seed = read_seed_candidates(intake, {"fields": {}})
    output = {"coverage": [], "regimen": regimen(), "questions": []}
    output["regimen"]["input_sha256"] = intake.input_sha256
    units = intake.to_payload()["sources"][0]["units"]
    for schedule in output["regimen"]["schedules"]:
        for i, step in enumerate(schedule["steps"]):
            step["references"][0]["locator"] = units[i]["locator"]
    return prepare_regimen_request(intake, seed), output


def test_reference_regimen_stays_reference_and_never_becomes_confirmed_facts():
    from app.protocol_workflow.agent2.clinical_worker import read_regimen_response
    prepared, output = prepared_reference()
    result = read_regimen_response(prepared, output)
    assert result["status"] == "ready_for_review"
    assert result["regimen"]["canonical_state"] == "proposed"
    assert all(step["source_support"] == "reference_only" for schedule in result["regimen"]["schedules"] for step in schedule["steps"])
    assert "facts" not in result


def test_new_regimen_quote_must_exist_in_its_bound_original_source_unit():
    from app.protocol_workflow.agent2.clinical_worker import read_regimen_response
    prepared, output = prepared_reference()
    output["regimen"]["schedules"][0]["steps"][0]["references"][0]["quote"] = "不存在的400 mg"
    with pytest.raises(ValueError, match="regimen_source_quote_not_found"):
        read_regimen_response(prepared, output)


def test_regimen_from_another_input_cannot_be_adopted_as_this_proposal():
    from app.protocol_workflow.agent2.clinical_worker import read_regimen_response
    prepared, output = prepared_reference()
    output["regimen"]["input_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="design_candidate_input_mismatch"):
        read_regimen_response(prepared, output)


def test_missing_regimen_is_information_gap_not_a_fabricated_complete_design():
    from app.protocol_workflow.agent2.clinical_worker import read_regimen_response
    prepared, _ = prepared_reference()
    result = read_regimen_response(prepared, {"coverage": [], "regimen": None, "questions": ["本研究是否拟采用该参考给药安排？"]})
    assert result["status"] == "needs_information"
    assert result["regimen"] is None
