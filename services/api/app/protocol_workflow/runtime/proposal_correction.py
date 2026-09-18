"""One structural correction from a known raw response; no dispatch here."""


def structure_correction_inputs(prepared, record, validation, *, input_name, error_prefix):
    if validation["valid"] or validation["status"] != "needs_structure_correction":
        raise ValueError(error_prefix + "_correction_not_required")
    receipt = record["receipt"]
    if any(a["ref"] == "correction-context" for a in receipt["input_artifacts"]):
        raise ValueError(error_prefix + "_correction_budget_exhausted")
    if (prepared.input_sha256 not in {a["sha256"] for a in receipt["input_artifacts"]}
            or receipt["output_sha256"] != validation["raw_response"]["output_sha256"]):
        raise ValueError(error_prefix + "_correction_material_mismatch")
    return {input_name: prepared.to_payload(), "correction_context": {
        "instruction": "根据原始资料修复上次回复的结构或引用错误。不要补造研究事实；缺失字段仍可省略。只输出符合原请求结构的JSON。",
        "previous_output": record["content"], "errors": validation["errors"],
        "previous_artifact_ref": validation["raw_response"]["artifact_ref"],
        "previous_response_id": receipt["provider_session_id"],
        "provider": receipt["observed_provider"], "model": receipt["observed_model"],
        "requested_reasoning_effort": receipt["requested_reasoning_effort"],
    }}
