"""Reproduce the mechanical fact-address report from the reviewed catalog."""
import argparse
import hashlib
import json
from pathlib import Path


def registration(catalog: dict) -> dict:
    rows = []
    for binding in catalog["bindings"]:
        canonical = binding["canonical_path"]
        method = "unsupported" if canonical is None else (
            "canonical_direct" if canonical == binding["fact_path"] else "projection"
        )
        rows.append({
            **binding, "resolution": method,
            "consuming_contracts": sorted({
                ref.split(".json#")[0].removeprefix("chapter_contracts/")
                for ref in binding["source_refs"] if ref.startswith("chapter_contracts/")
            }),
            "runtime_reader": "registries.fact_bindings.bind_chapter_input",
            "clinical_value_acquisition": "not asserted by this address catalog",
        })
    return {
        "scope": "mechanical canonical lookup; native facts supplied by confirmed StudyDefinition, not material extraction or clinical approval",
        "unsupported_fact_paths": [r["fact_path"] for r in rows if r["resolution"] == "unsupported"],
        "legacy_type_unresolved_paths": [r["fact_path"] for r in rows if r["value_type"] == "json"],
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.catalog.read_bytes()
    report = registration(json.loads(raw))
    report["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    # Reports are versioned evidence; never overwrite a previous run.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
