#!/usr/bin/env python3
"""Task 0.8 driver for read-only inventory and task-copy Word PoCs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pocs.protocol_v3.word_receipt.producers.applescript_bridge import (
    finalize_visual_qc,
    produce_candidate,
    producer_identity,
    word_inventory,
)
from pocs.protocol_v3.word_receipt.producers.base import (
    ProducerFunctionalError,
    ProducerRequest,
    inspect_docx_ooxml,
    sha256_file,
)
from pocs.protocol_v3.word_receipt.roundtrip_lineage import (
    prepare_roundtrip,
    stage_reimport,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory", help="read installed/running Word state")

    inspect_parser = subparsers.add_parser("inspect-source", help="read DOCX OOXML facts")
    inspect_parser.add_argument("--source", type=Path, required=True)

    run_parser = subparsers.add_parser("run", help="produce a task-copy receipt candidate")
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--source", type=Path, required=True)
    run_parser.add_argument("--results-root", type=Path, required=True)
    run_parser.add_argument("--semantic-revision", required=True)
    run_parser.add_argument("--template-revision", required=True)
    run_parser.add_argument("--source-snapshot-sha256", default="")
    run_parser.add_argument(
        "--lineage-manifest",
        type=Path,
        help="immutable edit/reimport/re-export lineage JSON",
    )

    prepare_parser = subparsers.add_parser(
        "prepare-roundtrip", help="prepare a task-owned DOCX for a visible Word wording edit"
    )
    prepare_parser.add_argument("--source-run-dir", type=Path, required=True)
    prepare_parser.add_argument("--roundtrip-dir", type=Path, required=True)

    reimport_parser = subparsers.add_parser(
        "stage-reimport", help="freeze the edited DOCX and lineage for re-export verification"
    )
    reimport_parser.add_argument("--roundtrip-dir", type=Path, required=True)
    reimport_parser.add_argument("--merged-semantic-revision", required=True)

    finalize_parser = subparsers.add_parser(
        "finalize", help="finalize after visible review of every page"
    )
    finalize_parser.add_argument("--run-dir", type=Path, required=True)
    finalize_parser.add_argument(
        "--passed-pages",
        required=True,
        help="comma-separated ordered pages, for example 1,2,3",
    )
    return parser


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory":
            _print({"producer_identity": producer_identity(), "word": word_inventory()})
            return 0
        if args.command == "inspect-source":
            facts = inspect_docx_ooxml(args.source.resolve(strict=True))
            _print(
                {
                    key: value
                    for key, value in facts.items()
                    if key not in {"fields", "bookmarks"}
                }
                | {
                    "field_samples": facts["fields"][:10],
                    "bookmark_samples": facts["bookmarks"][:10],
                }
            )
            return 0
        if args.command == "run":
            source = args.source.resolve(strict=True)
            source_hash = sha256_file(source)
            if args.source_snapshot_sha256 and args.source_snapshot_sha256 != source_hash:
                raise ProducerFunctionalError(
                    "WR_SOURCE_SNAPSHOT", "provided source snapshot does not match DOCX"
                )
            request = ProducerRequest(
                label=args.label,
                source_path=source,
                results_root=args.results_root.resolve(),
                source_snapshot_sha256=source_hash,
                semantic_document_revision=args.semantic_revision,
                template_revision=args.template_revision,
                edit_reimport_export_lineage=(
                    json.loads(args.lineage_manifest.resolve(strict=True).read_text(encoding="utf-8"))
                    if args.lineage_manifest
                    else None
                ),
            )
            _print(produce_candidate(request))
            return 0
        if args.command == "prepare-roundtrip":
            _print(
                prepare_roundtrip(
                    args.source_run_dir.resolve(strict=True),
                    args.roundtrip_dir.resolve(),
                )
            )
            return 0
        if args.command == "stage-reimport":
            _print(
                stage_reimport(
                    args.roundtrip_dir.resolve(strict=True),
                    merged_semantic_revision=args.merged_semantic_revision,
                )
            )
            return 0
        if args.command == "finalize":
            passed_pages = [
                int(item.strip())
                for item in args.passed_pages.split(",")
                if item.strip()
            ]
            _print(finalize_visual_qc(args.run_dir.resolve(strict=True), passed_pages=passed_pages))
            return 0
    except ProducerFunctionalError as exc:
        _print({"status": "blocked", "failure_code": exc.code, "message": str(exc)})
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
