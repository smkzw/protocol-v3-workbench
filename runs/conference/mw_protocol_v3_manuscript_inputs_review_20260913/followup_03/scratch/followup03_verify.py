"""Read-only followup_03 probes: diagnostic projection, retry identity, LookupError."""
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
from app.protocol_workflow.registries.fact_bindings import FactBindingError, bind_chapter_input
from app.protocol_workflow.registries.applicability import diagnose_applicable_input, bind_applicable_chapter
from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
from app.protocol_workflow.agent3.source_preparation import (
    build_source_preparation, SourcePreparationIncomplete,
)
from app.protocol_workflow.api.composition import protocol_workflow_config_from_env
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


def diagnostic_projections():
    banner("diagnose_applicable_input projections")
    template = boolean_template(load_current_template(REAL_TEMPLATE_DIR))
    contract = next(e.contract for e in template.registry.chapters if e.node_id == "v2_n_4_1")
    base = {
        "framing.structured_design": "invalid boolean",
        "framing.study_phase": "Ⅱ期",
        "framing.structured_design.phase": "Ⅲ期",
    }
    for label, extra in (
        ("unresolved", {}),
        ("inner_false", {"statistics.interim.applicable": False,
                         "framing.structured_design.features": {"stratification": False, "substudy": False}}),
        ("interim_true", {"statistics.interim.applicable": True}),
    ):
        study = confirmed_study({**base, **extra})
        app_findings, fact_errors = diagnose_applicable_input(
            study, contract, template.fact_catalog.bindings, rules=template.rules_catalog.rules)
        missing = {p for f in fact_errors if f.code == "missing_required_fact" for p in f.fact_paths}
        print(label, "app", [f.code for f in app_findings],
              "facts", [f.code for f in fact_errors],
              "interim_in_missing", "framing.structured_design.interim_analysis" in missing,
              "strat_in_missing", "framing.structured_design.stratification" in missing,
              "arms_in_missing", "framing.structured_design.arms" in missing)
        try:
            bind_applicable_chapter(study, contract, template.fact_catalog.bindings,
                                    rules=template.rules_catalog.rules)
            print(label, "strict_bind", "SUCCESS")
        except (Exception,) as exc:
            print(label, "strict_bind", type(exc).__name__, getattr(exc, "code", str(exc)[:80]))
        try:
            bind_chapter_input(study, contract, template.fact_catalog.bindings)
        except FactBindingError as exc:
            print(label, "raw_strict_first", exc.code)
        item = next(i for i in plan_manuscript_chapters(template, study)["chapters"] if i["node_id"] == "v2_n_4_1")
        print(label, "plan_codes", [e["code"] for e in item["errors"]], "status", item["status"])


def source_retry_and_unknown():
    banner("source prep LookupError vs OSError vs retry identity")
    config_env = protocol_workflow_config_from_env()
    print("default_mount_enabled", config_env.enabled)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        config = {"backend": "sqlite", "path": str(tmp / "prep.sqlite")}

        class Missing:
            def history(self, *a, **k):
                raise LookupError("chapter_source_not_found")

        owner = build_source_preparation(
            project_id="project-1", branch_id="main",
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            source_service=Missing(),
        )
        run = owner.start(prepare_seed_request("合成", ()))
        try:
            owner.resume(run)
            print("lookup_resume", "UNEXPECTED")
        except SourcePreparationIncomplete as exc:
            print("lookup_state", exc.state["status"], exc.state["error_code"],
                  "can_retry", exc.state["can_retry"], "can_resume", exc.state["can_resume"])
        try:
            owner.retry(run, retry_decision_id="source-retry:one")
            print("lookup_retry", "UNEXPECTED")
        except SourcePreparationIncomplete as exc:
            print("lookup_retry_blocked", exc.state["status"], exc.state["can_retry"])

        raw = build_docx(paragraph_xml("同一原文"))
        first = adopt(service(tmp), raw)
        seed = prepare_seed_request("合成", ((first.source.source, parse_docx(raw)),))

        class OnceOSError:
            calls = 0
            def history(self, *a, **k):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("temp")
                return service(tmp).history(*a, **k)
            def read_content(self, *a, **k):
                return service(tmp).read_content(*a, **k)

        sources = OnceOSError()
        owner2 = build_source_preparation(
            project_id="project-1", branch_id="main",
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            source_service=sources, clock=lambda: datetime(2026, 9, 13, tzinfo=timezone.utc),
        )
        run2 = owner2.start(seed)
        try:
            owner2.resume(run2)
        except SourcePreparationIncomplete as exc:
            print("oserror_state", exc.state["status"], exc.state["error_code"], "can_retry", exc.state["can_retry"])
        bundle = owner2.retry(run2, retry_decision_id="source-retry:one")
        print("retry_ok", bundle.evidence[0].body, "extracted", bundle.evidence[0].extracted_at.isoformat())
        try:
            owner2.retry(run2, retry_decision_id="source-retry:OTHER")
            print("mismatch_retry", "UNEXPECTED")
        except ValueError as exc:
            print("mismatch_retry", str(exc))
        print("parent_failure_kept", owner2._output(run2)["source_preparation_failure"]["code"])
        print("retry_child", owner2.state(run2)["retry_run_id"])
        before = _dump(tmp / "prep.sqlite")
        again = owner2.retry(run2, retry_decision_id="source-retry:one")
        print("idempotent_retry", again.input_sha256 == bundle.input_sha256, "db_same", _dump(tmp / "prep.sqlite") == before)
        print("attempts_parent", len(owner2.runtime.reservation_attempts(run2, "prepare-sources")),
              "attempts_child", len(owner2.runtime.reservation_attempts(run2 + ":retry:1", "prepare-sources")))


if __name__ == "__main__":
    diagnostic_projections()
    source_retry_and_unknown()
