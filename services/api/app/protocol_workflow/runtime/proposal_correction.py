"""One structural correction from a known raw response; no dispatch here."""
import json


_MAX_CORRECTION_OUTPUT_CHARS = 12000


def _path_value(payload, location):
    current = payload
    parts = location.split(".") if isinstance(location, str) else ()
    if not parts:
        return None
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _previous_output_context(content, errors):
    """Keep the full small response; otherwise retain error-local material."""
    if len(content) <= _MAX_CORRECTION_OUTPUT_CHARS:
        return content, False
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        payload = None
    fragments = []
    if isinstance(payload, dict):
        for error in errors or ():
            location = error.get("location") if isinstance(error, dict) else None
            value = _path_value(payload, location)
            if value is not None:
                fragments.append({"location": location, "value": value})
    if fragments:
        excerpt = json.dumps(
            {"error_fragments": fragments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        line_number = None
        for error in errors or ():
            location = error.get("location") if isinstance(error, dict) else ""
            if isinstance(location, str) and location.startswith("line:"):
                try:
                    line_number = int(location.split(":")[1])
                except (IndexError, ValueError):
                    pass
                break
        if line_number is not None:
            lines = content.splitlines(keepends=True)
            start = max(0, line_number - 3)
            excerpt = "".join(lines[start:start + 6])
        else:
            excerpt = content[:_MAX_CORRECTION_OUTPUT_CHARS]
    return excerpt[:_MAX_CORRECTION_OUTPUT_CHARS], True



def _compact_correction_input(prepared):
    """Drop only bytes duplicated by the persisted chapter input.

    Chapter source material repeats the exact top-level evidence list.  The
    correction still receives the complete parsed source structure and the
    canonical evidence list, so validation and citation identity remain
    unchanged while the request avoids sending that list twice.
    """
    payload = prepared.to_payload()
    source_material = payload.get("source_material")
    if (isinstance(source_material, dict)
            and source_material.get("evidence") == payload.get("evidence")):
        source_material = dict(source_material)
        source_material.pop("evidence", None)
        payload = {**payload, "source_material": source_material}
    return payload


def _compact_errors(errors):
    """Retain only stable error locations and actionable diagnostic text."""
    compact = []
    for error in errors or ():
        if not isinstance(error, dict):
            continue
        item = {
            key: error[key]
            for key in ("code", "location", "issue", "detail")
            if key in error and error[key] not in (None, "")
        }
        if item:
            compact.append(item)
    return compact


def structure_correction_inputs(prepared, record, validation, *, input_name, error_prefix):
    if validation["valid"] or validation["status"] != "needs_structure_correction":
        raise ValueError(error_prefix + "_correction_not_required")
    receipt = record["receipt"]
    if any(a["ref"] == "correction-context" for a in receipt["input_artifacts"]):
        raise ValueError(error_prefix + "_correction_budget_exhausted")
    if (prepared.input_sha256 not in {a["sha256"] for a in receipt["input_artifacts"]}
            or receipt["output_sha256"] != validation["raw_response"]["output_sha256"]):
        raise ValueError(error_prefix + "_correction_material_mismatch")
    errors = _compact_errors(validation["errors"])
    previous_output, previous_output_is_excerpt = _previous_output_context(
        record["content"], errors)
    return {input_name: _compact_correction_input(prepared), "correction_context": {
        "instruction": "根据原始资料修复上次回复的结构或引用错误。不要补造研究事实；缺失字段仍可省略。只输出符合原请求结构的完整JSON。若previous_output_is_excerpt为true，片段仅用于定位，请基于原始输入重新生成完整回复。",
        "previous_output": previous_output,
        "previous_output_is_excerpt": previous_output_is_excerpt,
        "errors": errors,
        "previous_artifact_ref": validation["raw_response"]["artifact_ref"],
        "previous_response_id": receipt["provider_session_id"],
        "provider": receipt["observed_provider"], "model": receipt["observed_model"],
        "requested_reasoning_effort": receipt["requested_reasoning_effort"],
    }}
