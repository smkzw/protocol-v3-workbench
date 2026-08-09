from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.ai_execution_policy import AiExecutionPolicyResolver  # noqa: E402
from services.api.app.ai_gateway import (  # noqa: E402
    DisabledAiProvider,
    configured_ai_provider_from_env,
)
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore  # noqa: E402
from services.api.app.demo_repository import DemoRepository  # noqa: E402
from services.api.app.medical_writing_synopsis_import import (  # noqa: E402
    MedicalWritingSynopsisImportService,
)


def _parse_case(value: str) -> tuple[str, str, Path]:
    parts = value.split("|", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("case must be LABEL|INDICATION|DOCX_PATH")
    label, indication, raw_path = (part.strip() for part in parts)
    path = Path(raw_path).expanduser().resolve()
    if not label or not indication or not path.is_file():
        raise argparse.ArgumentTypeError(f"invalid real-project case: {value}")
    return label, indication, path


def _parse_labeled_token(value: str) -> tuple[str, str]:
    parts = value.split("|", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError("value must be LABEL|TOKEN")
    return parts[0].strip(), parts[1].strip()


_TOKEN_ALIASES = {
    "promis": ("promis", "患者报告结局测量信息系统"),
}


def _alias_in_haystack(haystack: str, alias: str) -> bool:
    if alias.isascii() and alias.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", haystack) is not None
    return alias in haystack


def _instrument_token_matches(searchable_instrument: str, token: str) -> bool:
    parts = [
        part.casefold()
        for part in re.split(r"[\s/|,，、;；:：()（）\[\]【】_\-]+", token)
        if part.strip()
    ]
    haystack = searchable_instrument.casefold()
    return bool(parts) and all(
        any(
            _alias_in_haystack(haystack, alias)
            for alias in _TOKEN_ALIASES.get(part, (part,))
        )
        for part in parts
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", type=_parse_case, required=True)
    parser.add_argument("--expect-instrument", action="append", type=_parse_labeled_token, default=[])
    parser.add_argument("--forbid-instrument", action="append", type=_parse_labeled_token, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    provider = configured_ai_provider_from_env()
    if isinstance(provider, DisabledAiProvider):
        raise RuntimeError("independent production AI provider is not configured")
    policy = AiExecutionPolicyResolver()
    report: dict[str, object] = {
        "provider": os.environ.get("WORKBENCH_AI_PROVIDER", ""),
        "model": os.environ.get("WORKBENCH_AI_MODEL", ""),
        "transport": os.environ.get("WORKBENCH_AI_TRANSPORT", ""),
        "codex_runtime_dependency": False,
        "hermes_runtime_dependency": False,
        "prompt_version": "protocol_synopsis_structuring_v0_6",
        "cases": [],
    }
    results: list[dict[str, object]] = report["cases"]  # type: ignore[assignment]

    def persist() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    with tempfile.TemporaryDirectory(prefix="mw-real-instrument-extraction-") as tmp:
        runtime_root = Path(tmp)
        runner = AiTaskRunner(
            DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"),
            AiTaskStore(runtime_root / "ai_runs.jsonl"),
            provider_factory=lambda resolution: provider,
            policy_resolver=policy,
        )
        importer = MedicalWritingSynopsisImportService(
            runtime_root / "synopsis_artifacts",
            runner,
            runtime_root / "synopsis.sqlite3",
        )
        for index, (label, indication, path) in enumerate(args.case, start=1):
            project_id = f"real_protocol_instrument_qc_{index}_{label.lower()}"
            try:
                imported = importer.import_and_structure(
                    project_id,
                    filename=path.name,
                    content_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    payload=path.read_bytes(),
                    expected_indication=indication,
                    actor="medical_manager_real_project_qc",
                    idempotency_key=f"real-protocol-instrument-qc-{index}",
                )
            except Exception as exc:
                runs = runner.list_runs(project_id)
                latest = runs[-1] if runs else None
                results.append(
                    {
                        "label": label,
                        "indication": indication,
                        "source_path": str(path),
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "ai_run_id": latest.run_id if latest else "",
                        "ai_run_status": (
                            getattr(latest.status, "value", latest.status) if latest else ""
                        ),
                        "validation_errors": latest.validation_errors if latest else [],
                    }
                )
                persist()
                continue
            instruments = []
            for item in imported.proposed_picos.assessment_instruments:
                instruments.append(
                    {
                        "instrument_id": item.instrument_id,
                        "canonical_name_zh": item.canonical_name_zh,
                        "canonical_name_en": item.canonical_name_en,
                        "acronym": item.acronym,
                        "version_label": item.version_label,
                        "instrument_kind": item.instrument_kind,
                        "administration_mode": item.administration_mode,
                        "respondent": item.respondent,
                        "recall_period": item.recall_period,
                        "study_purpose": item.study_purpose,
                        "endpoint_paths": item.endpoint_paths,
                        "visit_labels": item.visit_labels,
                        "scoring_range": item.scoring_range,
                        "scoring_direction": item.scoring_direction,
                        "scoring_summary": item.scoring_summary,
                        "appendix_locator": item.appendix_locator,
                        "protocol_modified": item.protocol_modified,
                        "confirmation_status": item.confirmation_status,
                        "rights_status": item.rights.status,
                        "full_text_policy": item.rights.full_text_policy,
                        "translation_status": item.translation.status,
                        "source_synopsis_only": item.source_synopsis_only,
                        "evidence_span_ids": item.evidence_span_ids,
                        "source_bindings": [
                            {
                                "source_kind": binding.source_kind,
                                "source_id": binding.source_id,
                                "locator": binding.locator,
                                "evidence_sha256": binding.evidence_sha256,
                            }
                            for binding in item.source_bindings
                        ],
                    }
                )
            searchable_instruments = [
                " ".join(
                    str(item.get(field) or "")
                    for field in ("acronym", "canonical_name_zh", "canonical_name_en")
                )
                for item in instruments
            ]
            expected_tokens = [
                token for case_label, token in args.expect_instrument if case_label == label
            ]
            forbidden_tokens = [
                token for case_label, token in args.forbid_instrument if case_label == label
            ]
            missing_expected = [
                token
                for token in expected_tokens
                if not any(
                    _instrument_token_matches(searchable, token)
                    for searchable in searchable_instruments
                )
            ]
            present_forbidden = [
                token
                for token in forbidden_tokens
                if any(
                    _instrument_token_matches(searchable, token)
                    for searchable in searchable_instruments
                )
            ]
            contract_errors: list[str] = []
            evidence_ids = {item.span_id for item in imported.evidence_spans}
            for item in instruments:
                item_ids = item["evidence_span_ids"]
                if not 1 <= len(item_ids) <= 5:
                    contract_errors.append(
                        f"{item['acronym'] or item['canonical_name_zh']}: evidence count is {len(item_ids)}"
                    )
                unknown_ids = sorted(set(item_ids) - evidence_ids)
                if unknown_ids:
                    contract_errors.append(
                        f"{item['acronym'] or item['canonical_name_zh']}: unknown evidence IDs {unknown_ids}"
                    )
                if len(item["source_bindings"]) != len(dict.fromkeys(item_ids)):
                    contract_errors.append(
                        f"{item['acronym'] or item['canonical_name_zh']}: source binding count mismatch"
                    )
                if (
                    item["confirmation_status"] != "candidate"
                    or item["rights_status"] != "unknown"
                    or item["full_text_policy"] != "metadata_only"
                    or item["translation_status"] != "unknown"
                ):
                    contract_errors.append(
                        f"{item['acronym'] or item['canonical_name_zh']}: governance state is not fail-closed"
                    )
            contract_errors.extend(f"missing expected instrument: {token}" for token in missing_expected)
            contract_errors.extend(f"forbidden instrument present: {token}" for token in present_forbidden)
            results.append(
                {
                    "label": label,
                    "indication": indication,
                    "source_path": str(path),
                    "source_sha256": imported.source.content_sha256,
                    "source_role_status": imported.source.source_role_status,
                    "indication_status": imported.source.indication_status,
                    "validation_warnings": imported.source.validation_warnings,
                    "ai_run_id": imported.ai_run_id,
                    "import_status": imported.status,
                    "proposed_framing": imported.proposed_framing.model_dump(mode="json"),
                    "evidence_span_count": len(imported.evidence_spans),
                    "evidence_spans": [
                        {
                            "span_id": item.span_id,
                            "locator": item.locator,
                            "source_text": item.source_text,
                            "source_text_sha256": item.source_text_sha256,
                        }
                        for item in imported.evidence_spans
                    ],
                    "instrument_count": len(instruments),
                    "instruments": instruments,
                    "semantic_checks": {
                        "expected_tokens": expected_tokens,
                        "missing_expected": missing_expected,
                        "forbidden_tokens": forbidden_tokens,
                        "present_forbidden": present_forbidden,
                        "contract_errors": contract_errors,
                        "passed": not contract_errors,
                    },
                }
            )
            persist()

    persist()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return (
        0
        if all(
            item.get("status") != "failed"
            and item.get("semantic_checks", {}).get("passed") is True
            for item in results
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
