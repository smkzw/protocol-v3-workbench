from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from packages.contracts.workbench_contracts import (
    ClinicalDatasetSummary,
    TflOutputSummary,
    TflReviewAction,
    TflReviewActionRequest,
    TflReviewQualityGate,
    TflReviewRecord,
    TflReviewWorkbenchResult,
    SourceAdmissionState,
)

from .tfl_manifest import TflManifestService
from .source_admission import (
    require_source_admission,
    source_bindings_are_current,
    unavailable_source_admission,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TflReviewStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: TflReviewRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def records(self, project_id: str, package_id: Optional[str] = None, output_id: Optional[str] = None) -> List[TflReviewRecord]:
        if not self.path.exists():
            return []
        records: List[TflReviewRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("project_id") != project_id:
                    continue
                if package_id and payload.get("package_id") != package_id:
                    continue
                if output_id and payload.get("output_id") != output_id:
                    continue
                records.append(TflReviewRecord.model_validate(payload))
        return records


class TflReviewWorkbenchService:
    def __init__(
        self,
        manifest_service: TflManifestService,
        store: TflReviewStore,
        source_admission_resolver: Callable[[str, str], SourceAdmissionState] | None = None,
        *,
        allow_unvalidated_sources: bool = False,
    ):
        self.manifest_service = manifest_service
        self.store = store
        self.source_admission_resolver = source_admission_resolver
        self.allow_unvalidated_sources = allow_unvalidated_sources

    def workbench(
        self,
        project_id: str,
        package_id: Optional[str] = None,
        output_id: Optional[str] = None,
    ) -> TflReviewWorkbenchResult:
        manifest = self.manifest_service.build_manifest(project_id, force_refresh=True)
        package = next((item for item in manifest.packages if item.package_id == package_id), None) if package_id else None
        if package is None:
            package = manifest.packages[0] if manifest.packages else None
        if package is None:
            raise KeyError("no TFL package available")

        candidate_outputs = _candidate_outputs(package.outputs)
        selected_output = next((item for item in package.outputs if item.output_id == output_id), None) if output_id else None
        if selected_output is None:
            selected_output = candidate_outputs[0] if candidate_outputs else (package.outputs[0] if package.outputs else None)

        paired_dataset = _paired_dataset(selected_output, package.datasets) if selected_output else None
        records = self.store.records(project_id, package.package_id, selected_output.output_id if selected_output else None)
        current_status = _status_from_records(records)
        source_admission = (
            self.source_admission_resolver(project_id, package.package_id)
            if self.source_admission_resolver
            else None if self.allow_unvalidated_sources else unavailable_source_admission(
                project_id,
                "data_analysis_tfl",
                package.package_id,
            )
        )
        source_review_current = not (
            records
            and current_status in {"医学已审阅", "写作引用候选"}
            and source_admission is not None
            and not source_bindings_are_current(
                records[-1].source_validation_bindings,
                source_admission,
            )
        )
        if not source_review_current:
            current_status = "来源已变化，需重新医学审阅"
        gates = _quality_gates(
            package,
            selected_output,
            paired_dataset,
            current_status,
            source_review_current=source_review_current,
        )

        return TflReviewWorkbenchResult(
            project_id=project_id,
            generated_at=utc_now(),
            package_id=package.package_id,
            package_label=package.package_label,
            selected_output_id=selected_output.output_id if selected_output else "",
            selected_output=selected_output,
            paired_dataset=paired_dataset,
            current_status=current_status,
            review_records=records[-20:],
            quality_gates=gates,
            candidate_outputs=candidate_outputs[:24],
            dataset_context=_dataset_context(package.datasets, paired_dataset, selected_output),
            source_admission=source_admission,
            available_actions=[
                TflReviewAction.MARK_REVIEWED,
                TflReviewAction.REQUEST_STATISTICAL_REVIEW,
                TflReviewAction.CREATE_WRITING_CANDIDATE,
                TflReviewAction.RETURN_FOR_DATASET_CHECK,
                TflReviewAction.RESET_REVIEW,
            ],
        )

    def apply_action(
        self,
        project_id: str,
        package_id: str,
        output_id: str,
        request: TflReviewActionRequest,
    ) -> TflReviewWorkbenchResult:
        snapshot = self.workbench(project_id, package_id=package_id, output_id=output_id)
        if snapshot.selected_output is None:
            raise KeyError(output_id)
        if request.action != TflReviewAction.RESET_REVIEW and not request.comment.strip():
            raise ValueError("TFL审阅动作必须填写医学/统计处理意见。")
        protected_action = request.action in {
            TflReviewAction.MARK_REVIEWED,
            TflReviewAction.CREATE_WRITING_CANDIDATE,
        }
        source_bindings = (
            require_source_admission(snapshot.source_admission)
            if protected_action and snapshot.source_admission is not None
            else []
        )
        if request.action == TflReviewAction.CREATE_WRITING_CANDIDATE:
            if snapshot.paired_dataset is None:
                raise ValueError("未配对分析数据集的TFL输出不能标记为写作引用候选。")
            if snapshot.current_status == "来源已变化，需重新医学审阅":
                raise ValueError("来源版本已变化，需基于当前来源重新完成医学审阅后再进入写作引用候选。")
            if snapshot.current_status != "医学已审阅":
                raise ValueError("需先完成医学审阅，才能标记为写作引用候选。")
            latest_record = snapshot.review_records[-1] if snapshot.review_records else None
            if (
                snapshot.source_admission is not None
                and (
                    latest_record is None
                    or latest_record.action != TflReviewAction.MARK_REVIEWED
                    or not source_bindings_are_current(
                        latest_record.source_validation_bindings,
                        snapshot.source_admission,
                    )
                )
            ):
                raise ValueError("来源版本已变化，需基于当前来源重新完成医学审阅后再进入写作引用候选。")

        previous_status = snapshot.current_status
        new_status = _status_for_action(request.action)
        created_at = utc_now()
        record = TflReviewRecord(
            record_id=f"tfl_review_{created_at.strftime('%Y%m%d%H%M%S%f')}",
            project_id=project_id,
            package_id=package_id,
            output_id=output_id,
            output_display_id=snapshot.selected_output.display_id,
            action=request.action,
            actor=request.actor,
            previous_status=previous_status,
            new_status=new_status,
            comment=request.comment.strip(),
            source_validation_bindings=source_bindings,
            created_at=created_at,
        )
        self.store.append(record)
        return self.workbench(project_id, package_id=package_id, output_id=output_id)


def _candidate_outputs(outputs: Iterable[TflOutputSummary]) -> List[TflOutputSummary]:
    priority = {"table": 0, "figure": 1, "listing": 2}
    return sorted(
        list(outputs),
        key=lambda item: (
            0 if item.domain_hint in {"AE", "ADSL", "DM", "LB", "EX"} else 1,
            priority.get(item.output_type, 9),
            0 if item.paired_file_id else 1,
            item.display_id,
        ),
    )


def _paired_dataset(output: Optional[TflOutputSummary], datasets: Iterable[ClinicalDatasetSummary]) -> Optional[ClinicalDatasetSummary]:
    if output is None or not output.paired_file_id:
        return None
    return next((dataset for dataset in datasets if dataset.dataset_id == output.paired_file_id), None)


def _dataset_context(
    datasets: Iterable[ClinicalDatasetSummary],
    paired_dataset: Optional[ClinicalDatasetSummary],
    output: Optional[TflOutputSummary],
) -> List[ClinicalDatasetSummary]:
    context: List[ClinicalDatasetSummary] = []
    if paired_dataset is not None:
        context.append(paired_dataset)
    domain = output.domain_hint if output else ""
    for dataset in datasets:
        if dataset in context:
            continue
        if domain and dataset.domain == domain:
            context.append(dataset)
        elif dataset.dataset_name in {"ADSL", "ADAE", "AE", "DM", "LB"}:
            context.append(dataset)
        if len(context) >= 8:
            break
    return context


def _status_from_records(records: List[TflReviewRecord]) -> str:
    if not records:
        return "待医学审阅"
    return records[-1].new_status


def _status_for_action(action: TflReviewAction) -> str:
    return {
        TflReviewAction.MARK_REVIEWED: "医学已审阅",
        TflReviewAction.REQUEST_STATISTICAL_REVIEW: "需统计复核",
        TflReviewAction.CREATE_WRITING_CANDIDATE: "写作引用候选",
        TflReviewAction.RETURN_FOR_DATASET_CHECK: "退回数据集核对",
        TflReviewAction.RESET_REVIEW: "待医学审阅",
    }[action]


def _quality_gates(
    package,
    output: Optional[TflOutputSummary],
    paired_dataset: Optional[ClinicalDatasetSummary],
    current_status: str,
    *,
    source_review_current: bool = True,
) -> List[TflReviewQualityGate]:
    output_ref = output.display_id if output else "未选择TFL输出"
    gates = [
        TflReviewQualityGate(
            gate_id="tfl_output_selected",
            gate_label="TFL对象选择",
            status="passed" if output else "blocked",
            detail=f"当前审阅对象：{output_ref}",
            source_refs=[output.output_id] if output else [],
        ),
        TflReviewQualityGate(
            gate_id="tfl_dataset_pairing",
            gate_label="分析数据配对",
            status="passed" if paired_dataset else "warning",
            detail="已配对交付数据集。" if paired_dataset else "未识别到同编号交付数据集，需统计/数据管理复核。",
            source_refs=[paired_dataset.dataset_id] if paired_dataset else [],
        ),
        TflReviewQualityGate(
            gate_id="tfl_define_alignment",
            gate_label="define一致性",
            status="passed" if package.define_itemgroup_count else "warning",
            detail="define.xml已提供数据集定义。" if package.define_itemgroup_count else "当前包未提供define.xml，变量含义需额外核对。",
            source_refs=[],
        ),
        TflReviewQualityGate(
            gate_id="tfl_medical_disposition",
            gate_label="医学审阅处置",
            status="passed" if current_status in {"医学已审阅", "写作引用候选"} else "blocking",
            detail=f"当前状态：{current_status}。正式写作引用前需完成医学/统计处置。",
            source_refs=[output.output_id] if output else [],
        ),
    ]
    gates.append(
        TflReviewQualityGate(
            gate_id="tfl_review_source_current",
            gate_label="医学审阅来源版本",
            status="passed" if source_review_current else "blocked",
            detail=(
                "当前医学审阅记录绑定的来源版本仍有效。"
                if source_review_current
                else "来源版本或准入状态已变化，原医学审阅状态不再作为当前晋级依据。"
            ),
            source_refs=[],
        )
    )
    return gates
