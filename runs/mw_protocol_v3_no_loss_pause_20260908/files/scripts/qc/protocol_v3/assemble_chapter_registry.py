"""Read-only stdlib assembly CLI for Task3R.3 batch chapter registries.

Joins the authored per-node chapter-contract JSON files
(``chapter_contracts/<node_id>.json``), their companion chapter-skill
manifests (``chapter_skills/<node_id>.json``) and a batch fixture/vocabulary
document (closed fact/claim vocabularies, coverage roles, executable
fixtures) into one accepted :class:`ChapterRegistryDocument` shape.  The
chapter JSON files stay the single authored contracts; this helper never
duplicates or rewrites their content.

Library model validation is mandatory: every contract payload must validate
as :class:`ChapterContractV2`, every skill payload as
:class:`ChapterSkillManifest`, and the assembled document must pass the
fail-closed ``load_chapter_registry`` before it is printed.  Output goes to
stdout only; the CLI performs no writes, no activation and no promotion.
Later batches reuse this same assembly.

Exit status: 0 success; 2 usage/input failure (unreadable files, schema
mismatch, identity binding failure, or fail-closed registry validation).
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

from packages.contracts.workbench_contracts.protocol_v3 import (  # noqa: E402
    ChapterContractV2,
)

from app.protocol_workflow.registries.chapters import (  # noqa: E402
    ChapterSkillManifest,
    load_chapter_registry,
)

BATCH_SCHEMA_VERSION = "protocol-v3-chapter-batch.v1"
REGISTRY_SCHEMA_VERSION = "protocol-v3-chapter-registry.v1"

_BATCH_REQUIRED_KEYS = (
    "schema_version",
    "generated_for",
    "authority",
    "template_id",
    "template_sha256",
    "fact_vocabulary",
    "claim_vocabulary",
    "coverage_roles",
    "fixtures",
)


class AssemblyInputError(ValueError):
    """Raised when the batch inputs are unusable; reported without traceback."""


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AssemblyInputError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AssemblyInputError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AssemblyInputError(f"{path} must contain a JSON object")
    return data


def _load_batch_document(batch_path: Path) -> dict:
    batch = _read_json(batch_path)
    missing = [key for key in _BATCH_REQUIRED_KEYS if key not in batch]
    if missing:
        raise AssemblyInputError(
            f"{batch_path} is missing batch keys: {missing}"
        )
    if batch["schema_version"] != BATCH_SCHEMA_VERSION:
        raise AssemblyInputError(
            f"{batch_path} schema_version must be {BATCH_SCHEMA_VERSION!r}; "
            f"got {batch['schema_version']!r}"
        )
    if not isinstance(batch["coverage_roles"], dict) or not batch["coverage_roles"]:
        raise AssemblyInputError(
            f"{batch_path} coverage_roles must be a non-empty object"
        )
    for key in ("fact_vocabulary", "claim_vocabulary", "fixtures"):
        if not isinstance(batch[key], list):
            raise AssemblyInputError(f"{batch_path} {key} must be a list")
    return batch


def _load_payload_dir(directory: Path, label: str, node_ids: dict) -> dict:
    if not directory.is_dir():
        raise AssemblyInputError(f"{label} directory does not exist: {directory}")
    payloads = {}
    for node_id in sorted(node_ids):
        path = directory / f"{node_id}.json"
        payloads[node_id] = _read_json(path)
    if not payloads:
        raise AssemblyInputError(f"{label} directory has no JSON files: {directory}")
    return payloads


def assemble_registry(
    contracts_dir: str | Path,
    skills_dir: str | Path,
    batch_path: str | Path,
) -> dict:
    """Assemble and fail-closed validate one batch registry payload."""
    contracts_dir = Path(contracts_dir)
    skills_dir = Path(skills_dir)
    batch_path = Path(batch_path)
    batch = _load_batch_document(batch_path)
    contract_payloads = _load_payload_dir(contracts_dir, "chapter_contracts", batch["coverage_roles"])
    skill_payloads = _load_payload_dir(skills_dir, "chapter_skills", batch["coverage_roles"])

    entries = []
    for stem in sorted(contract_payloads):
        contract = ChapterContractV2.model_validate(contract_payloads[stem])
        if contract.semantic_node_id != stem:
            raise AssemblyInputError(
                f"{contracts_dir / stem}.json binds semantic_node_id "
                f"{contract.semantic_node_id!r}; the file name must be the node id"
            )
        if stem not in skill_payloads:
            raise AssemblyInputError(f"no companion skill manifest for {stem!r}")
        skill = ChapterSkillManifest.model_validate(skill_payloads[stem])
        coverage_role = batch["coverage_roles"].get(stem)
        if coverage_role is None:
            raise AssemblyInputError(
                f"{batch_path} declares no coverage role for {stem!r}"
            )
        entries.append(
            {
                "node_id": stem,
                "coverage_role": coverage_role,
                "contract": json.loads(contract.model_dump_json()),
                "skills": [json.loads(skill.model_dump_json())],
            }
        )

    payload = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "generated_for": batch["generated_for"],
        "authority": batch["authority"],
        "template_id": batch["template_id"],
        "template_sha256": batch["template_sha256"],
        "fact_vocabulary": list(batch["fact_vocabulary"]),
        "claim_vocabulary": list(batch["claim_vocabulary"]),
        "chapters": entries,
        "fixtures": list(batch["fixtures"]),
    }
    load_chapter_registry(payload)
    return payload


def assemble_registries(contracts_dir, skills_dir, batch_paths) -> dict:
    """Combine explicit batch slices; never overwrite duplicate chapter identities."""
    documents = [assemble_registry(contracts_dir, skills_dir, path) for path in batch_paths]
    if not documents:
        raise AssemblyInputError("at least one batch is required")
    combined = dict(documents[0])
    for document in documents[1:]:
        if any(document[key] != combined[key] for key in ("template_id", "template_sha256")):
            raise AssemblyInputError("batches refer to different template identities")
    for key in ("generated_for", "authority"):
        combined[key] = "\n".join(dict.fromkeys(document[key] for document in documents))
    for key in ("fact_vocabulary", "claim_vocabulary"):
        combined[key] = sorted({value for document in documents for value in document[key]})
    for key in ("chapters", "fixtures"):
        combined[key] = [value for document in documents for value in document[key]]
    load_chapter_registry(combined)
    return combined


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="assemble_chapter_registry",
        description=(
            "Assemble authored chapter-contract/skill JSON files and a batch "
            "fixture/vocabulary document into a validated chapter registry "
            "printed on stdout (read-only; no writes, activation or promotion)."
        ),
    )
    parser.add_argument("--contracts-dir", required=True)
    parser.add_argument("--skills-dir", required=True)
    parser.add_argument("--batch", required=True, action="append", help="repeat for each batch to include")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        payload = assemble_registries(args.contracts_dir, args.skills_dir, args.batch)
    except ValueError as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
