"""Review-only reproductions using actual service + existing deterministic fakes.

No service, network/model/OCR/Word call. Test-owned temporary stores only.
This proves observed legacy defects, not v3 acceptance or a fixed regression.
"""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fixtures = runpy.run_path(str(ROOT / "tests/test_medical_writing_full_draft.py"))


def completed_job(case):
    project = case.repo.project_id
    job_id, _ = case.full.submit_durable(project, case.store)
    claim = case.store.claim(project, job_id)
    result = fixtures["ProtocolFullDraftExecutor"](case.full).execute(
        claim.job, claim.claim_token, lambda: False, lambda progress: True
    )
    assert not result.error, result.error
    case.store.complete(
        project, job_id, claim.claim_token, output_hash=result.output_hash,
        artifact_locator=result.artifact_locator, provider=result.provider,
        model=result.model, final_progress=result.progress,
    )
    return case.store.get(project, job_id)


def reproduce(kind):
    case = fixtures["FullDraftServiceTests"]()
    case.setUp()
    try:
        if kind == "multiple_body_blocks":
            first = case.repo.document.sections[0].content_blocks
            first[1]["text"] = "现有背景。"
            first.append({"block_id": "b1_extra", "block_type": "paragraph",
                          "text": "现有依据。", "source_kind": "greenfield_scaffold"})
            case.repo.working["sec_1"].content_blocks = [dict(b) for b in first]
        job = completed_job(case)
        if kind == "later_section_stale":
            case.repo.working["sec_2"].revision = 1
            case.repo.working["sec_2"].content_blocks[1]["text"] = "用户后改目的。"
        try:
            case.full.adopt(case.repo.project_id, job)
        except fixtures["StaleRuntimeStateError"] as exc:
            saved = [entry[0] for entry in case.repo.save_calls]
            if kind == "multiple_body_blocks":
                assert "正文变化" in str(exc) and not saved
            else:
                assert "章节版本变化" in str(exc) and saved == ["sec_1"]
            return {"case": kind, "observed_error": str(exc),
                    "saved_before_error": saved,
                    "fake_model_calls": case.runner.calls,
                    "real_model_calls": 0}
        raise AssertionError("Expected legacy defect did not reproduce; reassess source")
    finally:
        case.tearDown()


if __name__ == "__main__":
    print(json.dumps([reproduce(k) for k in
                     ("multiple_body_blocks", "later_section_stale")],
                     ensure_ascii=False, indent=2))
