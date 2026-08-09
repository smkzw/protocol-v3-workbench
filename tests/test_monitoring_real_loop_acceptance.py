from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from services.api.app.monitoring_real_loop_acceptance import (
    ACCEPTANCE_PROJECT_IDS,
    ACCEPTANCE_ROLES,
    ACCEPTANCE_TESTER_IDS,
    ACCEPTANCE_TESTER_ROUTES,
    PLAYWRIGHT_UI_LOGIN,
    RealLoopAcceptanceError,
    RealLoopAcceptanceIssueCode,
    RealLoopAcceptancePrompt,
    RealLoopAcceptanceRun,
    assess_real_loop_acceptance as _assess_real_loop_acceptance,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


EVIDENCE_CHAIN_KWARGS = {
    "readiness_report_sha256": digest("fixture-readiness-report"),
    "generalization_evidence_sha256": digest("fixture-generalization-evidence"),
    "execution_report_sha256": digest("fixture-execution-report"),
    "semantics_binding_sha256": digest("fixture-semantics-binding"),
}


def assess_real_loop_acceptance(*args, **kwargs):
    """Keep legacy fixture calls explicit about their synthetic evidence chain."""

    for key, value in EVIDENCE_CHAIN_KWARGS.items():
        kwargs.setdefault(key, value)
    return _assess_real_loop_acceptance(*args, **kwargs)


def clean_runs() -> tuple[RealLoopAcceptanceRun, ...]:
    rows = []
    index = 0
    route_slots = {
        "pi/opencode-go/deepseek-v4-flash": 0,
        "pi/alibaba/qwen3.8-max-preview": 0,
        "codebuddy": 0,
    }
    for tester_id in ACCEPTANCE_TESTER_IDS:
        route = ACCEPTANCE_TESTER_ROUTES[tester_id]["route"]
        for role in ACCEPTANCE_ROLES:
            for round_number in (1, 2):
                project_id = ACCEPTANCE_PROJECT_IDS[index % len(ACCEPTANCE_PROJECT_IDS)]
                if route == "pi/opencode-go/deepseek-v4-flash":
                    slot = route_slots[route]
                    route_slots[route] += 1
                    start, end = (
                        f"2026-08-02T08:{slot * 2:02d}:00+08:00",
                        f"2026-08-02T08:{slot * 2 + 1:02d}:00+08:00",
                    )
                elif route == "pi/alibaba/qwen3.8-max-preview":
                    slot = route_slots[route]
                    route_slots[route] += 1
                    start, end = (
                        f"2026-08-02T23:{slot * 2:02d}:00+08:00",
                        f"2026-08-02T23:{slot * 2 + 1:02d}:00+08:00",
                    )
                else:
                    slot = route_slots["codebuddy"]
                    route_slots["codebuddy"] += 1
                    start, end = (
                        f"2026-08-03T09:{slot * 2:02d}:00+08:00",
                        f"2026-08-03T09:{slot * 2 + 1:02d}:00+08:00",
                    )
                rows.append(
                    RealLoopAcceptanceRun(
                        run_id=f"run:{tester_id}:{role}:{round_number}",
                        tester_id=tester_id,
                        role=role,
                        project_id=project_id,
                        round_number=round_number,
                        prompt_ref=f"prompt:{tester_id}:{role}:{round_number}",
                        prompt_sha256=digest(
                            f"prompt:{tester_id}:{role}:{project_id}:{round_number}"
                        ),
                        tester_route=route,
                        route_policy_verified=True,
                        route_window_verified=True,
                        started_at=start,
                        ended_at=end,
                        login_mode=PLAYWRIGHT_UI_LOGIN,
                        api_login_used=False,
                        playwright_session_ref=f"pw:{tester_id}:{role}:{round_number}",
                        browser_evidence_ref=f"browser:{tester_id}:{role}:{round_number}",
                        scientific_evidence_ref=f"science:{tester_id}:{role}:{round_number}",
                        run_status="passed",
                    )
                )
                index += 1
    return tuple(rows)


def prompt_manifest(
    rows: tuple[RealLoopAcceptanceRun, ...] | None = None,
) -> tuple[RealLoopAcceptancePrompt, ...]:
    return tuple(
        RealLoopAcceptancePrompt(
            prompt_ref=row.prompt_ref,
            prompt_sha256=row.prompt_sha256,
        )
        for row in (rows or clean_runs())
    )


class RealLoopAcceptanceTests(unittest.TestCase):
    def test_two_clean_rounds_for_each_tester_and_role_are_reviewable(self) -> None:
        report = assess_real_loop_acceptance(
            clean_runs(), prompt_manifest=prompt_manifest()
        )

        self.assertEqual("accepted_for_user_acceptance", report.status)
        self.assertTrue(report.acceptance_complete)
        self.assertEqual(5, report.tester_count)
        self.assertEqual(2, report.role_count)
        self.assertEqual(20, report.run_count)
        self.assertTrue(
            all(streak == 2 for _, streak in report.clean_streak_by_tester_role)
        )
        self.assertEqual((), report.issues)
        self.assertFalse(report.medical_confirmation_permitted)
        self.assertFalse(report.runtime_write_permitted)
        self.assertEqual(
            EVIDENCE_CHAIN_KWARGS["semantics_binding_sha256"],
            report.semantics_binding_sha256,
        )

    def test_report_hash_is_deterministic_under_run_input_order(self) -> None:
        rows = list(clean_runs())
        rows[0] = replace(rows[0], login_mode="api_backend", api_login_used=True)
        rows[-1] = replace(rows[-1], login_mode="api_backend", api_login_used=True)

        first = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest(tuple(rows))
        )
        second = assess_real_loop_acceptance(
            tuple(reversed(rows)),
            prompt_manifest=prompt_manifest(tuple(reversed(rows))),
        )

        self.assertEqual("blocked", first.status)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.report_sha256, second.report_sha256)

    def test_report_rejects_non_boolean_completion_and_authority_flags(self) -> None:
        report = assess_real_loop_acceptance(
            clean_runs(), prompt_manifest=prompt_manifest()
        )

        with self.assertRaisesRegex(RealLoopAcceptanceError, "strict boolean"):
            replace(report, acceptance_complete="true")
        with self.assertRaisesRegex(RealLoopAcceptanceError, "strict boolean"):
            replace(report, runtime_write_permitted="false")

    def test_acceptance_prompt_hash_rejects_noncanonical_shape(self) -> None:
        cases = (
            ("uppercase", "A" * 64),
            ("padded", "a" * 64 + " "),
            ("nonstring", ["a" * 64]),
        )
        for label, value in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    RealLoopAcceptanceError,
                    "lowercase SHA-256",
                ):
                    RealLoopAcceptancePrompt(
                        prompt_ref="prompt:shape",
                        prompt_sha256=value,
                    )

    def test_acceptance_report_chain_hash_rejects_noncanonical_shape(self) -> None:
        report = assess_real_loop_acceptance(
            clean_runs(),
            prompt_manifest=prompt_manifest(),
            **EVIDENCE_CHAIN_KWARGS,
        )
        for field, value in (
            ("readiness_report_sha256", "A" * 64),
            ("execution_report_sha256", "a" * 64 + " "),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    RealLoopAcceptanceError,
                    "lowercase SHA-256",
                ):
                    replace(report, **{field: value})

    def test_acceptance_assessment_does_not_rewrite_chain_hash(self) -> None:
        chain = dict(EVIDENCE_CHAIN_KWARGS)
        chain["readiness_report_sha256"] = "A" * 64
        report = _assess_real_loop_acceptance(
            clean_runs(), prompt_manifest=prompt_manifest(), **chain
        )
        self.assertIn(
            RealLoopAcceptanceIssueCode.EVIDENCE_CHAIN_HASH_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("", report.readiness_report_sha256)

    def test_api_or_backend_login_can_never_pass(self) -> None:
        rows = list(clean_runs())
        rows[0] = replace(rows[0], login_mode="api_backend", api_login_used=True)

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopAcceptanceIssueCode.LOGIN_MODE_INVALID, codes)
        self.assertIn(RealLoopAcceptanceIssueCode.API_LOGIN_USED, codes)
        self.assertIn(RealLoopAcceptanceIssueCode.CLEAN_STREAK_MISSING, codes)
        self.assertEqual("blocked", report.status)

    def test_dirty_p1_round_requires_traceable_repair_and_clean_streak(self) -> None:
        rows = list(clean_runs())
        rows[0] = replace(
            rows[0],
            run_status="failed",
            issue_severities=("P1",),
            issue_refs=("issue:p1",),
            failure_detail="query workflow failed",
            repair_evidence_refs=(),
        )

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopAcceptanceIssueCode.REPAIR_EVIDENCE_MISSING, codes)
        self.assertIn(RealLoopAcceptanceIssueCode.CLEAN_STREAK_MISSING, codes)
        self.assertEqual("blocked", report.status)

    def test_duplicate_prompt_reference_is_not_a_varied_prompt(self) -> None:
        rows = list(clean_runs())
        rows[1] = replace(rows[1], prompt_ref=rows[0].prompt_ref)

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.PROMPT_DUPLICATE,
            {issue.code for issue in report.issues},
        )

    def test_route_window_is_checked_for_pi_day_and_night_routes(self) -> None:
        rows = list(clean_runs())
        rows[0] = replace(
            rows[0],
            started_at="2026-08-02T22:30:00+08:00",
            ended_at="2026-08-02T22:31:00+08:00",
        )
        rows[2] = replace(
            rows[2],
            started_at="2026-08-02T08:30:00+08:00",
            ended_at="2026-08-02T08:31:00+08:00",
        )

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.TIME_WINDOW_INVALID,
            {issue.code for issue in report.issues},
        )

    def test_missing_tester_role_round_fails_closed(self) -> None:
        rows = list(clean_runs())
        rows.pop()

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.COVERAGE_MISSING,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", report.status)

    def test_declared_matrix_cannot_be_narrowed_by_caller(self) -> None:
        report = assess_real_loop_acceptance(
            clean_runs(),
            prompt_manifest=prompt_manifest(),
            expected_testers=ACCEPTANCE_TESTER_IDS[:-1],
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.EXPECTED_TESTER_SET_MISMATCH,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", report.status)

    def test_overlapping_sessions_cannot_count_as_serial(self) -> None:
        rows = list(clean_runs())
        rows[1] = replace(
            rows[1],
            started_at=rows[0].started_at,
            ended_at=rows[0].ended_at,
        )

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.SERIAL_RUN_OVERLAP,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", report.status)

    def test_non_contiguous_rounds_cannot_be_counted_as_consecutive(self) -> None:
        rows = list(clean_runs())
        rows[1] = replace(rows[1], round_number=3)

        report = assess_real_loop_acceptance(
            tuple(rows), prompt_manifest=prompt_manifest()
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.ROUND_SEQUENCE_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", report.status)

    def test_invalid_round_shape_is_rejected_at_boundary(self) -> None:
        with self.assertRaises(RealLoopAcceptanceError):
            RealLoopAcceptanceRun(
                run_id="run:invalid",
                tester_id=ACCEPTANCE_TESTER_IDS[0],
                role=ACCEPTANCE_ROLES[0],
                project_id=ACCEPTANCE_PROJECT_IDS[0],
                round_number=True,
                prompt_ref="prompt:invalid",
                prompt_sha256=digest("prompt"),
                tester_route=ACCEPTANCE_TESTER_ROUTES[ACCEPTANCE_TESTER_IDS[0]][
                    "route"
                ],
                route_policy_verified=True,
                route_window_verified=True,
                started_at="2026-08-02T08:00:00+08:00",
                ended_at="2026-08-02T08:01:00+08:00",
                login_mode=PLAYWRIGHT_UI_LOGIN,
                api_login_used=False,
                playwright_session_ref="pw:invalid",
                browser_evidence_ref="browser:invalid",
                scientific_evidence_ref="science:invalid",
                run_status="passed",
            )

    def test_route_and_login_flags_reject_string_coercion(self) -> None:
        with self.assertRaises(RealLoopAcceptanceError):
            replace(clean_runs()[0], route_policy_verified="false")

    def test_missing_prompt_manifest_fails_closed(self) -> None:
        report = assess_real_loop_acceptance(clean_runs())

        self.assertIn(
            RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_MISSING,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", report.status)

    def test_missing_evidence_chain_hash_fails_closed(self) -> None:
        report = _assess_real_loop_acceptance(
            clean_runs(), prompt_manifest=prompt_manifest()
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.EVIDENCE_CHAIN_HASH_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", report.status)

    def test_missing_semantics_binding_hash_fails_closed(self) -> None:
        chain = dict(EVIDENCE_CHAIN_KWARGS)
        chain.pop("semantics_binding_sha256")
        report = _assess_real_loop_acceptance(
            clean_runs(), prompt_manifest=prompt_manifest(), **chain
        )

        self.assertIn(
            RealLoopAcceptanceIssueCode.EVIDENCE_CHAIN_HASH_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("", report.semantics_binding_sha256)
        self.assertEqual("blocked", report.status)

    def test_prompt_manifest_hash_mismatch_fails_closed(self) -> None:
        rows = clean_runs()
        manifest = list(prompt_manifest(rows))
        manifest[0] = replace(manifest[0], prompt_sha256=digest("wrong-prompt"))

        report = assess_real_loop_acceptance(rows, prompt_manifest=tuple(manifest))

        self.assertIn(
            RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_prompt_manifest_duplicate_hash_fails_closed(self) -> None:
        rows = clean_runs()
        manifest = list(prompt_manifest(rows))
        manifest[1] = replace(manifest[1], prompt_sha256=manifest[0].prompt_sha256)

        report = assess_real_loop_acceptance(rows, prompt_manifest=tuple(manifest))

        self.assertIn(
            RealLoopAcceptanceIssueCode.PROMPT_MANIFEST_HASH_DUPLICATE,
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
