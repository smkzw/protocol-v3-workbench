"""Read-only followup_02 probes: diagnostic completeness and source-prep recovery."""
from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path[:0] = [
    str(ROOT / "services/api"),
    str(ROOT),
    str(ROOT / "tests"),
    str(ROOT / "tests/protocol_v3"),
    str(ROOT / "tests/protocol_v3/integration"),
]

from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from app.protocol_workflow.registries.template_runtime import load_current_template
from app.protocol_workflow.registries.fact_bindings import (
    FactBindingError, bind_chapter_input, diagnose_chapter_facts,
)
from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
from test_chapter_fact_binding import confirmed_study
from test_writing_reference_docx import build_docx, paragraph_xml
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.storage.sqlite import (
    build_unit_of_work_factory, build_committed_reservation_repository_factory,
)
from test_source_identity_product import service, adopt
from test_template_fact_adoption import _dump


def banner(t):
    print(f"\n=== {t} ===")


def boolean_template(template):
    bindings = tuple(
        b.model_copy(update={"value_type": "boolean"}) if b.fact_path == "framing.structured_design"
        else b for b in template.fact_catalog.bindings
    )
    return replace(template, fact_catalog=template.fact_catalog.model_copy(update={"bindings": bindings}))


def design_item(plan):
    return next(i for i in plan["chapters"] if i["node_id"] == "v2_n_4_1")


def diagnostic_completeness():
    banner("diagnose vs strict first-error")
    template = boolean_template(load_current_template(REAL_TEMPLATE_DIR))
    contract = next(e.contract for e in template.registry.chapters if e.node_id == "v2_n_4_1")
    study = confirmed_study({
        "framing.structured_design": "invalid boolean",
        "framing.study_phase": "Ⅱ期",
        "framing.structured_design.phase": "Ⅲ期",
    })
    deferred = {path for rule in template.rules_catalog.rules
                if rule.rule_id in {r.conditional_applicability_rule_id for r in contract.conditional_applicability_rules}
                for path in rule.conditional_fact_paths}
    print("deferred", sorted(deferred))
    findings = diagnose_chapter_facts(study, contract, template.fact_catalog.bindings,
                                      deferred_required_paths=deferred)
    print("diagnose_codes", [f.code for f in findings])
    print("diagnose_alias_count", sum(1 for f in findings if f.code == "fact_alias_conflict"))
    missing = {p for f in findings if f.code == "missing_required_fact" for p in f.fact_paths}
    print("missing_has_arms", "framing.structured_design.arms" in missing)
    print("missing_has_stratification", "framing.structured_design.stratification" in missing)
    try:
        bind_chapter_input(study, contract, template.fact_catalog.bindings)
        print("strict_bind", "UNEXPECTED")
    except FactBindingError as exc:
        print("strict_first_error", exc.code, list(exc.fact_paths)[:4])

    plan = plan_manuscript_chapters(template, study)
    item = design_item(plan)
    print("plan_codes", [e["code"] for e in item["errors"]], "status", item["status"])

    # Sibling rule already true: interim applicable, features unknown.
    sibling = confirmed_study({
        "statistics.interim.applicable": True,
        "framing.study_phase": "Ⅱ期",
    })
    plan_s = plan_manuscript_chapters(template, sibling)
    item_s = design_item(plan_s)
    missing_s = {p for e in item_s["errors"] if e.get("code") == "missing_required_fact" for p in e.get("fact_paths", [])}
    print("sibling_codes", [e["code"] for e in item_s["errors"]])
    print("sibling_missing_interim_analysis", "framing.structured_design.interim_analysis" in missing_s)
    print("sibling_missing_arms", "framing.structured_design.arms" in missing_s)
    print("sibling_missing_stratification", "framing.structured_design.stratification" in missing_s)

    # Conditions resolved false: diagnose path is skipped; strict first error only.
    resolved = confirmed_study({
        "framing.structured_design": "invalid boolean",
        "framing.study_phase": "Ⅱ期",
        "framing.structured_design.phase": "Ⅲ期",
        "statistics.interim.applicable": False,
        "framing.structured_design.features": {"stratification": False, "substudy": False},
    })
    plan_r = plan_manuscript_chapters(template, resolved)
    item_r = design_item(plan_r)
    print("resolved_inner_errors", item_r["errors"], "status", item_r["status"])
    print("resolved_complete_set", {e["code"] for e in item_r["errors"]})


def source_prep_behavior():
    banner("source_preparation start/fail/reopen")
    from app.protocol_workflow.agent3.source_preparation import build_source_preparation

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        original = build_docx(paragraph_xml("完整来源最后一句"))
        adopted = adopt(service(tmp), original)
        seed = prepare_seed_request("合成说明", ((adopted.source.source, parse_docx(original)),))
        config = {"backend": "sqlite", "path": str(tmp / "preparation.sqlite")}
        clock = lambda: datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
        reads = {"n": 0}
        inner = service(tmp)

        class Counting:
            def history(self, *a, **k):
                reads["n"] += 1
                return inner.history(*a, **k)
            def read_content(self, *a, **k):
                reads["n"] += 1
                return inner.read_content(*a, **k)

        def create(src, when):
            return build_source_preparation(
                project_id="project-1", branch_id="main",
                uow_factory=build_unit_of_work_factory(config),
                reservation_repository_factory=build_committed_reservation_repository_factory(config),
                source_service=src, clock=when,
            )

        coordinator = create(Counting(), clock)
        run_id = coordinator.start(seed)
        print("start_source_reads", reads["n"], "run", run_id.startswith("chapter-sources:"))
        print("start_read_none", coordinator.read(run_id) is None)
        bundle = coordinator.resume(run_id)
        print("resume_reads", reads["n"], "extracted_at", bundle.evidence[0].extracted_at.isoformat())
        print("medical_admission", bundle.to_payload().get("medical_admission"))

        class Boom:
            def history(self, *a, **k):
                raise AssertionError("should not read after complete")
        reopened = create(Boom(), lambda: datetime(2027, 9, 13, 12, tzinfo=timezone.utc))
        restored = reopened.resume(run_id)
        print("year_later_same_bundle", restored.input_sha256 == bundle.input_sha256)
        print("year_later_extracted_at", restored.evidence[0].extracted_at.isoformat())

        # Failed extract is sticky under allowed_attempts=1
        original2 = build_docx(paragraph_xml("另一来源"))
        adopted2 = adopt(service(tmp), original2)
        seed2 = prepare_seed_request("合成说明2", ((adopted2.source.source, parse_docx(original2)),))
        fail_coord = create(Boom(), clock)
        run2 = fail_coord.start(seed2)
        print("fail_start_ok", run2 != run_id)
        try:
            out = fail_coord.resume(run2)
            print("fail_resume_return", out)
        except Exception as exc:
            print("fail_resume_exc", type(exc).__name__, str(exc)[:240])
        good = create(service(tmp), clock)
        try:
            out2 = good.resume(run2)
            print("retry_after_fail", out2)
            snap = good.runtime.load_run(good.plan, run2)
            print("retry_status", snap.status.value, "stop", snap.stop_reason)
        except Exception as exc:
            print("retry_after_fail_exc", type(exc).__name__, str(exc)[:240])


if __name__ == "__main__":
    diagnostic_completeness()
    source_prep_behavior()
