from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from services.api.app.monitoring_real_loop_readiness import (
    REAL_LOOP_MODEL_ROUTES,
    REAL_LOOP_PROJECT_IDS,
    REAL_LOOP_ROLES,
    REAL_LOOP_TASK_TYPES,
    RealLoopBatch,
    RealLoopGateInput,
    RealLoopReadinessError,
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


def batch_rows(project_id: str, count: int = 2) -> tuple[RealLoopBatch, ...]:
    return tuple(
        RealLoopBatch(
            batch_ref=f"listing:{project_id}:batch-{index}",
            snapshot_date=f"2026-0{index + 1}-20",
            listing_sha256=digest(f"listing-{project_id}-batch-{index}"),
            listing_class="raw_full_snapshot",
            source_status="confirmed",
            full_snapshot_proven=True,
        )
        for index in range(count)
    )


def complete_sources(batch_count: int = 2) -> tuple[RealLoopSource, ...]:
    rows = []
    for project_id in REAL_LOOP_PROJECT_IDS:
        batches = batch_rows(project_id, batch_count)
        rows.append(
            RealLoopSource(
                project_id=project_id,
                protocol_ref=f"protocol:{project_id}:v1",
                protocol_sha256=digest(f"protocol:{project_id}"),
                listing_ref=batches[0].batch_ref if batches else "listing:missing",
                listing_sha256=(
                    batches[0].listing_sha256
                    if batches
                    else digest(f"listing-{project_id}-missing")
                ),
                listing_class="raw_full_snapshot",
                source_status="confirmed",
                batch_count=batch_count,
                batches=batches,
            )
        )
    return tuple(rows)


def complete_scenarios() -> tuple[RealLoopScenario, ...]:
    rows = []
    index = 0
    prompts = {row.scenario_id: row for row in build_real_loop_prompt_manifest()}
    for project_id in REAL_LOOP_PROJECT_IDS:
        for role in REAL_LOOP_ROLES:
            for task_type in REAL_LOOP_TASK_TYPES:
                prompt = prompts[f"{project_id}:{role}:{task_type}"]
                route = tuple(REAL_LOOP_MODEL_ROUTES)[
                    index % len(REAL_LOOP_MODEL_ROUTES)
                ]
                rows.append(
                    RealLoopScenario(
                        scenario_id=prompt.scenario_id,
                        project_id=project_id,
                        role=role,
                        task_type=task_type,
                        prompt_sha256=prompt.prompt_sha256,
                        model_route=route,
                        prompt_ref=prompt.prompt_id,
                    )
                )
                index += 1
    return tuple(rows)


def prompt_manifest():
    return build_real_loop_prompt_manifest()


def ready_gates() -> RealLoopGateInput:
    return RealLoopGateInput(
        b6_approved=True,
        approved_input_ready=True,
        source_token_revalidated=True,
        aggregate_cas_complete=True,
        runtime_identity_verified=True,
        browser_acceptance_complete=True,
        scientific_acceptance_complete=True,
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


class RealLoopReadinessTests(unittest.TestCase):
    def test_complete_manifest_is_execution_ready_but_never_grants_authority(
        self,
    ) -> None:
        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), ready_gates(), prompt_manifest()
        )

        self.assertEqual("ready_for_controlled_execution", report.status)
        self.assertTrue(report.execution_ready)
        self.assertTrue(report.acceptance_complete)
        self.assertEqual(5, report.project_count)
        self.assertEqual(40, report.scenario_count)
        self.assertFalse(report.runtime_activation_permitted)
        self.assertFalse(report.provider_call_permitted)
        self.assertFalse(report.write_permitted)
        self.assertEqual((), report.issues)
        self.assertEqual(
            (
                ("b6_approved", "b" * 64),
                ("approved_input_ready", "c" * 64),
                ("source_token_revalidated", "d" * 64),
                ("aggregate_cas_complete", "e" * 64),
                ("runtime_identity_verified", "f" * 64),
            ),
            report.upstream_gate_evidence_sha256,
        )
        self.assertEqual(
            (
                ("b6_approved", "ref:b6"),
                ("approved_input_ready", "ref:approved-input"),
                ("source_token_revalidated", "ref:source-token"),
                ("aggregate_cas_complete", "ref:aggregate-cas"),
                ("runtime_identity_verified", "ref:runtime-identity"),
            ),
            report.upstream_gate_evidence_refs,
        )

    def test_report_rejects_non_boolean_readiness_and_authority_flags(self) -> None:
        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), ready_gates(), prompt_manifest()
        )

        with self.assertRaisesRegex(RealLoopReadinessError, "strict boolean"):
            replace(report, execution_ready="true")
        with self.assertRaisesRegex(RealLoopReadinessError, "strict boolean"):
            replace(report, provider_call_permitted="false")
        with self.assertRaisesRegex(
            RealLoopReadinessError, "requires every upstream gate evidence hash"
        ):
            replace(report, upstream_gate_evidence_sha256=())
        with self.assertRaisesRegex(
            RealLoopReadinessError, "requires every upstream gate evidence ref"
        ):
            replace(report, upstream_gate_evidence_refs=())

    def test_current_source_classes_and_gate_state_are_blocked(self) -> None:
        sources = (
            RealLoopSource(
                "proj_rux_03_002",
                "protocol:rux:v1",
                digest("rux-protocol"),
                "listing:rux:raw",
                digest("rux-listing"),
                "raw_snapshot_with_dimension_defect",
                "candidate",
                1,
                batch_rows("proj_rux_03_002", 1),
            ),
            RealLoopSource(
                "proj_mgk10_sar_real",
                "protocol:mgk10:v2",
                digest("mgk10-protocol"),
                "listing:mgk10:locked",
                digest("mgk10-listing"),
                "raw_locked_snapshot",
                "confirmed",
                1,
                batch_rows("proj_mgk10_sar_real", 1),
            ),
            RealLoopSource(
                "proj_my009_uc",
                "protocol:my009:v3",
                digest("my009-protocol"),
                "listing:my009:restored",
                digest("my009-listing"),
                "restored_transitional",
                "candidate",
                1,
                batch_rows("proj_my009_uc", 1),
            ),
        )
        gates = RealLoopGateInput(False, False, False, False, False)

        report = assess_real_loop_readiness(
            sources, complete_scenarios(), gates, prompt_manifest()
        )

        codes = {item.code for item in report.issues}
        self.assertEqual("blocked", report.status)
        self.assertFalse(report.execution_ready)
        self.assertIn(RealLoopIssueCode.SOURCE_NOT_ELIGIBLE, codes)
        self.assertIn(RealLoopIssueCode.BATCH_COVERAGE_INSUFFICIENT, codes)
        self.assertIn(RealLoopIssueCode.GATE_NOT_READY, codes)
        self.assertFalse(report.write_permitted)

    def test_preflight_can_enter_before_post_run_acceptance(self) -> None:
        gates = RealLoopGateInput(
            b6_approved=True,
            approved_input_ready=True,
            source_token_revalidated=True,
            aggregate_cas_complete=True,
            runtime_identity_verified=True,
            browser_acceptance_complete=False,
            scientific_acceptance_complete=False,
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
        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertEqual("ready_for_controlled_execution", report.status)
        self.assertTrue(report.execution_ready)
        self.assertFalse(report.acceptance_complete)

    def test_string_acceptance_flags_cannot_be_coerced_to_complete(self) -> None:
        gates = replace(
            ready_gates(),
            browser_acceptance_complete="false",  # type: ignore[arg-type]
            scientific_acceptance_complete="false",  # type: ignore[arg-type]
        )

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.GATE_VALUE_INVALID,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.acceptance_complete)
        self.assertFalse(report.execution_ready)

    def test_missing_generalization_evidence_blocks_controlled_readiness(self) -> None:
        gates = RealLoopGateInput(
            b6_approved=True,
            approved_input_ready=True,
            source_token_revalidated=True,
            aggregate_cas_complete=True,
            runtime_identity_verified=True,
            browser_acceptance_complete=False,
            scientific_acceptance_complete=False,
        )
        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        codes = {item.code for item in report.issues}
        self.assertIn(RealLoopIssueCode.GATE_NOT_READY, codes)
        self.assertIn(RealLoopIssueCode.GENERALIZATION_EVIDENCE_INVALID, codes)
        self.assertFalse(report.execution_ready)

    def test_generalization_evidence_hash_must_be_lowercase_sha256(self) -> None:
        gates = replace(
            ready_gates(),
            generalization_evidence_sha256="not-a-hash",
        )
        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.GENERALIZATION_EVIDENCE_INVALID,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_readiness_digests_reject_noncanonical_shapes_without_rewriting(self) -> None:
        padded_source = replace(
            complete_sources()[0],
            protocol_sha256="a" * 64 + " ",
        )
        source_report = assess_real_loop_readiness(
            (padded_source, *complete_sources()[1:]),
            complete_scenarios(),
            ready_gates(),
            prompt_manifest(),
        )
        self.assertIn(
            RealLoopIssueCode.SOURCE_HASH_INVALID,
            {item.code for item in source_report.issues},
        )

        padded_prompt = replace(
            complete_scenarios()[0],
            prompt_sha256="b" * 64 + " ",
        )
        prompt_report = assess_real_loop_readiness(
            complete_sources(),
            (padded_prompt, *complete_scenarios()[1:]),
            ready_gates(),
            prompt_manifest(),
        )
        self.assertIn(
            RealLoopIssueCode.SOURCE_HASH_INVALID,
            {item.code for item in prompt_report.issues},
        )

        gate_report = assess_real_loop_readiness(
            complete_sources(),
            complete_scenarios(),
            replace(
                ready_gates(),
                generalization_evidence_sha256="A" * 64,
                semantics_binding_sha256="B" * 64,
                b6_evidence_sha256="C" * 64,
            ),
            prompt_manifest(),
        )
        codes = {item.code for item in gate_report.issues}
        self.assertIn(RealLoopIssueCode.GENERALIZATION_EVIDENCE_INVALID, codes)
        self.assertIn(RealLoopIssueCode.SEMANTICS_BINDING_INVALID, codes)
        self.assertIn(RealLoopIssueCode.UPSTREAM_EVIDENCE_HASH_INVALID, codes)
        self.assertEqual("", gate_report.generalization_evidence_sha256)
        self.assertEqual("", gate_report.semantics_binding_sha256)

    def test_identity_bound_semantics_are_required_for_proven_upstream_gates(self) -> None:
        gates = replace(
            ready_gates(),
            semantics_binding_matched=False,
            semantics_binding_sha256="",
        )

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.SEMANTICS_BINDING_NOT_READY,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_semantics_binding_hash_is_strict_and_propagated(self) -> None:
        invalid = replace(ready_gates(), semantics_binding_sha256="not-a-hash")
        invalid_report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), invalid, prompt_manifest()
        )
        self.assertIn(
            RealLoopIssueCode.SEMANTICS_BINDING_INVALID,
            {item.code for item in invalid_report.issues},
        )

        valid_report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), ready_gates(), prompt_manifest()
        )
        self.assertTrue(valid_report.semantics_binding_matched)
        self.assertEqual("1" * 64, valid_report.semantics_binding_sha256)

    def test_true_upstream_gate_without_evidence_hash_blocks_readiness(self) -> None:
        gates = replace(ready_gates(), source_token_evidence_sha256="")

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.UPSTREAM_EVIDENCE_HASH_INVALID,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_reused_upstream_evidence_hash_blocks_readiness(self) -> None:
        gates = replace(
            ready_gates(),
            aggregate_cas_evidence_sha256="b" * 64,
        )

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.UPSTREAM_EVIDENCE_HASH_DUPLICATE,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_true_upstream_gate_without_evidence_ref_blocks_readiness(self) -> None:
        gates = replace(ready_gates(), aggregate_cas_evidence_ref="")

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.UPSTREAM_EVIDENCE_PAIR_INCOMPLETE,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_reused_upstream_evidence_ref_blocks_readiness(self) -> None:
        gates = replace(
            ready_gates(),
            runtime_identity_evidence_ref="ref:b6",
        )

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.UPSTREAM_EVIDENCE_REF_DUPLICATE,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_string_prerequisite_flags_cannot_be_coerced_to_ready(self) -> None:
        gates = replace(
            ready_gates(),
            b6_approved="true",  # type: ignore[arg-type]
        )

        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), gates, prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.GATE_VALUE_INVALID,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_failed_scenario_blocks_replay(self) -> None:
        scenarios = list(complete_scenarios())
        failed = scenarios[0]
        scenarios[0] = RealLoopScenario(
            scenario_id=failed.scenario_id,
            project_id=failed.project_id,
            role=failed.role,
            task_type=failed.task_type,
            prompt_sha256=failed.prompt_sha256,
            model_route=failed.model_route,
            run_status="failed",
            prompt_ref=failed.prompt_ref,
        )
        report = assess_real_loop_readiness(
            complete_sources(), scenarios, ready_gates(), prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.SCENARIO_EXECUTION_FAILED,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_missing_role_task_and_duplicate_prompt_fail_closed(self) -> None:
        scenarios = list(complete_scenarios())
        scenarios.pop()
        scenarios[0] = RealLoopScenario(
            scenario_id=scenarios[0].scenario_id,
            project_id=scenarios[0].project_id,
            role=scenarios[0].role,
            task_type=scenarios[0].task_type,
            prompt_sha256=scenarios[1].prompt_sha256,
            model_route=scenarios[0].model_route,
            prompt_ref=scenarios[0].prompt_ref,
        )
        report = assess_real_loop_readiness(
            complete_sources(), scenarios, ready_gates(), prompt_manifest()
        )

        codes = {item.code for item in report.issues}
        self.assertIn(RealLoopIssueCode.PROMPT_HASH_DUPLICATE, codes)
        self.assertIn(RealLoopIssueCode.TASK_COVERAGE_MISSING, codes)
        self.assertFalse(report.execution_ready)

    def test_scalar_batch_count_without_explicit_rows_fails_closed(self) -> None:
        sources = list(complete_sources())
        sources[0] = replace(sources[0], batches=())

        report = assess_real_loop_readiness(
            sources, complete_scenarios(), ready_gates(), prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_duplicate_batch_identity_fails_closed(self) -> None:
        sources = list(complete_sources())
        first = sources[0]
        sources[0] = replace(
            first, batches=(first.batches[0], first.batches[0]), batch_count=2
        )

        report = assess_real_loop_readiness(
            sources, complete_scenarios(), ready_gates(), prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.BATCH_DUPLICATE,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_malformed_scalar_batch_count_fails_closed(self) -> None:
        sources = list(complete_sources())
        sources[0] = replace(sources[0], batch_count="2")

        report = assess_real_loop_readiness(
            sources, complete_scenarios(), ready_gates(), prompt_manifest()
        )

        self.assertIn(
            RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
            {item.code for item in report.issues},
        )
        self.assertFalse(report.execution_ready)

    def test_report_is_deterministic_under_input_order(self) -> None:
        sources = complete_sources()
        scenarios = complete_scenarios()
        first = assess_real_loop_readiness(
            sources, scenarios, ready_gates(), prompt_manifest()
        )
        second = assess_real_loop_readiness(
            tuple(reversed(sources)),
            tuple(reversed(scenarios)),
            ready_gates(),
            tuple(reversed(prompt_manifest())),
        )

        self.assertEqual(first.report_sha256, second.report_sha256)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_prompt_manifest_is_required_for_readiness(self) -> None:
        report = assess_real_loop_readiness(
            complete_sources(), complete_scenarios(), ready_gates()
        )

        self.assertIn(
            RealLoopIssueCode.PROMPT_MANIFEST_MISSING,
            {issue.code for issue in report.issues},
        )
        self.assertFalse(report.execution_ready)


if __name__ == "__main__":
    unittest.main()
