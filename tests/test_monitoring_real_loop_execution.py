from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from services.api.app.monitoring_real_loop_execution import (
    RealLoopExecutionError,
    RealLoopExecutionIssueCode,
    RealLoopScenarioEvidence,
    assess_real_loop_execution,
)
from services.api.app.monitoring_real_loop_readiness import (
    REAL_LOOP_MODEL_ROUTES,
    REAL_LOOP_PROJECT_IDS,
    REAL_LOOP_ROLES,
    REAL_LOOP_TASK_TYPES,
    RealLoopBatch,
    RealLoopGateInput,
    RealLoopIssue,
    RealLoopIssueCode,
    RealLoopScenario,
    RealLoopSource,
    assess_real_loop_readiness,
)
from services.api.app.monitoring_real_loop_prompt_manifest import (
    build_real_loop_prompt_manifest,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sources() -> tuple[RealLoopSource, ...]:
    rows = []
    for project_id in REAL_LOOP_PROJECT_IDS:
        batches = tuple(
            RealLoopBatch(
                batch_ref=f"listing:{project_id}:batch-{index}",
                snapshot_date=f"2026-0{index + 1}-20",
                listing_sha256=digest(f"listing-{project_id}-batch-{index}"),
                listing_class="raw_full_snapshot",
                source_status="confirmed",
                full_snapshot_proven=True,
            )
            for index in range(2)
        )
        rows.append(
            RealLoopSource(
                project_id=project_id,
                protocol_ref=f"protocol:{project_id}:v1",
                protocol_sha256=digest(f"protocol-{project_id}"),
                listing_ref=batches[0].batch_ref,
                listing_sha256=batches[0].listing_sha256,
                listing_class="raw_full_snapshot",
                source_status="confirmed",
                batch_count=2,
                batches=batches,
            )
        )
    return tuple(rows)


def scenarios(run_status: str = "not_run") -> tuple[RealLoopScenario, ...]:
    rows = []
    index = 0
    routes = tuple(REAL_LOOP_MODEL_ROUTES)
    prompts = {row.scenario_id: row for row in build_real_loop_prompt_manifest()}
    for project_id in REAL_LOOP_PROJECT_IDS:
        for role in REAL_LOOP_ROLES:
            for task_type in REAL_LOOP_TASK_TYPES:
                prompt = prompts[f"{project_id}:{role}:{task_type}"]
                rows.append(
                    RealLoopScenario(
                        scenario_id=prompt.scenario_id,
                        project_id=project_id,
                        role=role,
                        task_type=task_type,
                        prompt_sha256=prompt.prompt_sha256,
                        model_route=routes[index % len(routes)],
                        run_status=run_status,
                        prompt_ref=prompt.prompt_id,
                    )
                )
                index += 1
    return tuple(rows)


def gates() -> RealLoopGateInput:
    return RealLoopGateInput(
        b6_approved=True,
        approved_input_ready=True,
        source_token_revalidated=True,
        aggregate_cas_complete=True,
        runtime_identity_verified=True,
        generalization_evidence_complete=True,
        generalization_evidence_sha256="a" * 64,
        semantics_binding_matched=True,
        semantics_binding_sha256="1" * 64,
        b6_evidence_sha256="b" * 64,
        approved_input_evidence_sha256="c" * 64,
        source_token_evidence_sha256="d" * 64,
        aggregate_cas_evidence_sha256="e" * 64,
        runtime_identity_evidence_sha256="f" * 64,
        b6_evidence_ref="ref:b6",
        approved_input_evidence_ref="ref:approved-input",
        source_token_evidence_ref="ref:source-token",
        aggregate_cas_evidence_ref="ref:aggregate-cas",
        runtime_identity_evidence_ref="ref:runtime-identity",
    )


def prompt_manifest():
    return build_real_loop_prompt_manifest()


def evidence_rows(
    planned: tuple[RealLoopScenario, ...], *, run_status: str = "passed"
) -> tuple[RealLoopScenarioEvidence, ...]:
    rows = []
    for index, scenario in enumerate(planned):
        night = scenario.model_route == "pi/alibaba/qwen3.8-max-preview"
        start = "2026-08-02T23:00:00+08:00" if night else "2026-08-02T08:00:00+08:00"
        end = "2026-08-02T23:01:00+08:00" if night else "2026-08-02T08:01:00+08:00"
        rows.append(
            RealLoopScenarioEvidence(
                scenario_id=scenario.scenario_id,
                project_id=scenario.project_id,
                role=scenario.role,
                task_type=scenario.task_type,
                prompt_sha256=scenario.prompt_sha256,
                model_route=scenario.model_route,
                run_status=run_status,
                started_at=start,
                ended_at=end,
                batch_ref=f"listing:{scenario.project_id}:batch-1",
                output_ref=f"output:{index}",
                output_sha256=digest(f"output-{index}"),
                evidence_refs=(f"source:{scenario.project_id}:row-{index}",),
                uncertainty_state="confirmed" if index % 2 == 0 else "uncertain",
                failure_detail="provider timeout" if run_status != "passed" else "",
                prompt_ref=scenario.prompt_ref,
            )
        )
    return tuple(rows)


class RealLoopExecutionTests(unittest.TestCase):
    def ready_report(self, planned: tuple[RealLoopScenario, ...]):
        return assess_real_loop_readiness(
            sources(), planned, gates(), prompt_manifest()
        )

    def test_complete_execution_is_reviewable_but_never_authorized(self) -> None:
        planned = scenarios()
        readiness = self.ready_report(planned)
        report = assess_real_loop_execution(readiness, planned, evidence_rows(planned))

        self.assertEqual("accepted_for_medical_review", report.status)
        self.assertTrue(report.execution_evidence_complete)
        self.assertEqual(40, report.scenario_count)
        self.assertEqual(40, report.passed_count)
        self.assertEqual(0, report.failed_count)
        self.assertEqual(0, report.blocked_count)
        self.assertEqual((), report.issues)
        self.assertFalse(report.medical_confirmation_permitted)
        self.assertFalse(report.runtime_write_permitted)
        self.assertEqual(readiness.report_sha256, report.readiness_report_sha256)
        self.assertEqual(
            readiness.generalization_evidence_sha256,
            report.generalization_evidence_sha256,
        )
        self.assertEqual(
            readiness.semantics_binding_sha256,
            report.semantics_binding_sha256,
        )

    def test_report_rejects_non_boolean_completion_and_authority_flags(self) -> None:
        planned = scenarios()
        readiness = self.ready_report(planned)
        report = assess_real_loop_execution(readiness, planned, evidence_rows(planned))

        with self.assertRaisesRegex(RealLoopExecutionError, "strict boolean"):
            replace(report, execution_evidence_complete="true")
        with self.assertRaisesRegex(RealLoopExecutionError, "strict boolean"):
            replace(report, runtime_write_permitted="false")

    def test_blocked_preflight_cannot_be_hidden_by_complete_outputs(self) -> None:
        planned = scenarios()
        blocked_readiness = assess_real_loop_readiness(
            sources(),
            planned,
            RealLoopGateInput(False, False, False, False, False),
            prompt_manifest(),
        )
        report = assess_real_loop_execution(
            blocked_readiness, planned, evidence_rows(planned)
        )

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopExecutionIssueCode.READINESS_NOT_READY,
            {issue.code for issue in report.issues},
        )

    def test_identity_time_window_and_traceability_are_checked(self) -> None:
        planned = scenarios()
        rows = list(evidence_rows(planned))
        first = rows[0]
        rows[0] = RealLoopScenarioEvidence(
            scenario_id=first.scenario_id,
            project_id=first.project_id,
            role=first.role,
            task_type=first.task_type,
            prompt_sha256=digest("wrong-prompt"),
            model_route="pi/opencode-go/deepseek-v4-flash",
            run_status="passed",
            started_at="2026-08-02T23:00:00+08:00",
            ended_at="2026-08-02T23:01:00+08:00",
            batch_ref=first.batch_ref,
            output_ref=first.output_ref,
            output_sha256=first.output_sha256,
            evidence_refs=first.evidence_refs,
            uncertainty_state=first.uncertainty_state,
            prompt_ref=first.prompt_ref,
        )
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, tuple(rows)
        )

        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopExecutionIssueCode.SCENARIO_IDENTITY_MISMATCH, codes)
        self.assertIn(RealLoopExecutionIssueCode.TIME_WINDOW_INVALID, codes)

    def test_batch_reference_must_belong_to_readiness_manifest(self) -> None:
        planned = scenarios()
        rows = list(evidence_rows(planned))
        rows[0] = replace(rows[0], batch_ref="listing:proj_rux_03_002:not-in-manifest")

        report = assess_real_loop_execution(
            self.ready_report(planned), planned, tuple(rows)
        )

        self.assertIn(
            RealLoopExecutionIssueCode.BATCH_REFERENCE_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_failed_result_requires_repair_and_failure_detail(self) -> None:
        planned = scenarios()
        failed = list(evidence_rows(planned, run_status="failed"))
        failed[0] = replace(failed[0], output_ref="", output_sha256="")
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, tuple(failed)
        )

        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopExecutionIssueCode.EXECUTION_NOT_PASSED, codes)
        self.assertNotIn(RealLoopExecutionIssueCode.OUTPUT_REFERENCE_MISSING, codes)
        self.assertEqual(40, report.failed_count)
        self.assertFalse(report.execution_evidence_complete)

    def test_execution_cannot_cross_route_window_boundary(self) -> None:
        planned = scenarios()
        rows = list(evidence_rows(planned))
        rows[0] = replace(
            rows[0],
            started_at="2026-08-02T21:59:00+08:00",
            ended_at="2026-08-02T22:01:00+08:00",
        )
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, tuple(rows)
        )

        self.assertIn(
            RealLoopExecutionIssueCode.TIME_WINDOW_INVALID,
            {issue.code for issue in report.issues},
        )

    def test_passed_result_requires_output_hash(self) -> None:
        planned = scenarios()
        rows = list(evidence_rows(planned))
        rows[0] = replace(rows[0], output_sha256="")
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, tuple(rows)
        )

        self.assertIn(
            RealLoopExecutionIssueCode.OUTPUT_HASH_INVALID,
            {issue.code for issue in report.issues},
        )

    def test_missing_and_duplicate_evidence_fail_closed(self) -> None:
        planned = scenarios()
        rows = list(evidence_rows(planned))
        rows.pop()
        rows.append(rows[0])
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, tuple(rows)
        )

        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopExecutionIssueCode.EVIDENCE_DUPLICATE, codes)
        self.assertIn(RealLoopExecutionIssueCode.EVIDENCE_SET_MISMATCH, codes)

    def test_invalid_evidence_identifiers_are_rejected_before_assessment(self) -> None:
        planned = scenarios()
        row = evidence_rows(planned)[0]
        with self.assertRaises(RealLoopExecutionError):
            RealLoopScenarioEvidence(
                **{
                    **row.to_dict(),
                    "output_sha256": "not-a-hash",
                    "evidence_refs": ["source:one"],
                }
            )

    def test_execution_evidence_hashes_reject_noncanonical_shape(self) -> None:
        row = evidence_rows(scenarios())[0]
        cases = (
            ("prompt uppercase", "prompt_sha256", "A" * 64),
            ("prompt padded", "prompt_sha256", "a" * 64 + " "),
            ("prompt nonstring", "prompt_sha256", ["a" * 64]),
            ("output uppercase", "output_sha256", "B" * 64),
            ("output padded", "output_sha256", "b" * 64 + " "),
            ("output nonstring", "output_sha256", {"sha256": "b" * 64}),
        )
        for label, field, value in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    RealLoopExecutionError,
                    "lowercase SHA-256",
                ):
                    RealLoopScenarioEvidence(**{**row.to_dict(), field: value})

    def test_execution_report_chain_hash_rejects_noncanonical_shape(self) -> None:
        planned = scenarios()
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, evidence_rows(planned)
        )
        with self.assertRaisesRegex(
            RealLoopExecutionError,
            "lowercase SHA-256",
        ):
            replace(report, readiness_report_sha256="A" * 64)

    def test_report_is_deterministic_under_input_order(self) -> None:
        planned = scenarios()
        first = assess_real_loop_execution(
            self.ready_report(planned), planned, evidence_rows(planned)
        )
        second = assess_real_loop_execution(
            self.ready_report(tuple(reversed(planned))),
            tuple(reversed(planned)),
            tuple(reversed(evidence_rows(planned))),
        )

        self.assertEqual(first.report_sha256, second.report_sha256)

    def test_missing_upstream_generalization_hash_blocks_execution_evidence(self) -> None:
        planned = scenarios()
        readiness = replace(
            self.ready_report(planned),
            status="blocked",
            execution_ready=False,
            generalization_evidence_sha256="",
            issues=(
                RealLoopIssue(
                    RealLoopIssueCode.GENERALIZATION_EVIDENCE_INVALID,
                    "generalization_evidence_sha256",
                    "fixture deliberately removes the upstream hash",
                ),
            ),
        )

        report = assess_real_loop_execution(readiness, planned, evidence_rows(planned))

        self.assertFalse(report.execution_evidence_complete)
        self.assertIn(
            RealLoopExecutionIssueCode.GENERALIZATION_EVIDENCE_HASH_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("", report.generalization_evidence_sha256)

    def test_missing_upstream_semantics_binding_hash_blocks_execution_evidence(self) -> None:
        planned = scenarios()
        readiness = replace(
            self.ready_report(planned),
            status="blocked",
            execution_ready=False,
            semantics_binding_matched=False,
            semantics_binding_sha256="",
            issues=(
                RealLoopIssue(
                    RealLoopIssueCode.SEMANTICS_BINDING_INVALID,
                    "semantics_binding_sha256",
                    "fixture deliberately removes the upstream semantic binding hash",
                ),
            ),
        )

        report = assess_real_loop_execution(readiness, planned, evidence_rows(planned))

        self.assertFalse(report.execution_evidence_complete)
        self.assertIn(
            RealLoopExecutionIssueCode.SEMANTICS_BINDING_HASH_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("", report.semantics_binding_sha256)

    def test_complete_report_cannot_drop_evidence_chain_hashes(self) -> None:
        planned = scenarios()
        report = assess_real_loop_execution(
            self.ready_report(planned), planned, evidence_rows(planned)
        )

        with self.assertRaisesRegex(
            RealLoopExecutionError,
            "requires readiness and generalization hashes plus a semantics binding hash",
        ):
            replace(report, readiness_report_sha256="")


if __name__ == "__main__":
    unittest.main()
