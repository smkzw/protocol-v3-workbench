from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SLICE_ROOT = (
    PROJECT_ROOT
    / "records/active_slices/medical_writing_phase1_autoimmune_mnc_corpus_20260716"
)
TRANSLATION_ROOT = SLICE_ROOT / "translations"
OUTPUT_ROOT = PROJECT_ROOT / "services/api/assets/medical_writing_corpus"
OUTPUT_PATH = OUTPUT_ROOT / "phase1_autoimmune_mnc_candidates_v1.json"
MANIFEST_PATH = OUTPUT_ROOT / "phase1_autoimmune_mnc_candidates_v1.manifest.json"

LAYER_ID = "phase1_autoimmune_mnc"
ASSET_VERSION = "2026-07-16-v1"
EXPECTED_CONTRACT_HASH = (
    "8e3c66c1aff0f0f5f8c68e035466820dcc4feb3d5d16072c6f6be7685c865312"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _anchor(corpus_function: str) -> str:
    lowered = corpus_function.casefold()
    if any(token in lowered for token in ("safety", "stopping", "sentinel", "release", "dlrm")):
        return "safety"
    if any(token in lowered for token in ("washout", "administration", "dose", "regimen", "formulation")):
        return "intervention"
    if any(token in lowered for token in ("population", "pediatric")):
        return "eligibility"
    if any(token in lowered for token in ("rationale", "design", "cohort", "assignment", "review")):
        return "study_design"
    return "synopsis"


def _load_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected a list: {path}")
    return payload


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract_hash") != EXPECTED_CONTRACT_HASH:
        raise ValueError(f"translation manifest uses a stale contract: {path}")
    if payload.get("status") != "medical_review_pending":
        raise ValueError(f"translation manifest has an unexpected status: {path}")
    return payload


def build() -> tuple[Path, Path]:
    manifest_paths = [
        TRANSLATION_ROOT / "flash_biologic_current_glossary_manifest_v1.json",
        TRANSLATION_ROOT / "flash_core_v0_5_glossary_r3_manifest_v4.json",
    ]
    selection_paths = [
        TRANSLATION_ROOT / "biologic_translation_selection.json",
        TRANSLATION_ROOT / "translation_selection.json",
    ]
    selections = {
        item["segment_id"]: item
        for path in selection_paths
        for item in _load_list(path)
    }
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for manifest_path in manifest_paths:
        manifest = _load_manifest(manifest_path)
        for item in manifest["items"]:
            segment_id = str(item["segment_id"])
            if segment_id in seen:
                raise ValueError(f"duplicate phase-I segment: {segment_id}")
            metadata = selections.get(segment_id)
            if metadata is None:
                raise ValueError(f"missing selection metadata: {segment_id}")
            for field in (
                "nct_id",
                "sponsor",
                "modality",
                "compound",
                "corpus_function",
                "source_url",
                "source_locator",
                "document_sha256",
                "source_text_sha256",
            ):
                if str(item.get(field) or "") != str(metadata.get(field) or ""):
                    raise ValueError(f"manifest/selection mismatch for {segment_id}: {field}")
            if _sha256_bytes(item["source_text"].encode("utf-8")) != item["source_text_sha256"]:
                raise ValueError(f"source text hash mismatch: {segment_id}")
            if _sha256_bytes(item["translated_text"].encode("utf-8")) != item["translated_text_sha256"]:
                raise ValueError(f"translation hash mismatch: {segment_id}")
            if item.get("automatic_fidelity_status") != "passed":
                raise ValueError(f"candidate did not pass the automatic fidelity gate: {segment_id}")
            candidate = {
                "segment_id": segment_id,
                "nct_id": item["nct_id"],
                "sponsor": item["sponsor"],
                "phases": list(metadata.get("phases") or []),
                "conditions": list(metadata.get("conditions") or []),
                "modality": item["modality"],
                "compound": item["compound"],
                "corpus_function": item["corpus_function"],
                "ich_m11_anchor": _anchor(item["corpus_function"]),
                "applicability": str(metadata.get("applicability") or ""),
                "protocol_version": str(metadata.get("protocol_version") or ""),
                "document_date": str(metadata.get("document_date") or ""),
                "source_url": item["source_url"],
                "source_locator": item["source_locator"],
                "document_sha256": item["document_sha256"],
                "source_text": item["source_text"],
                "source_text_sha256": item["source_text_sha256"],
                "translated_text": item["translated_text"],
                "translated_text_sha256": item["translated_text_sha256"],
                "provider": item["provider"],
                "model_name": item["model_name"],
                "prompt_version": item["prompt_version"],
                "glossary_version": manifest["glossary_version"],
                "contract_hash": item["contract_hash"],
                "ai_run_id": item["ai_run_id"],
                "automatic_fidelity_status": "passed",
            }
            candidate["candidate_sha256"] = _sha256_bytes(_canonical(candidate))
            candidates.append(candidate)
            seen.add(segment_id)
    candidates.sort(key=lambda item: (item["nct_id"], item["segment_id"]))
    if len(candidates) != 18:
        raise ValueError(f"expected 18 current candidates, observed {len(candidates)}")
    payload = {
        "schema_version": "medical_writing_shared_corpus_candidates_v1",
        "layer_id": LAYER_ID,
        "asset_version": ASSET_VERSION,
        "item_count": len(candidates),
        "items": candidates,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    asset_sha256 = _file_sha256(OUTPUT_PATH)
    manifest = {
        "schema_version": "medical_writing_shared_corpus_asset_manifest_v1",
        "layer_id": LAYER_ID,
        "asset_version": ASSET_VERSION,
        "asset_sha256": asset_sha256,
        "item_count": len(candidates),
        "input_files": [
            {"path": str(path.relative_to(PROJECT_ROOT)), "sha256": _file_sha256(path)}
            for path in [*manifest_paths, *selection_paths]
        ],
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return OUTPUT_PATH, MANIFEST_PATH


if __name__ == "__main__":
    for output in build():
        print(output)
