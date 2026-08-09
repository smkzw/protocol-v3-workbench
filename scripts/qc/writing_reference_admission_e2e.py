from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("QC_API_BASE_URL", "http://127.0.0.1:8911").rstrip("/")
OUTPUT = Path(
    os.environ.get(
        "QC_OUTPUT_PATH",
        "records/visual_qc_20260712/writing_reference_admission_e2e.json",
    )
)

CASES = (
    {
        "project_id": "proj_rux_03_002",
        "translation_id": "wref_translation_320b83e76b4364435130",
        "translation_revision": 2,
    },
    {
        "project_id": "proj_my008_pnh_3_01",
        "translation_id": "wref_translation_7d89fb59810b983e73c6",
        "translation_revision": 1,
    },
)


def request_json(method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def source_selection(project_id: str):
    session = request_json("GET", f"/api/projects/{project_id}/medical-writing/document-session")
    for section_summary in session["sections"][:60]:
        section = request_json(
            "GET",
            f"/api/projects/{project_id}/medical-writing/document-session/sections/{section_summary['section_id']}",
        )
        for block in section["content_blocks"]:
            text = str(block.get("text", "")).strip()
            if block.get("block_type") == "paragraph" and len(text) >= 40:
                return session, section, block
    raise RuntimeError(f"no substantive source paragraph found: {project_id}")


def current_working_copy_revision(project_id: str, section_id: str) -> int:
    payload = request_json(
        "GET",
        f"/api/projects/{project_id}/medical-writing/working-copies/{section_id}",
    )
    return int(payload.get("revision", 0))


def run_case(case: dict) -> dict:
    project_id = case["project_id"]
    translation_id = case["translation_id"]
    translation_revision = case["translation_revision"]
    review = request_json(
        "POST",
        f"/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/medical-review",
        {
            "translation_revision": translation_revision,
            "decision": "approved",
            "comment": "隔离端到端测试医学审核者逐字核对原文与监管中文候选，确认医学含义、否定关系和限定条件一致。",
            "actor": "isolated_qc_medical_reviewer",
            "expected_revision": 0,
            "idempotency_key": f"isolated-e2e-review-{project_id}",
        },
    )
    brief = request_json(
        "POST",
        f"/api/projects/{project_id}/medical-writing/references/translations/{translation_id}/admissions",
        {
            "expected_translation_revision": translation_revision,
            "medical_review_id": review["review_id"],
            "idempotency_key": f"isolated-e2e-admission-{project_id}",
        },
    )
    session, section, block = source_selection(project_id)
    revision_before = current_working_copy_revision(project_id, section["section_id"])
    result = request_json(
        "POST",
        f"/api/projects/{project_id}/revision-threads",
        {
            "document_id": session["document_id"],
            "section_id": section["section_id"],
            "anchor_type": "paragraph",
            "anchor_path": block["source_locator"],
            "selected_text": block["text"],
            "user_instruction": "结合本次已批准竞品方案证据，将所选段落改写为更清晰的待医学批准方案候选；不得新增来源未支持的医学结论。",
            "intent": "medical_writing_revision",
            "evidence_brief_ids": [brief["brief_id"]],
            "requested_by": "isolated_qc_medical_manager",
        },
    )
    revision_after = current_working_copy_revision(project_id, section["section_id"])
    thread = result["thread"]
    ai_runs = request_json("GET", f"/api/projects/{project_id}/ai-runs")
    ai_run = next(item for item in ai_runs if item["run_id"] == thread["ai_run_id"])

    failures = []
    if review["decision"] != "approved":
        failures.append("medical-review-not-approved")
    if brief["status"] != "approved_current":
        failures.append("brief-not-current")
    if thread["evidence_brief_ids"] != [brief["brief_id"]]:
        failures.append("thread-brief-link-mismatch")
    if result["audit_event"]["detail"]["evidence_brief_ids"] != [brief["brief_id"]]:
        failures.append("audit-brief-link-mismatch")
    if result["approval_state"] != "in_medical_review":
        failures.append("revision-not-pending-medical-review")
    if revision_before != revision_after:
        failures.append("working-copy-was-auto-modified")
    if ai_run["provider"] != "buddy" or ai_run["model_name"] != "deepseek-v4-pro":
        failures.append("unexpected-independent-ai-route")
    if ai_run["codex_runtime_dependency"]:
        failures.append("codex-runtime-dependency")
    if ai_run["status"] != "completed":
        failures.append("ai-run-not-completed")

    return {
        "project_id": project_id,
        "translation_id": translation_id,
        "translation_revision": translation_revision,
        "review_id": review["review_id"],
        "brief_id": brief["brief_id"],
        "brief_status": brief["status"],
        "document_id": session["document_id"],
        "section_id": section["section_id"],
        "source_locator": block["source_locator"],
        "thread_id": thread["thread_id"],
        "thread_status": thread["status"],
        "approval_state": result["approval_state"],
        "ai_run_id": thread["ai_run_id"],
        "ai_provider": ai_run["provider"],
        "ai_model": ai_run["model_name"],
        "codex_runtime_dependency": ai_run["codex_runtime_dependency"],
        "working_copy_revision_before": revision_before,
        "working_copy_revision_after": revision_after,
        "failures": failures,
    }


def main() -> None:
    cases = [run_case(case) for case in CASES]
    failures = [f"{case['project_id']}:{failure}" for case in cases for failure in case["failures"]]
    report = {"api_base": BASE_URL, "isolated_runtime": True, "cases": cases, "failures": failures}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
