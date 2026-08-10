from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from pocs.protocol_v3.word_receipt.contract import validate_receipt
from pocs.protocol_v3.word_receipt.producers.applescript_bridge import (
    _lineage_for_request,
    _reconcile_completed_word_invocation,
    _word_script,
    finalize_visual_qc,
    producer_identity,
)
from pocs.protocol_v3.word_receipt.producers.base import (
    ProducerFunctionalError,
    ProducerRequest,
    atomic_write_json_once,
    inspect_docx_ooxml,
    normalized_ooxml_fingerprint,
    page_manifest,
    render_pdf_page_evidence,
    select_bookmark_checks,
    select_cross_reference_checks,
    sha256_file,
)
from pocs.protocol_v3.word_receipt.roundtrip_lineage import (
    EXTERNAL_EDIT,
    LINEAGE_MANIFEST,
    REEXPORTED,
    prepare_roundtrip,
    stage_reimport,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures.json"


def _write_docx(path: Path, *, text: str, rsid: str, modified: str) -> None:
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p w:rsidR="{rsid}">
      <w:bookmarkStart w:id="1" w:name="bm_target"/>
      <w:r><w:rPr><w:rFonts w:eastAsia="宋体" w:ascii="Times New Roman"/></w:rPr><w:t>{text}</w:t></w:r>
      <w:bookmarkEnd w:id="1"/>
    </w:p>
    <w:p>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText>PAGEREF bm_target \\h</w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>1</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
    <w:p>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText>TOC \\o "1-3" \\h</w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>目录</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
    <w:sectPr/>
  </w:body>
</w:document>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    core = f'''<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/">
  <dcterms:modified>{modified}</dcterms:modified>
</cp:coreProperties>'''
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)


def _write_pdf(path: Path, page_count: int) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)


def test_ooxml_inspection_finds_word_objects(tmp_path: Path):
    docx = tmp_path / "fixture.docx"
    _write_docx(docx, text="研究目的", rsid="00112233", modified="2026-08-10")
    facts = inspect_docx_ooxml(docx)
    assert facts["field_count"] == 2
    assert facts["toc_count"] == 1
    assert facts["fonts"] == ["Times New Roman", "宋体"]
    assert facts["bookmarks"][0]["name"] == "bm_target"
    assert facts["bookmarks"][0]["target_text"] == "研究目的"
    assert facts["fields"][0]["instruction"] == "PAGEREF bm_target \\h"
    assert facts["fields"][0]["result"] == "1"


def test_normalized_ooxml_ignores_declared_word_volatility_only(tmp_path: Path):
    first = tmp_path / "first.docx"
    volatile_change = tmp_path / "volatile-change.docx"
    semantic_change = tmp_path / "semantic-change.docx"
    _write_docx(first, text="研究目的", rsid="00112233", modified="2026-08-10")
    _write_docx(
        volatile_change,
        text="研究目的",
        rsid="AABBCCDD",
        modified="2026-08-11",
    )
    _write_docx(
        semantic_change,
        text="研究终点",
        rsid="AABBCCDD",
        modified="2026-08-11",
    )
    assert normalized_ooxml_fingerprint(first)["sha256"] == normalized_ooxml_fingerprint(
        volatile_change
    )["sha256"]
    assert normalized_ooxml_fingerprint(first)["sha256"] != normalized_ooxml_fingerprint(
        semantic_change
    )["sha256"]


def test_normalized_ooxml_handles_word_relative_namespace_custom_xml(tmp_path: Path):
    docx = tmp_path / "relative-namespace.docx"
    _write_docx(docx, text="研究目的", rsid="00112233", modified="2026-08-10")
    with ZipFile(docx, "a", ZIP_DEFLATED) as archive:
        archive.writestr(
            "customXml/item1.xml",
            '<?xml version="1.0"?><x:root xmlns:x="a68fe43b-4f92-446d-947a-4942a6cb3c41" x:value="kept"/>',
        )
    first = normalized_ooxml_fingerprint(docx)
    second = normalized_ooxml_fingerprint(docx)
    assert first == second
    assert first["normalizer_version"] == "protocol-v3-ooxml-normalizer-poc-v2"


def test_bookmark_and_cross_reference_checks_bind_real_targets(tmp_path: Path):
    before = tmp_path / "before.docx"
    after = tmp_path / "after.docx"
    _write_docx(before, text="研究目的", rsid="00112233", modified="2026-08-10")
    _write_docx(after, text="研究目的", rsid="AABBCCDD", modified="2026-08-11")
    before_facts = inspect_docx_ooxml(before)
    after_facts = inspect_docx_ooxml(after)
    bookmark_checks = select_bookmark_checks(before_facts, after_facts)
    reference_checks = select_cross_reference_checks(after_facts)
    assert bookmark_checks[0]["expected_target"] == bookmark_checks[0]["observed_target"]
    assert reference_checks[0]["target_bookmark"] == "bm_target"
    assert reference_checks[0]["rendered_text"] == "1"


def test_page_renderer_is_local_permissive_and_complete(tmp_path: Path):
    pdf = tmp_path / "fixture.pdf"
    _write_pdf(pdf, 2)
    pages, producer = render_pdf_page_evidence(pdf, tmp_path / "pages")
    assert [page["page_number"] for page in pages] == [1, 2]
    assert all((tmp_path / "pages" / f"page-{index:04d}.png").is_file() for index in (1, 2))
    assert producer["license_spdx"] == "Apache-2.0 OR BSD-3-Clause"
    assert producer["data_egress"] == "none"
    assert len(page_manifest(pdf, pages)) == 64


def test_atomic_json_artifact_is_never_overwritten(tmp_path: Path):
    target = tmp_path / "event.json"
    atomic_write_json_once(target, {"revision": 1})
    with pytest.raises(ProducerFunctionalError) as raised:
        atomic_write_json_once(target, {"revision": 2})
    assert raised.value.code == "WR_ARTIFACT_EXISTS"
    assert json.loads(target.read_text()) == {"revision": 1}


def test_applescript_is_target_scoped_and_compiles(tmp_path: Path):
    script = _word_script(
        tmp_path / "input.docx",
        tmp_path / "word-saved.docx",
        tmp_path / "word-export.pdf",
    )
    assert "read only true repair false" in script
    assert "close targetDoc saving no" in script
    assert "close every document" not in script
    assert "set storyTypes to {1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17}" in script
    assert "set headerFooterTypes to {1, 2, 3}" in script
    assert "get header" in script and "get footer" in script
    assert "countAllStoryFields" in script
    assert "updateAllStoryFields" in script
    assert script.count("get story range") >= 2
    if shutil.which("osacompile"):
        source = tmp_path / "producer.applescript"
        compiled = tmp_path / "producer.scpt"
        source.write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["osacompile", "-o", str(compiled), str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_producer_identity_is_source_bound():
    identity = producer_identity()
    assert identity["producer_type"] == "applescript_bridge"
    assert len(identity["implementation_sha256"]) == 64


def test_completed_word_invocation_resumes_postprocessing_without_replay(tmp_path: Path):
    run_dir = tmp_path / "run"
    events = run_dir / "events"
    events.mkdir(parents=True)
    source = b"source-docx"
    (run_dir / "input.docx").write_bytes(source)
    (run_dir / "word-saved.docx").write_bytes(b"saved-docx")
    (run_dir / "word-export.pdf").write_bytes(b"word-pdf")
    source_hash = sha256_file(run_dir / "input.docx")
    producer = producer_identity()
    atomic_write_json_once(
        events / "001-reserved.json",
        {
            "event": "reserved",
            "started_at": "2026-08-10T00:00:00Z",
            "source_sha256": source_hash,
            "idempotency_key": "idem-fixed",
            "receipt_id": "receipt-fixed",
            "edit_reimport_export_lineage": {
                "mode": "no_external_edit",
                "source_artifact_id": "word-input-source",
                "source_artifact_sha256": source_hash,
                "edited_artifact_id": "",
                "edited_artifact_sha256": "",
                "reimported_artifact_id": "",
                "reimported_artifact_sha256": "",
                "merged_semantic_revision": "",
                "reexport_artifact_id": "",
                "reexport_artifact_sha256": "",
            },
            "producer_identity": producer,
            "word_inventory_before": {"documents": []},
        },
    )
    atomic_write_json_once(
        events / "002-word-invocation.json",
        {
            "event": "word_invocation_returned",
            "exit_code": 0,
            "stdout": "OPEN_WITHOUT_REPAIR=true\nREOPEN_PASS=true",
            "stderr": "",
        },
    )
    inventory, started_at, word_result = _reconcile_completed_word_invocation(
        run_dir=run_dir,
        source_hash=source_hash,
        producer=producer,
        idempotency_key="idem-fixed",
        receipt_id="receipt-fixed",
        expected_lineage={
            "mode": "no_external_edit",
            "source_artifact_id": "word-input-source",
            "source_artifact_sha256": source_hash,
            "edited_artifact_id": "",
            "edited_artifact_sha256": "",
            "reimported_artifact_id": "",
            "reimported_artifact_sha256": "",
            "merged_semantic_revision": "",
            "reexport_artifact_id": "",
            "reexport_artifact_sha256": "",
        },
    )
    assert inventory == {"documents": []}
    assert started_at == "2026-08-10T00:00:00Z"
    assert word_result["reopen_pass"] == "true"

    stale_producer = dict(producer, implementation_sha256="0" * 64)
    with pytest.raises(ProducerFunctionalError) as raised:
        _reconcile_completed_word_invocation(
            run_dir=run_dir,
            source_hash=source_hash,
            producer=stale_producer,
            idempotency_key="idem-fixed",
            receipt_id="receipt-fixed",
            expected_lineage={
                "mode": "no_external_edit",
                "source_artifact_id": "word-input-source",
                "source_artifact_sha256": source_hash,
                "edited_artifact_id": "",
                "edited_artifact_sha256": "",
                "reimported_artifact_id": "",
                "reimported_artifact_sha256": "",
                "merged_semantic_revision": "",
                "reexport_artifact_id": "",
                "reexport_artifact_sha256": "",
            },
        )
    assert raised.value.code == "WR_UNKNOWN_OUTCOME"

    stale_lineage = {
        "mode": "no_external_edit",
        "source_artifact_id": "word-input-source",
        "source_artifact_sha256": source_hash,
        "edited_artifact_id": "",
        "edited_artifact_sha256": "",
        "reimported_artifact_id": "",
        "reimported_artifact_sha256": "",
        "merged_semantic_revision": "semantic-r3",
        "reexport_artifact_id": "",
        "reexport_artifact_sha256": "",
    }
    with pytest.raises(ProducerFunctionalError) as stale:
        _reconcile_completed_word_invocation(
            run_dir=run_dir,
            source_hash=source_hash,
            producer=producer,
            idempotency_key="idem-fixed",
            receipt_id="receipt-fixed",
            expected_lineage=stale_lineage,
        )
    assert stale.value.code == "WR_LINEAGE_STALE"


def test_visual_qc_finalization_requires_every_page_and_is_replayable(tmp_path: Path):
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    candidate = deepcopy(fixture)
    for page in candidate["page_evidence"]:
        page["visual_qc_status"] = "pending_visual_qc"
    pdf = tmp_path / "word-export.pdf"
    _write_pdf(pdf, 2)
    candidate["pdf_sha256"] = sha256_file(pdf)
    candidate["pdf_artifact_id"] = f"word-pdf-{candidate['pdf_sha256'][:20]}"
    (tmp_path / "receipt_candidate.json").write_text(
        json.dumps(candidate, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ProducerFunctionalError) as raised:
        finalize_visual_qc(tmp_path, passed_pages=[1])
    assert raised.value.code == "WR_VISUAL_QC_INCOMPLETE"

    completed = finalize_visual_qc(tmp_path, passed_pages=[1, 2])
    assert completed["status"] == "completed"
    validate_receipt(completed["receipt"])
    replayed = finalize_visual_qc(tmp_path, passed_pages=[1, 2])
    assert replayed["status"] == "replayed"


def test_roundtrip_staging_is_immutable_and_binds_external_edit(tmp_path: Path):
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))["valid_receipt"]
    source_run = tmp_path / "source-run"
    source_run.mkdir()
    saved = source_run / "word-saved.docx"
    saved.write_bytes(b"initial Word export")
    saved_hash = sha256_file(saved)
    fixture["saved_artifact_id"] = f"word-saved-{saved_hash[:20]}"
    fixture["saved_docx_sha256"] = saved_hash
    fixture["normalized_ooxml_fingerprint"]["artifact_id"] = fixture["saved_artifact_id"]
    fixture["normalized_ooxml_fingerprint"]["artifact_sha256"] = saved_hash
    (source_run / "receipt.json").write_text(json.dumps(fixture), encoding="utf-8")

    roundtrip_dir = tmp_path / "roundtrip"
    prepared = prepare_roundtrip(source_run, roundtrip_dir)
    assert prepared["status"] == "prepared_for_external_word_edit"
    assert prepare_roundtrip(source_run, roundtrip_dir)["status"] == "replayed"

    with pytest.raises(ProducerFunctionalError) as unchanged:
        stage_reimport(roundtrip_dir, merged_semantic_revision="semantic-r2")
    assert unchanged.value.code == "WR_EXTERNAL_EDIT_MISSING"

    edited = roundtrip_dir / EXTERNAL_EDIT
    edited.write_bytes(edited.read_bytes() + b" wording-only edit")
    staged = stage_reimport(roundtrip_dir, merged_semantic_revision="semantic-r2")
    lineage = staged["lineage"]
    assert staged["status"] == "staged_for_word_verification"
    assert (roundtrip_dir / LINEAGE_MANIFEST).is_file()
    assert sha256_file(roundtrip_dir / REEXPORTED) == lineage["reexport_artifact_sha256"]
    assert len(
        {
            lineage["source_artifact_id"],
            lineage["edited_artifact_id"],
            lineage["reimported_artifact_id"],
            lineage["reexport_artifact_id"],
        }
    ) == 4
    assert stage_reimport(
        roundtrip_dir, merged_semantic_revision="semantic-r2"
    )["status"] == "replayed"
    with pytest.raises(ProducerFunctionalError) as stale_revision:
        stage_reimport(roundtrip_dir, merged_semantic_revision="semantic-r3")
    assert stale_revision.value.code == "WR_LINEAGE_STALE"


def test_producer_external_lineage_must_bind_current_reexport(tmp_path: Path):
    source = tmp_path / "reexport.docx"
    source.write_bytes(b"reexport")
    source_hash = sha256_file(source)
    input_artifact_id = f"word-input-{source_hash[:20]}"
    lineage = {
        "mode": "edit_reimport_export",
        "source_artifact_id": "word-saved-source",
        "source_artifact_sha256": "1" * 64,
        "edited_artifact_id": "word-external-edit",
        "edited_artifact_sha256": "2" * 64,
        "reimported_artifact_id": "word-reimport",
        "reimported_artifact_sha256": "2" * 64,
        "merged_semantic_revision": "semantic-r2",
        "reexport_artifact_id": input_artifact_id,
        "reexport_artifact_sha256": source_hash,
    }
    request = ProducerRequest(
        label="roundtrip",
        source_path=source,
        results_root=tmp_path,
        source_snapshot_sha256=source_hash,
        semantic_document_revision="semantic-r2",
        template_revision="template-r1",
        edit_reimport_export_lineage=lineage,
    )
    assert _lineage_for_request(
        request,
        input_artifact_id=input_artifact_id,
        input_hash=source_hash,
    ) == lineage
    bad = dict(lineage, reexport_artifact_sha256="3" * 64)
    bad_request = ProducerRequest(
        label=request.label,
        source_path=request.source_path,
        results_root=request.results_root,
        source_snapshot_sha256=request.source_snapshot_sha256,
        semantic_document_revision=request.semantic_document_revision,
        template_revision=request.template_revision,
        edit_reimport_export_lineage=bad,
    )
    with pytest.raises(ProducerFunctionalError) as raised:
        _lineage_for_request(
            bad_request,
            input_artifact_id=input_artifact_id,
            input_hash=source_hash,
        )
    assert raised.value.code == "WR_LINEAGE_REEXPORT"
