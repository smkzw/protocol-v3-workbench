"""Read-only cross-contract linter CLI for Protocol v3 Task 3R.3 chapter registries.

Loads a chapter registry (embedded ``ChapterContractV2`` per node plus
companion chapter-skill manifests) and lints it against an accepted template
directory (``template.json`` + ``node_tree.json``).  Coverage truth is derived
from the template node tree; a full-mode run with missing carriers reports
them and does NOT generate missing chapter data.

Exit status:
  0  success — full mode complete, or partial mode with no error findings
     (partial output always says the registry is incomplete);
  1  error findings (missing coverage in full mode, identity/vocabulary/
     conflict/anchor/dependency/template failures);
  2  usage or input failure (unreadable/invalid registry or template).

The CLI performs no writes and has no import side effects.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parents[2]
for _path in ("services/api", "packages", "."):
    _candidate = _REPO_ROOT / _path
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from app.protocol_workflow.registries.chapters import (  # noqa: E402
    ChapterRegistryError,
    LintInputError,
    lint_registry,
    load_chapter_registry,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lint_chapter_registry",
        description=(
            "Read-only cross-contract linter for typed chapter registries "
            "(ChapterContractV2 + chapter skill manifests)."
        ),
    )
    parser.add_argument(
        "--registry",
        required=True,
        help="path to the chapter registry JSON document",
    )
    parser.add_argument(
        "--template-dir",
        required=True,
        help="accepted template directory containing template.json and node_tree.json",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help=(
            "validate a partial batch; the report always says the registry is "
            "incomplete and never represents full acceptance"
        ),
    )
    parser.add_argument(
        "--check-fixtures",
        action="store_true",
        help="display detailed fixture results (fixture validation always runs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit a JSON report on stdout instead of text",
    )
    return parser


def _render_text(report, fixture_results) -> str:
    lines = [
        f"mode: {report.mode}",
        f"status: {report.status}",
        (
            f"coverage: expected={report.coverage.expected_carrier_count} "
            f"covered={report.coverage.covered_carrier_count} "
            f"leaf_union={report.coverage.leaf_union_count} "
            f"cover={report.coverage.cover_node_id or '-'}"
        ),
    ]
    if report.coverage.missing_node_ids:
        lines.append(
            "missing carriers: " + ", ".join(report.coverage.missing_node_ids)
        )
    if report.coverage.unexpected_node_ids:
        lines.append(
            "unexpected carriers: " + ", ".join(report.coverage.unexpected_node_ids)
        )
    for finding in report.findings:
        lines.append(
            f"[{finding.severity.upper()}] {finding.code} "
            f"{finding.location}: {finding.message}"
        )
    for result in fixture_results:
        lines.append(
            f"fixture {result.subject_id} "
            f"({result.chapter_contract_id}): "
            f"{'PASS' if result.passed else 'FAIL'}"
        )
        for finding in result.findings:
            lines.append(
                f"  [{finding.severity.upper()}] {finding.code} "
                f"{finding.location}: {finding.message}"
            )
        for deferred in result.deferred_qc_obligations:
            lines.append(f"  [DEFERRED] {deferred}")
    if report.status == "incomplete":
        lines.append(
            "registry is INCOMPLETE; this report does not represent full "
            "acceptance and no missing chapter data was generated"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        document = load_chapter_registry(args.registry)
    except ChapterRegistryError as exc:
        print(f"registry load failed: {exc}", file=sys.stderr)
        return 2
    try:
        report = lint_registry(
            args.template_dir, document, require_complete=not args.partial
        )
    except LintInputError as exc:
        print(f"template input failed: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        payload = report.model_dump()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(report, report.fixture_results if args.check_fixtures else ()))

    if report.errors():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
