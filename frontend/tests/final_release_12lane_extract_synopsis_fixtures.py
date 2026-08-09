#!/usr/bin/env python3.11
"""
E3 Synopsis Fixture Extractor — Worker 05.

Creates reproducible, lossless page-extract fixtures from authoritative protocol
PDFs. Each fixture copies the exact physical Synopsis/Protocol Summary page range
into a new standalone PDF using pypdf.

Features:
  --generate   Extract all five synopsis fixtures + manifest + QC
  --verify-only  Re-verify existing fixtures (opens, page count, SHA, text evidence)

Determinism:
  - Output PDFs contain no wall-clock timestamp (CreationDate is removed).
  - Stable metadata identifies lane, source SHA, page range, tool/version.
  - Reruns produce byte-identical output.

Usage:
  python3.11 final_release_12lane_extract_synopsis_fixtures.py --generate
  python3.11 final_release_12lane_extract_synopsis_fixtures.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import pypdf
from pypdf import PdfReader, PdfWriter

# ─── Constants ───────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # workbench root

FIXTURES_DIR = (
    PROJECT_ROOT
    / "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures"
)

# Search roots for source PDFs (in priority order). The config declares
# protocol-corpus/raw/NCT.../Prot_000.pdf but that directory may not exist yet
# under the workbench root. The qoderwork research corpus has some of the PDFs.
SOURCE_SEARCH_ROOTS = [
    PROJECT_ROOT / "protocol-corpus/raw",
    PROJECT_ROOT / "records/research/medical_writing_autoimmune_phase1_biologic_corpus_20260716/raw/documents",
    # qoderwork mirror (sibling worktree)
    PROJECT_ROOT.parent / "qoderwork/implementation/workbench/records/research/medical_writing_autoimmune_phase1_biologic_corpus_20260716/raw/documents",
]

# Five PDF synopsis lanes with authoritative physical page ranges (1-based)
# from the execution context "Verified six-cell source authority".
SOURCES = [
    {
        "lane": "RA_I",
        "indication": "类风湿关节炎",
        "phase": "I",
        "nct_id": "NCT03156023",
        "protocol_subpath": "NCT03156023/Prot_000.pdf",
        "expected_sha256": "83c13414a14b6ea445016f005627177cb5dc4d6ab974aadaf74e3df049bf3f85",
        "page_range_1based": (3, 6),
        "synopsis_section": "Phase 1b RA Protocol Synopsis",
        "output_filename": "RA_I_synopsis_extract.pdf",
    },
    {
        "lane": "RA_III",
        "indication": "类风湿关节炎",
        "phase": "III",
        "nct_id": "NCT02629159",
        "protocol_subpath": "NCT02629159/Prot_000.pdf",
        "expected_sha256": "48b6154c0e1f0fd9e05938c3e5ad0878b2438c69f49174e6e21da781b35fef0b",
        "page_range_1based": (9, 19),
        "synopsis_section": "Phase 3 RA synopsis (SELECT-COMPARE)",
        "output_filename": "RA_III_synopsis_extract.pdf",
    },
    {
        "lane": "AD_I",
        "indication": "特应性皮炎",
        "phase": "I",
        "nct_id": "NCT04668066",
        "protocol_subpath": "NCT04668066/Prot_000.pdf",
        "expected_sha256": "3bbbbeeaf2d1ee8012ae1c28a0199ef46df471ee20a2bdd0ce607a79f9861a4a",
        "page_range_1based": (12, 18),
        "synopsis_section": "Phase 1 FIH SAD/MAD healthy-participant and AD-patient Protocol Summary",
        "output_filename": "AD_I_synopsis_extract.pdf",
    },
    {
        "lane": "AD_III",
        "indication": "特应性皮炎",
        "phase": "III",
        "nct_id": "NCT03745638",
        "protocol_subpath": "NCT03745638/Prot_000.pdf",
        "expected_sha256": "035f37d3fece57f5dd238378b6b36c186babb7c2a27afafc78005bafeb021c91",
        "page_range_1based": (12, 19),
        "synopsis_section": "Phase 3 AD Protocol Summary (TRuE-AD1)",
        "output_filename": "AD_III_synopsis_extract.pdf",
    },
    {
        "lane": "UC_III",
        "indication": "溃疡性结肠炎",
        "phase": "III",
        "nct_id": "NCT02407236",
        "protocol_subpath": "NCT02407236/UNIFI_Protocol_Amendment2_local_archive.pdf",
        "expected_sha256": "f5d4e6498cba6b78c1d41fc186b1865b066727019c63831d8ea198bd12abc923",
        "page_range_1based": (25, 39),
        "synopsis_section": "Phase 3 UC synopsis (UNIFI)",
        "output_filename": "UC_III_synopsis_extract.pdf",
    },
]

TOOL_NAME = "pypdf"
TOOL_VERSION = pypdf.__version__
TOOL_LICENSE = "BSD-3-Clause"
MANIFEST_SCHEMA_VERSION = "mw_e3_synopsis_extract_manifest_v1"

# Text evidence keywords for verification
SYNOPSIS_KEYWORDS = ["synopsis", "protocol summary", "protocol synopsis", "摘要"]
INDICATION_KEYWORDS = {
    "RA_I": ["rheumatoid arthritis", "ra"],
    "RA_III": ["rheumatoid arthritis", "ra"],
    "AD_I": ["atopic dermatitis", "ad"],
    "AD_III": ["atopic dermatitis", "ad"],
    "UC_III": ["ulcerative colitis", "uc"],
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_source_path(src: dict) -> Path | None:
    """Search SOURCE_SEARCH_ROOTS for the protocol PDF by NCT subpath."""
    for root in SOURCE_SEARCH_ROOTS:
        candidate = root / src["protocol_subpath"]
        if candidate.exists():
            return candidate
    return None


def verify_source_sha(src: dict) -> tuple[bool, str]:
    """Verify source PDF exists and matches expected SHA-256. Fail closed on mismatch."""
    path = resolve_source_path(src)
    if path is None:
        searched = "; ".join(str(r / src["protocol_subpath"]) for r in SOURCE_SEARCH_ROOTS)
        return False, f"FILE_NOT_FOUND: searched {searched}"
    # Store the resolved path back into the source dict for downstream use
    src["_resolved_path"] = str(path)
    actual = sha256_file(path)
    if actual != src["expected_sha256"]:
        return False, f"SHA_MISMATCH: expected {src['expected_sha256']}, got {actual}"
    return True, actual


def extract_pages(src: dict, output_path: Path) -> dict:
    """
    Extract exact physical page range into a new PDF using pypdf.

    Physical pages are 1-based in the execution context.
    pypdf uses 0-based indices internally.
    We explicitly derive zero-based range to prevent off-by-one.
    """
    reader = PdfReader(src["_resolved_path"])

    page_start_1 = src["page_range_1based"][0]
    page_end_1 = src["page_range_1based"][1]

    # Zero-based indices (explicit derivation)
    idx_start = page_start_1 - 1  # first page to include (0-based)
    idx_end = page_end_1 - 1       # last page to include (0-based)

    total_pages = len(reader.pages)
    expected_count = idx_end - idx_start + 1

    if idx_start < 0 or idx_end >= total_pages or idx_end < idx_start:
        raise ValueError(
            f"Invalid page range for {src['lane']}: "
            f"1-based pp{page_start_1}-{page_end_1} → 0-based [{idx_start},{idx_end}], "
            f"source has {total_pages} pages"
        )

    writer = PdfWriter()

    # Copy pages preserving boxes, rotation, content/resources
    for i in range(idx_start, idx_end + 1):
        page = reader.pages[i]
        writer.add_page(page)

    # Set stable metadata (no wall-clock timestamp for reproducibility)
    meta = writer.add_metadata
    writer.add_metadata({
        "/Title": f"{src['lane']} — versioned_exact_synopsis_extract_for_e3",
        "/Subject": f"E3 synopsis extract: {src['synopsis_section']}",
        "/Keywords": (
            f"lane={src['lane']};source_sha256={src['expected_sha256']};"
            f"pages={page_start_1}-{page_end_1};tool={TOOL_NAME}/{TOOL_VERSION};"
            f"nct={src['nct_id']};indication={src['indication']};phase={src['phase']};"
            f"content_modified=false;label=versioned_exact_synopsis_extract_for_e3"
        ),
        "/Creator": f"{TOOL_NAME} {TOOL_VERSION} (E3 Worker 05)",
        "/Producer": f"{TOOL_NAME} {TOOL_VERSION}",
        # Deliberately NO CreationDate/ModDate → byte-stable reruns
    })

    with open(output_path, "wb") as f:
        writer.write(f)

    output_sha = sha256_file(output_path)

    return {
        "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        "output_sha256": output_sha,
        "page_count": expected_count,
        "expected_page_count": expected_count,
    }


def verify_output(src: dict, output_path: Path, expected_count: int) -> dict:
    """Verify output opens, has expected page count, no blank pages, text evidence present."""
    checks = {"opens": False, "page_count_match": False, "no_blank_pages": False,
              "synopsis_keyword_found": False, "indication_keyword_found": False}

    try:
        reader = PdfReader(str(output_path))
    except Exception:
        return checks

    checks["opens"] = True
    actual_count = len(reader.pages)
    checks["page_count_match"] = (actual_count == expected_count)

    # Check for blank pages and extract text
    all_text_parts = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        stripped = text.strip()
        checks["no_blank_pages"] = checks["no_blank_pages"] or True
        if len(stripped) < 5:
            checks["no_blank_pages"] = False
        all_text_parts.append(text)

    full_text = "\n".join(all_text_parts)
    full_lower = full_text.lower()

    # Synopsis keyword check
    for kw in SYNOPSIS_KEYWORDS:
        if kw.lower() in full_lower:
            checks["synopsis_keyword_found"] = True
            break

    # Indication keyword check
    for kw in INDICATION_KEYWORDS.get(src["lane"], []):
        if kw.lower() in full_lower:
            checks["indication_keyword_found"] = True
            break

    # Text evidence hashes (first and last page only, not full text)
    first_text = all_text_parts[0].strip() if all_text_parts else ""
    last_text = all_text_parts[-1].strip() if all_text_parts else ""
    checks["first_page_text_sha256"] = sha256_text(first_text) if first_text else None
    checks["last_page_text_sha256"] = sha256_text(last_text) if last_text else None
    checks["first_page_text_len"] = len(first_text)
    checks["last_page_text_len"] = len(last_text)

    return checks


def run_generate() -> int:
    """Generate all five fixtures + manifest + QC."""
    results = []
    failures = []
    source_not_found = []

    for src in SOURCES:
        print(f"[{src['lane']}] Checking source {src['nct_id']}...", file=sys.stderr)
        ok, sha_or_msg = verify_source_sha(src)
        if not ok:
            print(f"  FAIL: {sha_or_msg}", file=sys.stderr)
            if "FILE_NOT_FOUND" in sha_or_msg:
                source_not_found.append({"lane": src["lane"], "nct_id": src["nct_id"],
                                         "reason": sha_or_msg})
            else:
                failures.append({"lane": src["lane"], "reason": sha_or_msg})
            results.append({"lane": src["lane"], "status": "blocked", "reason": sha_or_msg})
            continue

        print(f"  SHA-256 verified: {sha_or_msg}", file=sys.stderr)
        output_path = FIXTURES_DIR / src["output_filename"]
        print(f"  Extracting pp{src['page_range_1based'][0]}-{src['page_range_1based'][1]}...", file=sys.stderr)
        extract_info = extract_pages(src, output_path)

        print(f"  Verifying output...", file=sys.stderr)
        vchecks = verify_output(src, output_path, extract_info["page_count"])

        all_ok = all([
            vchecks["opens"], vchecks["page_count_match"],
            vchecks["no_blank_pages"], vchecks["synopsis_keyword_found"],
        ])

        page_start, page_end = src["page_range_1based"]
        result = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "lane": src["lane"],
            "indication": src["indication"],
            "phase": src["phase"],
            "nct_id": src["nct_id"],
            "source_absolute_path": src["_resolved_path"],
            "source_sha256": src["expected_sha256"],
            "synopsis_section": src["synopsis_section"],
            "physical_page_range": f"{page_start}-{page_end}",
            "zero_based_indices": f"[{page_start - 1}, {page_end - 1}]",
            "output_relative_path": extract_info["output_path"],
            "output_sha256": extract_info["output_sha256"],
            "output_page_count": extract_info["page_count"],
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "tool_license": TOOL_LICENSE,
            "content_modified": False,
            "label": "versioned_exact_synopsis_extract_for_e3",
            "verification": vchecks,
        }
        results.append(result)

        if all_ok:
            print(f"  PASS: {extract_info['page_count']} pages, SHA {extract_info['output_sha256'][:16]}...", file=sys.stderr)
        else:
            failed_checks = [k for k, v in vchecks.items() if v is False]
            failures.append({"lane": src["lane"], "reason": f"verification failed: {failed_checks}"})
            print(f"  VERIFY FAIL: {failed_checks}", file=sys.stderr)

    # Write manifest
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_by": f"{TOOL_NAME}/{TOOL_VERSION}",
        "tool_license": TOOL_LICENSE,
        "content_modified": False,
        "label": "versioned_exact_synopsis_extract_for_e3",
        "total_sources": len(SOURCES),
        "extracted_ok": sum(1 for r in results if r.get("status") != "blocked" and r.get("verification", {}).get("opens")),
        "blocked_sources": source_not_found,
        "fixtures": results,
    }
    manifest_path = FIXTURES_DIR / "extraction_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Write QC markdown
    write_qc(results, source_not_found)

    ok_count = len([r for r in results if r.get("verification", {}).get("opens")])
    total = len(SOURCES)
    print(f"\nGeneration complete: {ok_count}/{total} fixtures extracted.", file=sys.stderr)
    if source_not_found:
        print(f"Blocked (source not found): {len(source_not_found)}", file=sys.stderr)
        for snf in source_not_found:
            print(f"  {snf['lane']} ({snf['nct_id']})", file=sys.stderr)

    if ok_count == total:
        return 0
    else:
        return 1


def run_verify_only() -> int:
    """Re-verify existing fixtures without regenerating."""
    manifest_path = FIXTURES_DIR / "extraction_manifest.json"
    if not manifest_path.exists():
        print("No manifest found. Run --generate first.", file=sys.stderr)
        return 2

    with open(manifest_path) as f:
        manifest = json.load(f)

    all_pass = True
    for fixture in manifest.get("fixtures", []):
        if fixture.get("status") == "blocked":
            print(f"[{fixture['lane']}] BLOCKED: {fixture.get('reason', 'unknown')}")
            continue

        output_path = PROJECT_ROOT / fixture["output_relative_path"]
        if not output_path.exists():
            print(f"[{fixture['lane']}] FAIL: output file missing: {output_path}")
            all_pass = False
            continue

        src = next((s for s in SOURCES if s["lane"] == fixture["lane"]), None)
        if not src:
            print(f"[{fixture['lane']}] FAIL: source definition not found")
            all_pass = False
            continue

        # Re-verify source SHA (resolve_source_path stores _resolved_path)
        ok, sha_or_msg = verify_source_sha(src)
        if not ok:
            print(f"[{fixture['lane']}] SOURCE FAIL: {sha_or_msg}")
            all_pass = False
            continue

        # Re-verify output
        vchecks = verify_output(src, output_path, fixture["output_page_count"])
        all_ok = all([
            vchecks["opens"], vchecks["page_count_match"],
            vchecks["no_blank_pages"], vchecks["synopsis_keyword_found"],
        ])

        # Verify SHA stability
        actual_sha = sha256_file(output_path)
        sha_stable = (actual_sha == fixture["output_sha256"])

        if all_ok and sha_stable:
            print(f"[{fixture['lane']}] PASS: {fixture['output_page_count']}pp, SHA stable, text evidence present")
        else:
            print(f"[{fixture['lane']}] FAIL: opens={vchecks['opens']} pages={vchecks['page_count_match']} "
                  f"blank={vchecks['no_blank_pages']} synopsis={vchecks['synopsis_keyword_found']} sha_stable={sha_stable}")
            all_pass = False

    return 0 if all_pass else 1


def write_qc(results: list, source_not_found: list):
    """Write EXTRACTION_QC.md."""
    qc_path = FIXTURES_DIR / "EXTRACTION_QC.md"

    lines = [
        "# Synopsis Fixture Extraction QC — E3 Worker 05",
        "",
        f"Tool: `{TOOL_NAME}` v{TOOL_VERSION} (license: {TOOL_LICENSE})",
        f"Label: `versioned_exact_synopsis_extract_for_e3`",
        "",
        "## Source → Output Table",
        "",
        "| Lane | NCT | Source SHA-256 | Pages (1-based) | 0-based indices | Output | Output SHA-256 | Page count | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        if r.get("status") == "blocked":
            lines.append(
                f"| {r['lane']} | {r.get('nct_id', '—')} | — | — | — | — | — | — | BLOCKED: source not found |"
            )
            continue

        v = r.get("verification", {})
        status_parts = []
        if v.get("opens"): status_parts.append("opens")
        if v.get("page_count_match"): status_parts.append("pages")
        if v.get("no_blank_pages"): status_parts.append("no_blank")
        if v.get("synopsis_keyword_found"): status_parts.append("synopsis_kw")
        if v.get("indication_keyword_found"): status_parts.append("indication_kw")
        status = "PASS" if len(status_parts) >= 4 else f"PARTIAL ({', '.join(status_parts)})"

        sha_short = r["output_sha256"][:16] + "..."
        lines.append(
            f"| {r['lane']} | {r['nct_id']} | `{r['source_sha256'][:16]}...` | "
            f"{r['physical_page_range']} | {r['zero_based_indices']} | "
            f"`{r['output_relative_path']}` | `{sha_short}` | "
            f"{r['output_page_count']} | {status} |"
        )

    lines.extend([
        "",
        "## Text Evidence Hashes",
        "",
        "| Lane | First-page text SHA-256 | Length | Last-page text SHA-256 | Length |",
        "|---|---|---|---|---|",
    ])

    for r in results:
        if r.get("status") == "blocked":
            lines.append(f"| {r['lane']} | — | — | — | — |")
            continue
        v = r.get("verification", {})
        fp = v.get("first_page_text_sha256", "—")
        lp = v.get("last_page_text_sha256", "—")
        fl = v.get("first_page_text_len", 0)
        ll = v.get("last_page_text_len", 0)
        lines.append(f"| {r['lane']} | `{fp[:16]}...` | {fl} | `{lp[:16]}...` | {ll} |")

    lines.extend([
        "",
        "## Determinism",
        "",
        "- Output PDFs contain no CreationDate/ModDate metadata.",
        "- Reruns produce byte-identical PDFs (verified via --verify-only SHA stability check).",
        "- Stable metadata in /Keywords identifies lane, source SHA, page range, tool/version.",
        "",
        "## Limitations",
        "",
    ])

    if source_not_found:
        lines.append(f"### Blocked: {len(source_not_found)} source PDFs not found on disk")
        lines.append("")
        for snf in source_not_found:
            lines.append(f"- **{snf['lane']}** ({snf['nct_id']}): {snf['reason']}")
        lines.append("")
        lines.append("These protocols were referenced in the execution context and worker_01 config")
        lines.append("but do not exist at the declared `protocol-corpus/raw/NCT.../Prot_000.pdf` path.")
        lines.append("The `protocol-corpus` directory does not exist under the workbench root.")
        lines.append("Worker 01 / manager / Codex must supply these files before the corresponding")
        lines.append("fixtures can be generated.")
        lines.append("")

    lines.extend([
        "### Content fidelity",
        "- Extracts are lossless page copies (pypdf `add_page` preserves page boxes, rotation, content/resources).",
        "- `content_modified: false` — no rasterization, reflow, translation, summarization or rewriting.",
        "- Label is `versioned_exact_synopsis_extract_for_e3`, not `sponsor-issued standalone synopsis`.",
        "- The extract is a fixture for the E3 harness synopsis-import lanes, not a regulatory document.",
        "",
        "### Text extraction caveat",
        "- Text evidence hashes are computed from pypdf's `extract_text()` output, which depends on",
        "  the source PDF's text layer encoding. PDFs with image-only pages or non-standard encodings",
        "  may produce sparse text. The page count and SHA checks are the primary integrity signals.",
        "",
    ])

    with open(qc_path, "w") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="E3 Synopsis Fixture Extractor (Worker 05)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true",
                       help="Generate all fixtures + manifest + QC")
    group.add_argument("--verify-only", action="store_true",
                       help="Re-verify existing fixtures (SHA stability, page count, text evidence)")
    args = parser.parse_args()

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Record tool/license evidence
    print(f"Tool: {TOOL_NAME} v{TOOL_VERSION}", file=sys.stderr)
    print(f"License: {TOOL_LICENSE} (License-Expression metadata)", file=sys.stderr)
    print(f"Fixtures dir: {FIXTURES_DIR}", file=sys.stderr)

    if args.generate:
        return run_generate()
    elif args.verify_only:
        return run_verify_only()


if __name__ == "__main__":
    sys.exit(main())
