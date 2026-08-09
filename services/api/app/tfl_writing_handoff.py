from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from packages.contracts.workbench_contracts import (
    ClinicalDatasetSummary,
    TflOutputSummary,
    TflReviewQualityGate,
    TflReviewRecord,
    TflWritingCitationCandidate,
    TflWritingCitationManifestResult,
    SourceAdmissionState,
)

from .tfl_manifest import TflManifestService
from .tfl_review_workbench import TflReviewStore
from .source_admission import source_bindings_are_current, unavailable_source_admission


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TflWritingHandoffService:
    def __init__(
        self,
        manifest_service: TflManifestService,
        review_store: TflReviewStore,
        source_admission_resolver: Callable[[str, str], SourceAdmissionState] | None = None,
        *,
        allow_unvalidated_sources: bool = False,
    ):
        self.manifest_service = manifest_service
        self.review_store = review_store
        self.source_admission_resolver = source_admission_resolver
        self.allow_unvalidated_sources = allow_unvalidated_sources

    def has_handoff_candidate_records(self, project_id: str) -> bool:
        latest_by_output = _latest_records_by_output(self.review_store.records(project_id))
        return any(record.new_status == "写作引用候选" for record in latest_by_output.values())

    def citation_manifest(self, project_id: str) -> TflWritingCitationManifestResult:
        manifest = self.manifest_service.build_manifest(project_id)
        latest_by_output = _latest_records_by_output(self.review_store.records(project_id))
        candidates: List[TflWritingCitationCandidate] = []
        source_admissions: List[SourceAdmissionState] = []
        blocked_stale_candidate_count = 0
        for package in manifest.packages:
            source_admission = (
                self.source_admission_resolver(project_id, package.package_id)
                if self.source_admission_resolver
                else None if self.allow_unvalidated_sources else unavailable_source_admission(
                    project_id,
                    "data_analysis_tfl",
                    package.package_id,
                )
            )
            if source_admission is not None:
                source_admissions.append(source_admission)
            for output in package.outputs:
                record = latest_by_output.get((package.package_id, output.output_id))
                if record is None or record.new_status != "写作引用候选":
                    continue
                if source_admission is not None and not source_bindings_are_current(
                    record.source_validation_bindings,
                    source_admission,
                ):
                    blocked_stale_candidate_count += 1
                    continue
                paired_dataset = _paired_dataset(output, package.datasets)
                candidates.append(
                    TflWritingCitationCandidate(
                        candidate_id=f"tfl_citation_{record.record_id}",
                        project_id=project_id,
                        package_id=package.package_id,
                        package_label=package.package_label,
                        output_id=output.output_id,
                        output_display_id=output.display_id,
                        output_type=output.output_type,
                        domain_hint=output.domain_hint,
                        title_hint=output.title_hint,
                        paired_dataset_id=paired_dataset.dataset_id if paired_dataset else "",
                        paired_dataset_name=paired_dataset.dataset_name if paired_dataset else "",
                        paired_dataset_standard=paired_dataset.standard if paired_dataset else "",
                        paired_dataset_domain=paired_dataset.domain if paired_dataset else "",
                        paired_dataset_row_count=paired_dataset.row_count if paired_dataset else None,
                        review_record_id=record.record_id,
                        reviewer=record.actor,
                        review_comment=record.comment,
                        review_created_at=record.created_at,
                        recommended_writing_sections=_recommended_writing_sections(output, paired_dataset),
                        source_refs=_source_refs(record, output, paired_dataset),
                        source_validation_bindings=record.source_validation_bindings,
                    )
                )

        candidates.sort(key=lambda item: (item.review_created_at, item.output_display_id), reverse=True)
        gates = _quality_gates(candidates, blocked_stale_candidate_count)
        return TflWritingCitationManifestResult(
            project_id=project_id,
            generated_at=utc_now(),
            total_candidates=len(candidates),
            candidates=candidates,
            quality_gates=gates,
            source_admissions=source_admissions,
            blocked_stale_candidate_count=blocked_stale_candidate_count,
        )


def _latest_records_by_output(records: List[TflReviewRecord]) -> Dict[Tuple[str, str], TflReviewRecord]:
    latest: Dict[Tuple[str, str], TflReviewRecord] = {}
    for record in sorted(records, key=lambda item: item.created_at):
        latest[(record.package_id, record.output_id)] = record
    return latest


def _paired_dataset(
    output: TflOutputSummary,
    datasets: List[ClinicalDatasetSummary],
) -> Optional[ClinicalDatasetSummary]:
    if not output.paired_file_id:
        return None
    return next((dataset for dataset in datasets if dataset.dataset_id == output.paired_file_id), None)


def _recommended_writing_sections(
    output: TflOutputSummary,
    dataset: Optional[ClinicalDatasetSummary],
) -> List[str]:
    domain = (output.domain_hint or (dataset.domain if dataset else "")).upper()
    display = output.display_id.lower()
    if domain in {"AE", "ADAE"} or "ae" in display:
        return ["安全性结果", "M2.7.4临床安全性总结", "CSR安全性章节"]
    if domain in {"LB", "ADLB"} or "lab" in display:
        return ["实验室检查结果", "M2.7.4临床安全性总结", "CSR安全性章节"]
    if domain in {"ADSL", "DM", "EX"} or any(token in display for token in ["adsl", "dm", "disp", "ex"]):
        return ["受试者处置与基线特征", "研究人群", "CSR受试者分布章节"]
    if domain in {"QS", "ADQSMI", "ADQS", "ADEFF"} or any(token in display for token in ["eff", "easi", "iga", "tnss"]):
        return ["有效性结果", "M2.7.3临床有效性总结", "CSR有效性章节"]
    return ["统计结果引用待定章节", "CSR结果章节"]


def _source_refs(
    record: TflReviewRecord,
    output: TflOutputSummary,
    dataset: Optional[ClinicalDatasetSummary],
) -> List[str]:
    refs = [record.record_id, output.output_id]
    if dataset:
        refs.append(dataset.dataset_id)
    return refs


def _quality_gates(
    candidates: List[TflWritingCitationCandidate],
    blocked_stale_candidate_count: int = 0,
) -> List[TflReviewQualityGate]:
    no_candidate = not candidates
    missing_dataset = [item for item in candidates if not item.paired_dataset_id]
    missing_comment = [item for item in candidates if not item.review_comment.strip()]
    gates = [
        TflReviewQualityGate(
            gate_id="tfl_citation_candidate_presence",
            gate_label="TFL引用候选",
            status="warning" if no_candidate else "passed",
            detail="尚无TFL写作引用候选。" if no_candidate else f"当前共有{len(candidates)}个TFL写作引用候选。",
            source_refs=[item.candidate_id for item in candidates[:8]],
        ),
        TflReviewQualityGate(
            gate_id="tfl_citation_dataset_pairing",
            gate_label="配对数据集",
            status="warning" if missing_dataset else "passed",
            detail="部分候选缺少配对数据集，正式引用前需统计/数据管理复核。" if missing_dataset else "全部候选均保留配对数据集引用。",
            source_refs=[item.candidate_id for item in missing_dataset[:8]],
        ),
        TflReviewQualityGate(
            gate_id="tfl_citation_medical_comment",
            gate_label="医学处置意见",
            status="blocked" if missing_comment else "passed",
            detail="存在缺少医学/统计处置意见的候选。" if missing_comment else "全部候选均有医学/统计处置意见。",
            source_refs=[item.candidate_id for item in missing_comment[:8]],
        ),
    ]
    gates.append(
        TflReviewQualityGate(
            gate_id="tfl_source_version_current",
            gate_label="来源版本准入",
            status="blocked" if blocked_stale_candidate_count else "passed",
            detail=(
                f"{blocked_stale_candidate_count}个既有候选绑定的来源版本已变化或未完成确认，已停止交接。"
                if blocked_stale_candidate_count
                else "写作引用候选绑定的来源版本仍为当前可用版本。"
            ),
            source_refs=[],
        )
    )
    return gates
