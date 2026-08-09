from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

from .monitoring_batch_repository import (
    DiffReadyBatch,
    MonitoringBatchRepositoryError,
    NormalizedRow,
    RecordNotFoundError,
    SourceRegistration,
)
from .monitoring_batch_rule_runner import (
    _anchor_domain,
    _current_predicate_fields,
    _group_rows_by_subject,
    _materialize_record,
    _record_from_row,
)
from .monitoring_gold_case_authority import (
    MonitoringGoldCaseAuthorityError,
    _canonical_domain,
    _canonical_row_locator,
    monitoring_batch_revision,
    monitoring_source_revision,
)
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    MonitoringProtocolRuleRepository,
)
from .monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
    RuleEvaluationNotSupported,
    RuleShadowValidationRun,
)
from .monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    MonitoringRulePack,
    RuleDiagnosticCase,
    RuleGoldRecordFieldBinding,
    RuleGoldSourceRowBinding,
    RuleGoldStandardCase,
    ShadowProvisionalSample,
    ShadowProvisionalSampleSet,
    ShadowSampleMedicalConfirmation,
    validate_rule_field_lineage,
)
from .monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
    MonitoringRuleAuthoringService,
)


class MonitoringShadowSampleError(MonitoringRuleAuthoringError):
    """Automatic shadow sample preparation fails closed with a precise code."""


class _UnbindableCandidate(ValueError):
    """One evaluated record cannot be bound to its frozen rows exactly."""


_RULE_IDENTITY_FIELDS = (
    "mapping_revision",
    "mapping_content_sha256",
    "capability_manifest_sha256",
    "effective_capabilities_sha256",
)

_DIAGNOSTIC_CATEGORY_BY_CODE = {
    "missing_required_domains": "missing_input",
    "missing_source_evidence": "incomplete_evidence",
    "indeterminate_predicate": "invalid_input",
}

_BUCKET_LABELS = {
    "positive": "阳性",
    "negative": "阴性",
    "boundary": "边界",
    "diagnostic": "不可判定诊断",
}


@dataclass(frozen=True)
class ShadowSampleInspection:
    """Result of one automatic provisional sample preparation."""

    pack: MonitoringRulePack
    sample_set: ShadowProvisionalSampleSet
    reused: bool


@dataclass(frozen=True)
class ShadowLineageEvidence:
    """Shadow-stage sample evidence projected across the pack lineage."""

    project_id: str
    rule_pack_id: str
    shadow_rule_pack_id: str
    sample_sets: tuple[ShadowProvisionalSampleSet, ...]
    confirmation: ShadowSampleMedicalConfirmation | None


@dataclass(frozen=True)
class _EvaluatedCandidate:
    rule: MonitoringRuleDefinition
    subject_id: str
    business_key: str
    bucket: str
    matched: bool
    evaluation_state: str
    diagnostic_code: str
    input_record: dict[str, Any]
    related_records: dict[str, list[dict[str, Any]]]
    observed_domains: tuple[str, ...]


@dataclass(frozen=True)
class _BatchSource:
    source_entry_id: str
    source_content_sha256: str
    source_revision: str


class MonitoringShadowSampleService:
    """Prepare server-side provisional shadow samples from a frozen batch.

    The medical manager only chooses the frozen batch. The server selects
    representative rows, evaluates the pack's rules against them and stores
    an immutable provisional sample set recording ONLY actual outcomes.
    Nothing here writes gold/diagnostic cases or trusted shadow runs: only
    the explicit `confirm_samples` medical act may promote the exact frozen
    snapshot into trusted expectation.
    """

    def __init__(
        self,
        *,
        repository: MonitoringProtocolRuleRepository,
        batch_repository: Any,
        protocol_rule_service: MonitoringProtocolRuleService,
        rule_authoring_service: MonitoringRuleAuthoringService,
    ):
        self.repository = repository
        self.batch_repository = batch_repository
        self.protocol_rule_service = protocol_rule_service
        self.rule_authoring_service = rule_authoring_service
        # Late-bound back-reference: the authoring service orchestrates
        # confirm-shadow via this service without a constructor cycle.
        rule_authoring_service.set_shadow_sample_service(self)

    def prepare_and_run(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        batch_id: str,
        actor: str,
        expected_pack_revision: int | None = None,
    ) -> ShadowSampleInspection:
        # `actor` authorizes the call and is recorded as audit metadata; it
        # never enters sample content, so identities stay deterministic.
        pack, rules = self.rule_authoring_service._rule_pack(
            project_id,
            rule_pack_id,
            status="shadow",
        )
        if expected_pack_revision is not None and int(
            expected_pack_revision
        ) != pack.pack_revision:
            raise MonitoringShadowSampleError(
                "monitoring_rule_pack_revision_stale",
                f"规则包修订已变化：预期 {expected_pack_revision}，"
                f"当前为 {pack.pack_revision}，请刷新后重试。",
                http_status=409,
            )
        mapping_revision = self._verified_rule_mapping_identity(rules)
        batch = self._frozen_batch(
            project_id,
            batch_id,
            rules=rules,
            mapping_revision=mapping_revision,
        )
        diff_batch = self.batch_repository.load_diff_ready_batch(batch_id)
        source = self._batch_source(project_id, diff_batch)
        rows_by_locator = self._rows_by_locator(
            diff_batch,
            source.source_content_sha256,
        )
        samples: list[ShadowProvisionalSample] = []
        rows_by_subject, _grouping_diagnostics = _group_rows_by_subject(
            diff_batch,
            rule_pack_id=rule_pack_id,
        )
        for rule in sorted(rules, key=lambda item: item.rule_key):
            samples.extend(
                self._prepare_rule_samples(
                    project_id=project_id,
                    pack=pack,
                    rule=rule,
                    batch=diff_batch,
                    batch_record=batch,
                    source=source,
                    rows_by_subject=rows_by_subject,
                    rows_by_locator=rows_by_locator,
                )
            )

        sample_set = ShadowProvisionalSampleSet.create(
            project_id=project_id,
            rule_pack_id=pack.rule_pack_id,
            batch_id=batch.batch_id,
            batch_version=int(batch.version),
            batch_revision=monitoring_batch_revision(
                batch.batch_id,
                batch.version,
            ),
            mapping_revision=mapping_revision,
            mapping_content_sha256=rules[0].mapping_content_sha256,
            capability_manifest_sha256=rules[0].capability_manifest_sha256,
            effective_capabilities_sha256=(
                rules[0].effective_capabilities_sha256
            ),
            rule_revision_ids=[
                rule.rule_revision_id for rule in rules
            ],
            samples=samples,
            created_by=actor,
            created_at=self._now_text(),
        )
        try:
            self.repository.shadow_sample_set(sample_set.sample_set_id)
            reused = True
        except MonitoringProtocolRecordNotFound:
            reused = False
        stored = self.repository.store_shadow_sample_set(sample_set)
        return ShadowSampleInspection(
            pack=pack,
            sample_set=stored,
            reused=reused,
        )

    def confirm_samples(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        sample_set_id: str,
        actor: str,
        expected_pack_revision: int | None = None,
    ) -> tuple[ShadowSampleMedicalConfirmation, RuleShadowValidationRun]:
        """Promote the exact frozen provisional snapshot into trusted truth.

        Revalidates every recorded actual outcome against the current exact
        rule revisions, computes the trusted shadow run over the merged
        repository case set, then commits the promoted gold/diagnostic
        cases, the trusted run and the immutable medical confirmation
        record through a single repository transaction: any failure rolls
        the whole confirmation attempt back. Any drift fails closed.
        """
        pack, rules = self.rule_authoring_service._rule_pack(
            project_id,
            rule_pack_id,
            status="shadow",
        )
        if expected_pack_revision is not None and int(
            expected_pack_revision
        ) != pack.pack_revision:
            raise MonitoringShadowSampleError(
                "monitoring_rule_pack_revision_stale",
                f"规则包修订已变化：预期 {expected_pack_revision}，"
                f"当前为 {pack.pack_revision}，请刷新后重试。",
                http_status=409,
            )
        try:
            sample_set = self.repository.shadow_sample_set(sample_set_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_sample_set_not_found",
                "当前项目未找到该影子样本集。",
                http_status=404,
            ) from exc
        if (
            sample_set.project_id != project_id
            or sample_set.rule_pack_id != rule_pack_id
        ):
            raise MonitoringShadowSampleError(
                "monitoring_shadow_sample_set_scope_conflict",
                "该影子样本集不属于当前规则包。",
                http_status=409,
            )
        existing_confirmation = self.repository.shadow_sample_confirmation(
            project_id,
            rule_pack_id,
        )
        if (
            existing_confirmation is not None
            and existing_confirmation.sample_set_id
            != sample_set.sample_set_id
        ):
            raise MonitoringShadowSampleError(
                "monitoring_shadow_confirmation_conflict",
                "该规则包已确认另一影子样本集，不能重复确认。",
                http_status=409,
            )
        if existing_confirmation is not None:
            # Idempotent replay of the exact confirmation act already
            # recorded for this sample set: return the recorded act and
            # its trusted run instead of re-promoting or re-validating.
            trusted_run = next(
                (
                    item
                    for item in self.repository.shadow_runs(
                        project_id,
                        rule_pack_id=rule_pack_id,
                    )
                    if item.shadow_run_id
                    == existing_confirmation.trusted_shadow_run_id
                ),
                None,
            )
            if trusted_run is None:
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_confirmation_drift",
                    "影子样本集与当前规则、映射或冻结批次状态不一致；"
                    "请重新准备影子样本。",
                    http_status=409,
                )
            return existing_confirmation, trusted_run
        self._assert_confirmation_freshness(
            project_id=project_id,
            rules=rules,
            sample_set=sample_set,
        )
        self._assert_sample_outcomes(
            rules=rules,
            sample_set=sample_set,
        )

        diff_batch = self.batch_repository.load_diff_ready_batch(
            sample_set.batch_id
        )
        source = self._batch_source(project_id, diff_batch)
        rationale = (
            f"医学经理确认影子样本集 {sample_set.sample_set_id} "
            "中的冻结样本，将记录的实际评估结果登记为医学确认的期望结果。"
        )
        gold_cases: list[RuleGoldStandardCase] = []
        diagnostic_cases: list[RuleDiagnosticCase] = []
        for sample in sample_set.samples:
            if sample.bucket == "diagnostic":
                category = _DIAGNOSTIC_CATEGORY_BY_CODE.get(
                    sample.actual_diagnostic_code
                )
                if category is None:
                    raise MonitoringShadowSampleError(
                        "monitoring_shadow_diagnostic_code_unmapped",
                        f"规则 {sample.rule_key} 返回了未登记的诊断代码 "
                        f"{sample.actual_diagnostic_code}，"
                        "不能自动归类诊断案例。",
                        http_status=422,
                    )
                diagnostic_cases.append(
                    RuleDiagnosticCase.create(
                        project_id=project_id,
                        rule_key=sample.rule_key,
                        rule_revision_id=sample.rule_revision_id,
                        source_entry_id=source.source_entry_id,
                        source_content_sha256=source.source_content_sha256,
                        source_revision=source.source_revision,
                        batch_revision=sample_set.batch_revision,
                        case_label=sample.case_label,
                        input_record=sample.input_record,
                        related_records=sample.related_records,
                        observed_domains=sample.observed_domains,
                        expected_diagnostic_category=category,
                        expected_diagnostic_code=sample.actual_diagnostic_code,
                        medical_rationale=rationale,
                        evidence_locators=sample.evidence_locators,
                        source_row_bindings=sample.source_row_bindings,
                    )
                )
                continue
            coverage_labels = (
                ("positive",)
                if sample.bucket == "positive"
                else (
                    ("negative",)
                    if sample.bucket == "negative"
                    else ("negative", "boundary")
                )
            )
            gold_cases.append(
                RuleGoldStandardCase.create(
                    project_id=project_id,
                    rule_key=sample.rule_key,
                    rule_revision_id=sample.rule_revision_id,
                    source_entry_id=source.source_entry_id,
                    source_content_sha256=source.source_content_sha256,
                    source_revision=source.source_revision,
                    batch_revision=sample_set.batch_revision,
                    case_label=sample.case_label,
                    input_record=sample.input_record,
                    related_records=sample.related_records,
                    observed_domains=sample.observed_domains,
                    expected_match=sample.actual_matched,
                    coverage_labels=coverage_labels,
                    medical_rationale=rationale,
                    evidence_locators=sample.evidence_locators,
                    source_row_bindings=sample.source_row_bindings,
                )
            )
        pre_run = self.protocol_rule_service.run_shadow_validation(
            rule_pack_id=rule_pack_id,
            batch_id=sample_set.batch_id,
            cases=gold_cases,
            diagnostic_cases=diagnostic_cases,
        )
        if pre_run.failed_count or pre_run.diagnostic_failed_count:
            # Failure-atomic gate: the promotion cases were revalidated in
            # memory before anything reached the repository, so a failed
            # confirmation leaves zero trusted cases behind.
            raise MonitoringShadowSampleError(
                "monitoring_shadow_confirmation_run_failed",
                "晋升前的影子复验未全部通过，不能登记医学确认。",
                http_status=409,
            )
        trusted_run = self.protocol_rule_service.compute_repository_shadow_run(
            rule_pack_id=rule_pack_id,
            batch_id=sample_set.batch_id,
            additional_gold_cases=gold_cases,
            additional_diagnostic_cases=diagnostic_cases,
        )
        if trusted_run.failed_count or trusted_run.diagnostic_failed_count:
            # Defensive gate: the merged repository case set was evaluated
            # in memory before the atomic commit, so a failure here means
            # pre-existing registered evidence drifted; nothing is written.
            raise MonitoringShadowSampleError(
                "monitoring_shadow_confirmation_run_failed",
                "晋升后的可信影子复验未全部通过，不能登记医学确认。",
                http_status=409,
            )
        confirmation = ShadowSampleMedicalConfirmation.create(
            project_id=project_id,
            rule_pack_id=rule_pack_id,
            sample_set_id=sample_set.sample_set_id,
            sample_set_content_sha256=sample_set.content_sha256,
            trusted_shadow_run_id=trusted_run.shadow_run_id,
            confirmed_by=actor,
            confirmed_at=self._now_text(),
        )
        (
            _stored_gold,
            _stored_diagnostic,
            stored_run,
            stored_confirmation,
        ) = self.repository.commit_shadow_sample_confirmation(
            gold_cases=gold_cases,
            diagnostic_cases=diagnostic_cases,
            run=trusted_run,
            confirmation=confirmation,
        )
        return (
            stored_confirmation,
            self.protocol_rule_service.trusted_shadow_run_view(stored_run),
        )

    def lineage_evidence(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
    ) -> ShadowLineageEvidence:
        """Project shadow-stage sample evidence for any lineage stage.

        Sample sets and medical confirmations bind the shadow-stage pack
        id; fresh-loading a confirmed or published pack walks the strict
        lifecycle chain back to its shadow ancestor so the evidence stays
        reachable. A lineage without a shadow stage yields empty evidence,
        never an error.
        """
        try:
            pack, _rules = self.repository.rule_pack(rule_pack_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise MonitoringShadowSampleError(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
                http_status=404,
            ) from exc
        if pack.project_id != project_id:
            raise MonitoringShadowSampleError(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
                http_status=404,
            )
        shadow_pack = self.repository.rule_pack_stage_ancestor(
            project_id,
            rule_pack_id,
            status="shadow",
        )
        if shadow_pack is None:
            return ShadowLineageEvidence(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                shadow_rule_pack_id="",
                sample_sets=(),
                confirmation=None,
            )
        return ShadowLineageEvidence(
            project_id=project_id,
            rule_pack_id=rule_pack_id,
            shadow_rule_pack_id=shadow_pack.rule_pack_id,
            sample_sets=self.repository.shadow_sample_sets(
                project_id,
                rule_pack_id=shadow_pack.rule_pack_id,
            ),
            confirmation=self.repository.shadow_sample_confirmation(
                project_id,
                shadow_pack.rule_pack_id,
            ),
        )

    def _assert_confirmation_freshness(
        self,
        *,
        project_id: str,
        rules: Sequence[MonitoringRuleDefinition],
        sample_set: ShadowProvisionalSampleSet,
    ) -> None:
        def _drift() -> MonitoringShadowSampleError:
            return MonitoringShadowSampleError(
                "monitoring_shadow_confirmation_drift",
                "影子样本集与当前规则、映射或冻结批次状态不一致；"
                "请重新准备影子样本。",
                http_status=409,
            )

        current_revision_ids = tuple(
            sorted(rule.rule_revision_id for rule in rules)
        )
        if (
            tuple(sorted(sample_set.rule_revision_ids))
            != current_revision_ids
        ):
            raise _drift()
        mapping_revision = self._verified_rule_mapping_identity(rules)
        if mapping_revision != sample_set.mapping_revision:
            raise _drift()
        for rule in rules:
            if (
                rule.mapping_content_sha256
                != sample_set.mapping_content_sha256
                or rule.capability_manifest_sha256
                != sample_set.capability_manifest_sha256
                or rule.effective_capabilities_sha256
                != sample_set.effective_capabilities_sha256
            ):
                raise _drift()
        try:
            batch = self.batch_repository.get_batch(sample_set.batch_id)
        except RecordNotFoundError as exc:
            raise _drift() from exc
        if batch.project_id != project_id or batch.state != "frozen":
            raise _drift()
        if int(batch.version) != int(sample_set.batch_version):
            raise _drift()
        if (
            monitoring_batch_revision(batch.batch_id, batch.version)
            != sample_set.batch_revision
        ):
            raise _drift()
        if (
            str(batch.active_mapping_revision or "")
            != sample_set.mapping_revision
        ):
            raise _drift()
        try:
            contract = self.batch_repository.load_frozen_mapping_contract(
                sample_set.batch_id
            )
        except MonitoringBatchRepositoryError as exc:
            raise _drift() from exc
        if (
            contract.mapping_content_sha256
            != sample_set.mapping_content_sha256
            or contract.capability_manifest_sha256
            != sample_set.capability_manifest_sha256
        ):
            raise _drift()

    def _assert_sample_outcomes(
        self,
        *,
        rules: Sequence[MonitoringRuleDefinition],
        sample_set: ShadowProvisionalSampleSet,
    ) -> None:
        rules_by_revision = {
            rule.rule_revision_id: rule for rule in rules
        }
        for sample in sample_set.samples:
            rule = rules_by_revision.get(sample.rule_revision_id)
            if rule is None or rule.rule_key != sample.rule_key:
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_confirmation_drift",
                    "影子样本集与当前规则、映射或冻结批次状态不一致；"
                    "请重新准备影子样本。",
                    http_status=409,
                )
            try:
                evaluation = self.protocol_rule_service.evaluate_record(
                    rule,
                    sample.input_record,
                    observed_domains=sample.observed_domains,
                    related_records=sample.related_records,
                    allow_non_enabled=True,
                    validation_mode="shadow",
                )
            except (
                MonitoringProtocolRuleError,
                RuleEvaluationNotSupported,
            ) as exc:
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_confirmation_outcome_drift",
                    f"样本 {sample.sample_id} 无法按冻结快照复评，"
                    "不能登记医学确认。",
                    http_status=409,
                ) from exc
            state = str(
                evaluation.evidence.get("evaluation_state") or ""
            ).strip().lower()
            code = str(
                evaluation.evidence.get("diagnostic_code") or ""
            ).strip().lower()
            if (
                evaluation.matched != sample.actual_matched
                or state != sample.actual_evaluation_state
                or code != sample.actual_diagnostic_code
            ):
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_confirmation_outcome_drift",
                    f"样本 {sample.sample_id} 的复评结果与冻结快照"
                    "记录的实际结果不一致，不能登记医学确认。",
                    http_status=409,
                )
            if sample.bucket != "diagnostic" and (
                state not in {"true", "false"}
                or evaluation.evidence.get("evidence_ready") is not True
            ):
                # Exact parity with the trusted run's per-case pass
                # condition: promoted gold cases must re-evaluate to a
                # determinate, evidence-ready outcome.
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_confirmation_outcome_drift",
                    f"样本 {sample.sample_id} 的复评结果未达到可信复验的"
                    "判定与证据完备要求，不能登记医学确认。",
                    http_status=409,
                )

    def _verified_rule_mapping_identity(
        self,
        rules: Sequence[MonitoringRuleDefinition],
    ) -> str:
        identities: set[tuple[str, str, str, str]] = set()
        for rule in rules:
            missing = [
                field
                for field in _RULE_IDENTITY_FIELDS
                if not str(getattr(rule, field, "") or "").strip()
            ]
            if missing:
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_rule_identity_unverifiable",
                    f"规则 {rule.rule_key} 缺少不可变映射身份（{', '.join(missing)}）；"
                    "自动影子验证样本仅支持来自规则推荐链路的规则。",
                    http_status=409,
                )
            identities.add(
                tuple(
                    str(getattr(rule, field, "")).strip()
                    for field in _RULE_IDENTITY_FIELDS
                )
            )
        if len(identities) != 1:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_rule_identity_unverifiable",
                "影子规则包中的规则未共享同一完整不可变身份四元组"
                "（映射修订、映射内容、能力清单、有效能力哈希）；"
                "请通过规则推荐链路重新确认规则。",
                http_status=409,
            )
        return next(iter(identities))[0]

    def _frozen_batch(
        self,
        project_id: str,
        batch_id: str,
        *,
        rules: Sequence[MonitoringRuleDefinition],
        mapping_revision: str,
    ):
        try:
            batch = self.batch_repository.get_batch(batch_id)
        except RecordNotFoundError as exc:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_batch_not_found",
                "当前项目未找到该冻结批次。",
                http_status=404,
            ) from exc
        if batch.project_id != project_id:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_batch_not_found",
                "当前项目未找到该冻结批次。",
                http_status=404,
            )
        if batch.state != "frozen":
            raise MonitoringShadowSampleError(
                "monitoring_shadow_batch_not_frozen",
                f"批次当前状态为 {batch.state}，"
                "自动影子验证样本只能来自已冻结批次。",
                http_status=409,
            )
        drift_message = (
            "冻结批次的映射身份与规则不可变身份不一致；"
            "请重新冻结批次或通过推荐链路重新确认规则。"
        )
        if str(batch.active_mapping_revision or "") != mapping_revision:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_mapping_drift",
                drift_message,
                http_status=409,
            )
        try:
            contract = self.batch_repository.load_frozen_mapping_contract(
                batch_id
            )
        except MonitoringBatchRepositoryError as exc:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_mapping_drift",
                drift_message,
                http_status=409,
            ) from exc
        for rule in rules:
            if (
                contract.mapping_revision != rule.mapping_revision
                or contract.mapping_content_sha256
                != rule.mapping_content_sha256
                or contract.capability_manifest_sha256
                != rule.capability_manifest_sha256
                or contract.effective_capabilities_sha256
                != rule.effective_capabilities_sha256
            ):
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_mapping_drift",
                    drift_message,
                    http_status=409,
                )
        return batch

    def _batch_source(
        self,
        project_id: str,
        batch: DiffReadyBatch,
    ) -> _BatchSource:
        bindings = tuple(batch.source_bindings)
        if len(bindings) != 1:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_source_ambiguous",
                "冻结批次绑定的来源文件不唯一，无法自动确定验证样本来源。",
                http_status=409,
            )
        source_entry_id, content_sha256 = bindings[0]
        entry = self.rule_authoring_service._usable_source(
            project_id,
            source_entry_id,
            source_kind="edc_data_listing",
        )
        if (
            not isinstance(content_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
            or not isinstance(entry.content_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", entry.content_hash) is None
            or entry.content_hash != content_sha256
        ):
            raise MonitoringShadowSampleError(
                "monitoring_shadow_source_drift",
                "冻结批次绑定的来源文件内容已变化，请重新登记并冻结批次。",
                http_status=409,
            )
        summary = self.batch_repository.batch_summary(batch.batch_id)
        registrations = [
            item
            for item in summary["sources"]
            if item["source_entry_id"] == source_entry_id
            and isinstance(item["content_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", item["content_sha256"])
            is not None
            and item["content_sha256"] == content_sha256
        ]
        if len(registrations) != 1:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_source_drift",
                "冻结批次的来源登记不唯一，无法自动确定验证样本来源。",
                http_status=409,
            )
        registration = SourceRegistration(**registrations[0])
        return _BatchSource(
            source_entry_id=entry.entry_id,
            source_content_sha256=content_sha256,
            source_revision=monitoring_source_revision(registration),
        )

    def _rows_by_locator(
        self,
        batch: DiffReadyBatch,
        source_content_sha256: str,
    ) -> dict[str, NormalizedRow]:
        rows_by_locator: dict[str, NormalizedRow] = {}
        for row in batch.rows:
            try:
                locator = _canonical_row_locator(
                    row.source_locator,
                    fallback_hash=source_content_sha256,
                )
            except MonitoringGoldCaseAuthorityError as exc:
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_row_locator_invalid",
                    f"冻结批次行缺少规范来源定位：{exc}",
                    http_status=422,
                ) from exc
            if locator in rows_by_locator:
                raise MonitoringShadowSampleError(
                    "monitoring_shadow_row_locator_ambiguous",
                    "冻结批次存在来源定位重复的行，无法自动绑定验证样本。",
                    http_status=409,
                )
            rows_by_locator[locator] = row
        return rows_by_locator

    def _prepare_rule_samples(
        self,
        *,
        project_id: str,
        pack: MonitoringRulePack,
        rule: MonitoringRuleDefinition,
        batch: DiffReadyBatch,
        batch_record: Any,
        source: _BatchSource,
        rows_by_subject: Mapping[str, Mapping[str, Sequence[NormalizedRow]]],
        rows_by_locator: Mapping[str, NormalizedRow],
    ) -> list[ShadowProvisionalSample]:
        try:
            lineage = validate_rule_field_lineage(
                field_lineage=dict(rule.field_lineage),
                preconditions=rule.preconditions,
                trigger_expression=rule.trigger_expression,
                exclusions=rule.exclusions,
                evidence_template=rule.evidence_template,
                required_domains=rule.required_domains,
            )
        except MonitoringProtocolRuleError as exc:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_rule_not_samplable",
                f"规则 {rule.rule_key} 的字段血缘不可用，"
                "不能自动生成影子验证样本。",
                http_status=422,
            ) from exc
        current_fields, related_domains = _current_predicate_fields(rule)
        anchor_domain = _anchor_domain(
            rule,
            lineage,
            current_fields=current_fields,
            related_domains=related_domains,
        )
        if not anchor_domain:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_rule_not_samplable",
                f"规则 {rule.rule_key} 无法确定当前记录锚定数据域，"
                "不能自动生成影子验证样本。",
                http_status=422,
            )
        case_domains = tuple(
            sorted(
                {str(domain).upper() for domain in rule.required_domains}
                | related_domains
            )
        )
        batch_revision = monitoring_batch_revision(
            batch_record.batch_id,
            batch_record.version,
        )

        buckets: dict[str, ShadowProvisionalSample] = {}
        for subject_id in sorted(rows_by_subject):
            subject_domains = rows_by_subject[subject_id]
            for current_row in subject_domains.get(anchor_domain, ()):
                candidate = self._evaluate_candidate(
                    pack=pack,
                    rule=rule,
                    batch=batch,
                    lineage=lineage,
                    subject_id=subject_id,
                    anchor_domain=anchor_domain,
                    current_row=current_row,
                    subject_domains=subject_domains,
                    current_fields=current_fields,
                    related_domains=related_domains,
                    case_domains=case_domains,
                )
                if candidate is None or candidate.bucket in buckets:
                    continue
                try:
                    sample = self._build_sample(
                        project_id=project_id,
                        candidate=candidate,
                        source=source,
                        batch_revision=batch_revision,
                        rows_by_locator=rows_by_locator,
                    )
                except _UnbindableCandidate:
                    continue
                buckets[candidate.bucket] = sample
                if len(buckets) == 4:
                    break
            if len(buckets) == 4:
                break
        missing = [
            bucket
            for bucket in ("positive", "negative", "boundary", "diagnostic")
            if bucket not in buckets
        ]
        if missing:
            raise MonitoringShadowSampleError(
                "monitoring_shadow_sample_buckets_incomplete",
                f"规则 {rule.rule_key} 在冻结批次中缺少样本类别："
                f"{', '.join(missing)}；"
                "请使用覆盖更完整的冻结批次。",
                http_status=422,
            )
        return [buckets[bucket] for bucket in sorted(buckets)]

    def _evaluate_candidate(
        self,
        *,
        pack: MonitoringRulePack,
        rule: MonitoringRuleDefinition,
        batch: DiffReadyBatch,
        lineage: Mapping[str, Mapping[str, Any]],
        subject_id: str,
        anchor_domain: str,
        current_row: NormalizedRow,
        subject_domains: Mapping[str, Sequence[NormalizedRow]],
        current_fields: set[str],
        related_domains: set[str],
        case_domains: tuple[str, ...],
    ) -> _EvaluatedCandidate | None:
        record, _materialization_diagnostics = _materialize_record(
            batch=batch,
            rule_pack_id=pack.rule_pack_id,
            rule=rule,
            lineage=lineage,
            subject_id=subject_id,
            anchor_domain=anchor_domain,
            current_row=current_row,
            subject_domains=subject_domains,
            current_fields=current_fields,
            related_domains=related_domains,
        )
        related_records = {
            domain: [
                _record_from_row(batch, row)
                for row in subject_domains.get(domain, ())
            ]
            for domain in case_domains
        }
        observed_domains = tuple(
            sorted(str(domain).upper() for domain in rule.required_domains)
        )
        try:
            evaluation = self.protocol_rule_service.evaluate_record(
                rule,
                record,
                observed_domains=observed_domains,
                related_records=related_records,
                allow_non_enabled=True,
                validation_mode="shadow",
            )
        except (MonitoringProtocolRuleError, RuleEvaluationNotSupported):
            return None
        evaluation_state = str(
            evaluation.evidence.get("evaluation_state") or ""
        ).strip().lower()
        diagnostic_code = str(
            evaluation.evidence.get("diagnostic_code") or ""
        ).strip().lower()
        bucket = ""
        if evaluation.matched:
            bucket = "positive"
        elif evaluation_state == "false" and not evaluation.preconditions_met:
            bucket = "negative"
        elif evaluation_state == "false" and evaluation.preconditions_met:
            bucket = "boundary"
        elif evaluation_state == "indeterminate" and diagnostic_code:
            bucket = "diagnostic"
        if not bucket:
            return None
        return _EvaluatedCandidate(
            rule=rule,
            subject_id=subject_id,
            business_key=current_row.business_key,
            bucket=bucket,
            matched=evaluation.matched,
            evaluation_state=evaluation_state,
            diagnostic_code=diagnostic_code,
            input_record=record,
            related_records=related_records,
            observed_domains=observed_domains,
        )

    def _build_sample(
        self,
        *,
        project_id: str,
        candidate: _EvaluatedCandidate,
        source: _BatchSource,
        batch_revision: str,
        rows_by_locator: Mapping[str, NormalizedRow],
    ) -> ShadowProvisionalSample:
        rule = candidate.rule
        records = self._case_records(
            candidate,
            rows_by_locator,
            source_content_sha256=source.source_content_sha256,
        )
        evidence_locators = tuple(
            sorted(
                {
                    locator
                    for record in records.values()
                    for locator in record["__source_locator__"]
                }
            )
        )
        bindings = self._source_row_bindings(
            records,
            rows_by_locator=rows_by_locator,
        )
        actual_domains = {
            _canonical_domain(rows_by_locator[locator].domain)
            for locator in evidence_locators
        }
        required_domains = {
            _canonical_domain(domain) for domain in rule.required_domains
        }
        if actual_domains != required_domains:
            raise _UnbindableCandidate(
                f"candidate rows cover {sorted(actual_domains)} but the rule "
                f"requires {sorted(required_domains)}"
            )
        evidence_summary = (
            f"服务器从冻结批次 {batch_revision} 中按业务键 "
            f"{candidate.business_key} 自动选取的"
            f"{_BUCKET_LABELS[candidate.bucket]}影子样本；"
            "记录的实际评估结果尚待医学确认。"
        )
        case_label = (
            f"auto:{rule.rule_key}:{candidate.subject_id}:"
            f"{candidate.business_key}"
        )
        return ShadowProvisionalSample.create(
            project_id=project_id,
            rule_key=rule.rule_key,
            rule_revision_id=rule.rule_revision_id,
            bucket=candidate.bucket,
            case_label=case_label,
            business_key=candidate.business_key,
            input_record=records["current"],
            related_records=self._related_case_records(records),
            observed_domains=candidate.observed_domains,
            evidence_locators=evidence_locators,
            source_row_bindings=bindings,
            actual_matched=candidate.matched,
            actual_evaluation_state=candidate.evaluation_state,
            actual_diagnostic_code=candidate.diagnostic_code,
            evidence_summary=evidence_summary,
        )

    def _case_records(
        self,
        candidate: _EvaluatedCandidate,
        rows_by_locator: Mapping[str, NormalizedRow],
        *,
        source_content_sha256: str,
    ) -> dict[str, dict[str, Any]]:
        raw_records: dict[str, dict[str, Any]] = {
            "current": candidate.input_record,
        }
        for domain, related in sorted(candidate.related_records.items()):
            for index, record in enumerate(related):
                raw_records[f"related:{domain}:{index}"] = record
        records: dict[str, dict[str, Any]] = {}
        for role, record in raw_records.items():
            converted = dict(record)
            locators: list[str] = []
            for item in record.get("__source_locator__") or ():
                try:
                    locator = (
                        item
                        if isinstance(item, str)
                        else _canonical_row_locator(
                            item,
                            fallback_hash=source_content_sha256,
                        )
                    )
                except MonitoringGoldCaseAuthorityError as exc:
                    raise _UnbindableCandidate(str(exc)) from exc
                if locator not in locators:
                    locators.append(locator)
            unknown = [
                locator
                for locator in locators
                if locator not in rows_by_locator
            ]
            if not locators or unknown:
                raise _UnbindableCandidate(
                    f"{role} record locators do not resolve to frozen rows"
                )
            converted["__source_locator__"] = locators
            records[role] = converted
        return records

    @staticmethod
    def _related_case_records(
        records: Mapping[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        related: dict[str, list[dict[str, Any]]] = {}
        for role, record in sorted(records.items()):
            if not role.startswith("related:"):
                continue
            _prefix, domain, _index = role.split(":", 2)
            related.setdefault(domain, []).append(record)
        return related

    @staticmethod
    def _source_row_bindings(
        records: Mapping[str, dict[str, Any]],
        *,
        rows_by_locator: Mapping[str, NormalizedRow],
    ) -> tuple[RuleGoldSourceRowBinding, ...]:
        roles_by_locator: dict[str, list[str]] = {}
        for role, record in records.items():
            for locator in record["__source_locator__"]:
                roles_by_locator.setdefault(locator, []).append(role)
        bindings: list[RuleGoldSourceRowBinding] = []
        for locator in sorted(roles_by_locator):
            row = rows_by_locator[locator]
            roles = sorted(roles_by_locator[locator])
            field_bindings: list[RuleGoldRecordFieldBinding] = []
            for role in roles:
                record = records[role]
                derived_fields = set(
                    (record.get("__auditable_base_values__") or {}).keys()
                )
                for field in sorted(record):
                    if field.startswith("__") or field in derived_fields:
                        continue
                    if (
                        field not in row.data
                        or row.data[field] != record[field]
                    ):
                        raise _UnbindableCandidate(
                            f"{role} record field {field} does not match its "
                            f"frozen row {row.business_key}"
                        )
                    field_bindings.append(
                        RuleGoldRecordFieldBinding.create(
                            record_role=role,
                            record_field=field,
                            source_field=field,
                        )
                    )
            bindings.append(
                RuleGoldSourceRowBinding.create(
                    business_key=row.business_key,
                    domain=row.domain,
                    source_locator=locator,
                    row_fingerprint=row.row_fingerprint,
                    record_roles=roles,
                    field_bindings=field_bindings,
                )
            )
        return tuple(bindings)

    @staticmethod
    def _now_text() -> str:
        return datetime.now(timezone.utc).isoformat()
