from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("QC_API_BASE_URL", "http://127.0.0.1:8912").rstrip("/")
PHASE = os.environ.get("QC_PHASE", "execute").strip()
OUTPUT = Path(
    os.environ.get(
        "QC_OUTPUT_PATH",
        "records/active_slices/safety_pv_dual_project_fullchain_20260714/"
        "safety_pv_dual_project_e2e.json",
    )
)
PROJECTS = ("proj_rux_03_002", "proj_my009_uc")


def request_json(
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    expected_status: int = 200,
):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=300) as response:
            status = response.status
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        status = exc.code
        response_body = exc.read().decode("utf-8", errors="replace")
    if status != expected_status:
        raise RuntimeError(
            f"{method} {path} returned HTTP {status}, expected {expected_status}: {response_body}"
        )
    return json.loads(response_body) if response_body else {}


def review_workbench(project_id: str, package_id: str = "", signal_id: str = "") -> dict:
    query = []
    if package_id:
        query.append(f"package_id={quote(package_id, safe='')}")
    if signal_id:
        query.append(f"signal_id={quote(signal_id, safe='')}")
    suffix = f"?{'&'.join(query)}" if query else ""
    return request_json("GET", f"/api/projects/{project_id}/safety-pv/review-workbench{suffix}")


def confirm_warned_sources(project_id: str, workbench: dict) -> list[dict]:
    confirmations = []
    admission = workbench.get("source_admission") or {}
    for source in admission.get("sources", []):
        if source.get("use_status") != "requires_confirmation":
            continue
        warning_codes = [
            check["check_code"]
            for check in source.get("checks", [])
            if check.get("outcome") in {"warning", "mismatch"} and check.get("overridable")
        ]
        confirmation = request_json(
            "POST",
            f"/api/projects/{project_id}/sources/{quote(source['source_entry_id'], safe='')}/"
            "content-validation/confirm",
            {
                "reason": (
                    "隔离端到端测试：医学经理已核对项目、适应症、文件角色及当前使用场景，"
                    "确认该内部权威资料可在保留警告和审计记录的前提下用于本次复核。"
                ),
                "acknowledged_check_codes": warning_codes,
                "actor": "isolated_qc_medical_manager",
                "expected_revision": source["revision"],
                "idempotency_key": f"safety-source-confirm:{project_id}:{source['source_entry_id']}",
            },
        )
        confirmations.append(
            {
                "source_entry_id": source["source_entry_id"],
                "previous_revision": source["revision"],
                "new_revision": confirmation["revision"],
                "use_status": confirmation["use_status"],
                "acknowledged_check_codes": warning_codes,
            }
        )
    return confirmations


def action_path(project_id: str, package_id: str, signal_id: str) -> str:
    return (
        f"/api/projects/{project_id}/safety-pv/review-workbench/"
        f"{quote(package_id, safe='')}/signals/{quote(signal_id, safe='')}/actions"
    )


def apply_review_action(
    project_id: str,
    package_id: str,
    signal_id: str,
    *,
    action: str,
    expected_revision: int,
    source_binding_digest: str,
    key: str,
    comment: str,
    expected_status: int = 200,
) -> dict:
    return request_json(
        "POST",
        action_path(project_id, package_id, signal_id),
        {
            "action": action,
            "actor": "isolated_qc_medical_manager",
            "comment": comment,
            "expected_revision": expected_revision,
            "idempotency_key": key,
            "expected_source_binding_digest": source_binding_digest,
        },
        expected_status=expected_status,
    )


def create_monitoring_collaboration(project_id: str) -> dict:
    inbox = request_json("GET", f"/api/projects/{project_id}/workbench-inbox?limit=200")
    risk = next(
        item
        for item in inbox["items"]
        if item["item_type"] == "risk" and item["status"] == "待医学复核"
    )
    response = request_json(
        "POST",
        f"/api/projects/{project_id}/workbench-inbox/{quote(risk['item_id'], safe='')}/risk-disposition",
        {
            "action": "reviewed",
            "disposition_kind": "safety_pv_collaboration",
            "actor": "isolated_qc_medical_manager",
            "comment": "已完成当前来源版本医学复核，转Safety/PV协作；不创建第二套风险或中心Query。",
            "expected_source_version": risk["source_version"],
            "idempotency_key": f"monitoring-safety-pv:{project_id}:{risk['item_id']}",
            "medical_judgments": {
                "patient_safety_impact": True,
                "key_data_impact": False,
                "query_required": False,
                "lock_or_export_impact": False,
                "review_completed": True,
            },
        },
    )
    projected = next(
        item
        for item in response["items"]
        if item.get("source_type") == "monitoring_safety_pv_collaboration"
        and item.get("risk_instance_id") == risk.get("risk_instance_id")
    )
    return {
        "risk_id": risk["source_id"],
        "risk_key": risk.get("risk_key", ""),
        "risk_instance_id": risk.get("risk_instance_id", ""),
        "snapshot_id": risk.get("snapshot_id", ""),
        "source_version": risk["source_version"],
        "projected_item_id": projected["item_id"],
        "projected_status": projected["status"],
        "projected_target_page": projected["target_page"],
    }


def run_project(project_id: str) -> dict:
    initial = review_workbench(project_id)
    package_id = initial["package_id"]
    signal_id = initial["selected_signal_id"]
    original_digest = initial["source_binding_digest"]
    confirmations = confirm_warned_sources(project_id, initial)
    current = review_workbench(project_id, package_id, signal_id)
    if not (current.get("source_admission") or {}).get("ready_for_use"):
        raise RuntimeError(f"source admission remains blocked after confirmation: {project_id}")
    current_digest = current["source_binding_digest"]

    source_drift_status = "not_applicable"
    if confirmations and original_digest != current_digest:
        drift = apply_review_action(
            project_id,
            package_id,
            signal_id,
            action="mark_medical_reviewed",
            expected_revision=0,
            source_binding_digest=original_digest,
            key=f"stale-source-digest:{project_id}",
            comment="旧来源绑定不得提交。",
            expected_status=409,
        )
        source_drift_status = drift["detail"]

    early_pv = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="request_pv_confirmation",
        expected_revision=0,
        source_binding_digest=current_digest,
        key=f"pv-too-early:{project_id}",
        comment="未完成医学复核，不应进入PV确认候选。",
        expected_status=409,
    )
    reviewed = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="mark_medical_reviewed",
        expected_revision=0,
        source_binding_digest=current_digest,
        key=f"review:{project_id}",
        comment="已逐项核对原始listing、PV资料文件及当前来源版本，完成医学复核。",
    )
    replay = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="mark_medical_reviewed",
        expected_revision=0,
        source_binding_digest=current_digest,
        key=f"review:{project_id}",
        comment="已逐项核对原始listing、PV资料文件及当前来源版本，完成医学复核。",
    )
    stale_revision = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="return_for_source_check",
        expected_revision=0,
        source_binding_digest=current_digest,
        key=f"stale-revision:{project_id}",
        comment="陈旧页面不得覆盖当前复核状态。",
        expected_status=409,
    )
    pv_candidate = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="request_pv_confirmation",
        expected_revision=1,
        source_binding_digest=current_digest,
        key=f"pv-candidate:{project_id}",
        comment="请PV基于当前来源版本确认安全性报告边界和后续协作事项。",
    )
    handoff_before_close = request_json(
        "GET", f"/api/projects/{project_id}/safety-pv/handoff-candidates"
    )
    closed = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="accept_no_action",
        expected_revision=2,
        source_binding_digest=current_digest,
        key=f"withdraw-and-close:{project_id}",
        comment="撤回PV候选；现有资料下暂无需继续协作，保留复核与撤回审计。",
    )
    handoff_after_close = request_json(
        "GET", f"/api/projects/{project_id}/safety-pv/handoff-candidates"
    )
    reset = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="reset_review",
        expected_revision=3,
        source_binding_digest=current_digest,
        key=f"reset-after-close:{project_id}",
        comment="为验证重新开启复核，显式重置处置状态。",
    )
    returned = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="return_for_source_check",
        expected_revision=4,
        source_binding_digest=current_digest,
        key=f"return-source:{project_id}",
        comment="需补充当前批次可核对的来源资料后再完成医学复核。",
    )
    reviewed_again = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="mark_medical_reviewed",
        expected_revision=5,
        source_binding_digest=current_digest,
        key=f"review-again:{project_id}",
        comment="补充资料已核对，基于同一当前来源版本重新完成医学复核。",
    )
    final = apply_review_action(
        project_id,
        package_id,
        signal_id,
        action="reset_review",
        expected_revision=6,
        source_binding_digest=current_digest,
        key=f"final-reset:{project_id}",
        comment="端到端验证完成，重置为待医学/PV确认以验证冷启动恢复。",
    )
    monitoring = create_monitoring_collaboration(project_id)
    handoff_with_monitoring = request_json(
        "GET", f"/api/projects/{project_id}/safety-pv/handoff-candidates"
    )
    monitoring_handoff = next(
        item
        for item in handoff_with_monitoring["monitoring_collaborations"]
        if item["risk_instance_id"] == monitoring["risk_instance_id"]
    )

    failures = []
    expectations = {
        "reviewed": (reviewed["current_status"], "医学已复核"),
        "replay_revision": (replay["state_revision"], 1),
        "pv_candidate": (pv_candidate["current_status"], "PV确认候选"),
        "handoff_before_close": (handoff_before_close["total_candidates"], 1),
        "closed": (closed["current_status"], "关闭为暂无需处理"),
        "handoff_after_close": (handoff_after_close["total_candidates"], 0),
        "reset": (reset["current_status"], "待医学/PV确认"),
        "returned": (returned["current_status"], "退回补充资料"),
        "reviewed_again": (reviewed_again["current_status"], "医学已复核"),
        "final_revision": (final["state_revision"], 7),
        "final_status": (final["current_status"], "待医学/PV确认"),
        "monitoring_handoff_current": (monitoring_handoff["is_current"], True),
        "monitoring_handoff_risk_key": (monitoring_handoff["risk_key"], monitoring["risk_key"]),
    }
    for label, (actual, expected) in expectations.items():
        if actual != expected:
            failures.append(f"{label}: expected={expected!r}, actual={actual!r}")
    if "医学复核" not in str(early_pv.get("detail", "")):
        failures.append("early-pv-transition-was-not-rejected")
    if "stale" not in str(stale_revision.get("detail", "")).lower():
        failures.append("stale-revision-was-not-rejected")
    if confirmations and "来源版本已变化" not in source_drift_status:
        failures.append("stale-source-binding-was-not-rejected")

    return {
        "project_id": project_id,
        "package_id": package_id,
        "signal_id": signal_id,
        "source_confirmations": confirmations,
        "source_binding_digest_before": original_digest,
        "source_binding_digest_current": current_digest,
        "source_drift_rejection": source_drift_status,
        "early_pv_rejection": early_pv.get("detail"),
        "stale_revision_rejection": stale_revision.get("detail"),
        "five_actions": [
            "mark_medical_reviewed",
            "request_pv_confirmation",
            "accept_no_action",
            "reset_review",
            "return_for_source_check",
        ],
        "final_revision": final["state_revision"],
        "final_status": final["current_status"],
        "review_record_count": len(final["review_records"]),
        "monitoring_collaboration": monitoring,
        "monitoring_handoff": monitoring_handoff,
        "failures": failures,
    }


def execute() -> dict:
    cases = [run_project(project_id) for project_id in PROJECTS]
    health = request_json("GET", "/api/health")
    failures = [
        f"{case['project_id']}:{failure}"
        for case in cases
        for failure in case["failures"]
    ]
    return {
        "api_base": BASE_URL,
        "isolated_runtime": True,
        "phase": "execute",
        "health": health,
        "cases": cases,
        "failures": failures,
    }


def verify_restart() -> dict:
    report = json.loads(OUTPUT.read_text(encoding="utf-8"))
    restart_cases = []
    failures = []
    for previous in report["cases"]:
        current = review_workbench(
            previous["project_id"],
            previous["package_id"],
            previous["signal_id"],
        )
        handoff = request_json(
            "GET", f"/api/projects/{previous['project_id']}/safety-pv/handoff-candidates"
        )
        case_failures = []
        if current["state_revision"] != previous["final_revision"]:
            case_failures.append("state-revision-not-recovered")
        if current["current_status"] != previous["final_status"]:
            case_failures.append("state-status-not-recovered")
        if handoff["monitoring_collaboration_count"] != 1:
            case_failures.append("monitoring-collaboration-not-recovered")
        restart_cases.append(
            {
                "project_id": previous["project_id"],
                "state_revision": current["state_revision"],
                "current_status": current["current_status"],
                "review_record_count": len(current["review_records"]),
                "monitoring_collaboration_count": handoff["monitoring_collaboration_count"],
                "blocked_monitoring_collaboration_count": handoff[
                    "blocked_monitoring_collaboration_count"
                ],
                "failures": case_failures,
            }
        )
        failures.extend(f"{previous['project_id']}:{item}" for item in case_failures)
    report["restart_verification"] = {
        "health": request_json("GET", "/api/health"),
        "cases": restart_cases,
        "failures": failures,
    }
    report["phase"] = "verified_after_restart"
    report["failures"] = [*report.get("failures", []), *failures]
    return report


def main() -> None:
    report = execute() if PHASE == "execute" else verify_restart()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report.get("failures"):
        raise SystemExit("; ".join(report["failures"]))


if __name__ == "__main__":
    main()
