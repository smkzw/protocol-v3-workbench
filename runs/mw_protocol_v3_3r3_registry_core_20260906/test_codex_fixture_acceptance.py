"""Library/CLI acceptance regressions from independent review; no model calls."""
import json
import test_all_chapter_contracts as h
from app.protocol_workflow.registries.chapters import lint_registry, load_chapter_registry


def payload():
    return h._syn_registry_payload([
        h._entry_payload(h._syn_cover_contract(), "cover"),
        h._entry_payload(h._syn_chapter(1)),
        h._entry_payload(h._syn_chapter(2)),
    ])


def test_fixtureless_library_cannot_report_complete(tmp_path):
    data = payload()
    data["fixtures"] = []
    report = lint_registry(h._synthetic_template_dir(tmp_path), load_chapter_registry(data))
    assert report.status == "incomplete"
    assert "missing_fixture" in {f.code for f in report.errors()}


def test_poisoned_fixture_fails_library_even_in_partial_mode(tmp_path):
    data = payload()
    data["fixtures"] = [h._fixture_payload("fixture:bad-positive", "contract:syn-1:v2", "positive", {})]
    report = lint_registry(h._synthetic_template_dir(tmp_path), load_chapter_registry(data), require_complete=False)
    assert "fixture_expectation_mismatch" in {f.code for f in report.errors()}


def test_cli_default_and_formats_share_failing_verdict(tmp_path):
    data = payload()
    data["fixtures"] = [h._fixture_payload("fixture:bad-positive", "contract:syn-1:v2", "positive", {})]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    directory = h._synthetic_template_dir(tmp_path / "template")
    args = ["--registry", str(path), "--template-dir", str(directory)]
    plain = h._run_cli(args, h.REPO_ROOT)
    machine = h._run_cli(args + ["--json"], h.REPO_ROOT)
    assert plain.returncode == machine.returncode == 1
    assert "status: incomplete" in plain.stdout
    assert json.loads(machine.stdout)["status"] == "incomplete"


def test_claim_bearing_control_negative_is_valid(tmp_path):
    data = payload()
    contract = data["chapters"][0]["contract"]
    contract["substantive_content"]["claim_requirements"] = [{
        "claim_type": "study_objective", "obligation": "required", "rationale": "Synthetic control obligation",
    }]
    data["fixtures"] = [h._fixture_payload(
        "fixture:control:claim-missing", contract["chapter_contract_id"],
        "missing_control", h._cover_positive_content(),
    )]
    report = lint_registry(h._synthetic_template_dir(tmp_path), load_chapter_registry(data), require_complete=False)
    assert len(report.fixture_results) == 1
    assert not report.fixture_results[0].passed
    assert "missing_required_claim" in report.fixture_results[0].error_codes()
    assert not report.errors()


def test_real_template_rejects_arbitrary_cover_identity():
    data = h._registry_payload([h._entry_payload(h._cover_contract(), "cover")])
    entry = data["chapters"][0]
    entry["node_id"] = "unrelated_cover"
    entry["contract"]["semantic_node_id"] = "unrelated_cover"
    entry["skills"][0]["node_id"] = "unrelated_cover"
    report = lint_registry(h.REAL_TEMPLATE_DIR, load_chapter_registry(data), require_complete=False)
    assert "cover_identity_mismatch" in {f.code for f in report.errors()}
