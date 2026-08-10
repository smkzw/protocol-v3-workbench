"""Recoverable Microsoft Word for Mac producer implemented through AppleScript.

Only task-owned DOCX copies are opened.  Existing user documents are inventoried
before and after but never closed, saved, or edited by this bridge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from pocs.protocol_v3.word_receipt.contract import (
    SCHEMA_VERSION,
    VERIFICATION_ENGINE,
    VERIFICATION_STATUS,
    WORKFLOW,
    assert_receipt_current,
    compute_idempotency_key,
    compute_receipt_id,
    validate_receipt,
)
from pocs.protocol_v3.word_receipt.producers.base import (
    ProducerFunctionalError,
    ProducerRequest,
    atomic_write_json_once,
    font_environment,
    inspect_docx_ooxml,
    normalized_ooxml_fingerprint,
    page_manifest,
    render_pdf_page_evidence,
    select_bookmark_checks,
    select_cross_reference_checks,
    sha256_file,
)


WORD_APP = Path("/Applications/Microsoft Word.app")
_SAFE_LABEL = re.compile(r"[^A-Za-z0-9_.-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _apple_text(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _run_applescript(script: str, *, timeout: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            ["osascript"],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, stdout.strip(), f"{stderr.strip()} TIMEOUT".strip()


def _parse_lines(output: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"raw": output}
    documents: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "DOC_NAME":
            current = {"name": value}
            documents.append(current)
        elif key == "DOC_PATH" and current is not None:
            current["path"] = value
        elif key == "DOC_SAVED" and current is not None:
            current["saved"] = value
        else:
            parsed[key.lower()] = value
    if documents:
        parsed["documents"] = documents
    return parsed


def word_inventory() -> dict[str, Any]:
    """Read installed/running Word state without opening or saving a document."""

    if not WORD_APP.is_dir():
        raise ProducerFunctionalError("WR_WORD_UNAVAILABLE", str(WORD_APP))
    script = r'''
tell application "Microsoft Word"
  set outputText to "VERSION=" & (version as text) & linefeed
  set outputText to outputText & "DOC_COUNT=" & (count of documents) & linefeed
  repeat with i from 1 to (count of documents)
    set outputText to outputText & "DOC_NAME=" & (name of document i as text) & linefeed
    try
      set outputText to outputText & "DOC_PATH=" & (full name of document i as text) & linefeed
    on error
      set outputText to outputText & "DOC_PATH=<unavailable>" & linefeed
    end try
    try
      set outputText to outputText & "DOC_SAVED=" & (saved of document i as text) & linefeed
    on error
      set outputText to outputText & "DOC_SAVED=<unavailable>" & linefeed
    end try
  end repeat
  return outputText
end tell
'''
    code, stdout, stderr = _run_applescript(script, timeout=30)
    if code != 0:
        raise ProducerFunctionalError(
            "WR_WORD_INVENTORY", f"code={code}; stderr={stderr}; stdout={stdout}"
        )
    result = _parse_lines(stdout)
    result["captured_at"] = _utc_now()
    result["bundle_path"] = str(WORD_APP)
    return result


def producer_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    files = [
        Path(__file__).resolve(),
        Path(__file__).with_name("base.py").resolve(),
        root / "contract.py",
        root / "roundtrip_lineage.py",
    ]
    digest = sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(bytes.fromhex(sha256_file(path)))
    return {
        "producer_id": "protocol-v3-word-mac-applescript-poc",
        "producer_type": "applescript_bridge",
        "producer_version": "poc-v1",
        "implementation_sha256": digest.hexdigest(),
    }


def _word_script(input_path: Path, saved_path: Path, pdf_path: Path) -> str:
    input_name = input_path.name
    saved_name = saved_path.name
    return f'''
set inputFile to POSIX file {_apple_text(str(input_path))}
set outputDocx to {_apple_text(str(saved_path))}
set outputPdf to {_apple_text(str(pdf_path))}
set inputName to {_apple_text(input_name)}
set outputName to {_apple_text(saved_name)}
set savedFile to POSIX file outputDocx
set targetDoc to missing value
set reopenedDoc to missing value

using terms from application "Microsoft Word"
on appendLine(currentText, keyText, valueText)
  return currentText & keyText & "=" & (valueText as text) & linefeed
end appendLine

on countAllStoryFields(d)
  local r, t, s, idx, hf, tr, fieldItems, storyTypes, headerFooterTypes, totalFields, totalStories
  tell application "Microsoft Word"
    -- Headers and footers (story types 6..11) are enumerated explicitly per
    -- section because Word 16.111 for Mac fails when next story range has a
    -- successor. The remaining document-level stories are obtained directly.
    set storyTypes to {{1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17}}
    set headerFooterTypes to {{1, 2, 3}}
    set totalFields to 0
    set totalStories to 0
    repeat with t in storyTypes
      set r to missing value
      try
        set r to get story range d story type (contents of t)
      on error
        set r to missing value
      end try
      if r is not missing value then
        set totalStories to totalStories + 1
        set fieldItems to get fields of r
        set totalFields to totalFields + (count of fieldItems)
      end if
    end repeat
    repeat with s in (get sections of d)
      repeat with idx in headerFooterTypes
        try
          set hf to get header (contents of s) index (contents of idx)
          set tr to text object of hf
          set fieldItems to get fields of tr
          set totalFields to totalFields + (count of fieldItems)
          set totalStories to totalStories + 1
        end try
        try
          set hf to get footer (contents of s) index (contents of idx)
          set tr to text object of hf
          set fieldItems to get fields of tr
          set totalFields to totalFields + (count of fieldItems)
          set totalStories to totalStories + 1
        end try
      end repeat
    end repeat
    return {{totalFields, totalStories}}
  end tell
end countAllStoryFields

on updateAllStoryFields(d)
  local r, t, s, idx, hf, tr, f, fieldItems, updateOkay, storyTypes, headerFooterTypes, updatedFields, updateErrors, totalStories
  tell application "Microsoft Word"
    set storyTypes to {{1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17}}
    set headerFooterTypes to {{1, 2, 3}}
    set updatedFields to 0
    set updateErrors to 0
    set totalStories to 0
    repeat with t in storyTypes
      set r to missing value
      try
        set r to get story range d story type (contents of t)
      on error
        set r to missing value
      end try
      if r is not missing value then
        set totalStories to totalStories + 1
        set fieldItems to get fields of r
        repeat with f in fieldItems
          try
            set updateOkay to update field (contents of f)
            if updateOkay is false then set updateErrors to updateErrors + 1
          on error
            set updateErrors to updateErrors + 1
          end try
          set updatedFields to updatedFields + 1
        end repeat
      end if
    end repeat
    repeat with s in (get sections of d)
      repeat with idx in headerFooterTypes
        set tr to missing value
        try
          set hf to get header (contents of s) index (contents of idx)
          set tr to text object of hf
        end try
        if tr is not missing value then
          set totalStories to totalStories + 1
          set fieldItems to get fields of tr
          repeat with f in fieldItems
            try
              set updateOkay to update field (contents of f)
              if updateOkay is false then set updateErrors to updateErrors + 1
            on error
              set updateErrors to updateErrors + 1
            end try
            set updatedFields to updatedFields + 1
          end repeat
        end if
        set tr to missing value
        try
          set hf to get footer (contents of s) index (contents of idx)
          set tr to text object of hf
        end try
        if tr is not missing value then
          set totalStories to totalStories + 1
          set fieldItems to get fields of tr
          repeat with f in fieldItems
            try
              set updateOkay to update field (contents of f)
              if updateOkay is false then set updateErrors to updateErrors + 1
            on error
              set updateErrors to updateErrors + 1
            end try
            set updatedFields to updatedFields + 1
          end repeat
        end if
      end repeat
    end repeat
    return {{updatedFields, updateErrors, totalStories}}
  end tell
end updateAllStoryFields

tell application "Microsoft Word"
  set outputText to ""
  try
    open inputFile read only true repair false showing repairs false
    repeat with i from 1 to (count of documents)
      if (name of document i as text) is inputName then
        set targetDoc to document i
        exit repeat
      end if
    end repeat
    if targetDoc is missing value then error "task input document not found after open"
    set outputText to my appendLine(outputText, "OPEN_WITHOUT_REPAIR", "true")
    set outputText to my appendLine(outputText, "WORD_VERSION", version as text)

    -- The handlers use documented numeric story types and enumerate every
    -- section's first/even/primary header and footer independently.
    set initialCounts to my countAllStoryFields(targetDoc)
    set outputText to my appendLine(outputText, "FIELD_COUNT_INITIAL", item 1 of initialCounts)
    set outputText to my appendLine(outputText, "STORY_RANGE_COUNT_INITIAL", item 2 of initialCounts)

    set tocItems to get tables of contents of targetDoc
    set tocCount to count of tocItems
    repeat with tocRef in tocItems
      update (contents of tocRef)
      update page numbers (contents of tocRef)
    end repeat
    set outputText to my appendLine(outputText, "TOC_COUNT", tocCount)

    -- TOC refresh can legitimately add or remove generated TOC fields. The
    -- contract's before/after count begins after that deterministic rebuild so
    -- it detects field loss across the subsequent update/save/reopen path.
    set beforeCounts to my countAllStoryFields(targetDoc)
    set outputText to my appendLine(outputText, "FIELD_COUNT_BEFORE", item 1 of beforeCounts)
    set outputText to my appendLine(outputText, "STORY_RANGE_COUNT_BEFORE", item 2 of beforeCounts)

    set updateCounts to my updateAllStoryFields(targetDoc)
    set outputText to my appendLine(outputText, "UPDATED_FIELD_COUNT", item 1 of updateCounts)
    set outputText to my appendLine(outputText, "FIELD_UPDATE_ERROR_COUNT", item 2 of updateCounts)
    set outputText to my appendLine(outputText, "STORY_RANGE_COUNT_UPDATED", item 3 of updateCounts)

    repaginate targetDoc
    set outputText to my appendLine(outputText, "REPAGINATE_PASS", "true")

    set unavailableList to {{}}
    try
      set unavailableList to unavailable fonts of targetDoc
    end try
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to "|||"
    set unavailableText to unavailableList as text
    set AppleScript's text item delimiters to oldDelimiters
    set outputText to my appendLine(outputText, "UNAVAILABLE_FONTS", unavailableText)

    save as targetDoc file name outputDocx file format format document default
    set outputText to my appendLine(outputText, "SAVE_PASS", "true")
    set targetDoc to missing value
    repeat with i from 1 to (count of documents)
      if (name of document i as text) is outputName then
        set targetDoc to document i
        exit repeat
      end if
    end repeat
    if targetDoc is missing value then error "Word-saved document object not found after Save As"
    save as targetDoc file name outputPdf file format format PDF
    set outputText to my appendLine(outputText, "PDF_PASS", "true")
    close targetDoc saving no
    set targetDoc to missing value

    open savedFile read only true repair false showing repairs false
    repeat with i from 1 to (count of documents)
      if (name of document i as text) is outputName then
        set reopenedDoc to document i
        exit repeat
      end if
    end repeat
    if reopenedDoc is missing value then error "Word-saved document not found after reopen"
    set afterCounts to my countAllStoryFields(reopenedDoc)
    set outputText to my appendLine(outputText, "FIELD_COUNT_AFTER", item 1 of afterCounts)
    set outputText to my appendLine(outputText, "STORY_RANGE_COUNT_AFTER", item 2 of afterCounts)
    set outputText to my appendLine(outputText, "REOPEN_PASS", "true")
    close reopenedDoc saving no
    set reopenedDoc to missing value
    return outputText
  on error errorMessage number errorNumber
    try
      if targetDoc is not missing value then close targetDoc saving no
    end try
    try
      if reopenedDoc is not missing value then close reopenedDoc saving no
    end try
    set cleanMessage to my replaceText(errorMessage, return, " ")
    set cleanMessage to my replaceText(cleanMessage, linefeed, " ")
    return outputText & "ERROR_CODE=" & errorNumber & linefeed & "ERROR_MESSAGE=" & cleanMessage
  end try
end tell

on replaceText(sourceText, searchText, replacementText)
  set oldDelimiters to AppleScript's text item delimiters
  set AppleScript's text item delimiters to searchText
  set sourceParts to text items of sourceText
  set AppleScript's text item delimiters to replacementText
  set resultText to sourceParts as text
  set AppleScript's text item delimiters to oldDelimiters
  return resultText
end replaceText
end using terms from
'''


def _identity(request: ProducerRequest, producer: Mapping[str, Any]) -> tuple[str, str]:
    input_hash = sha256_file(request.source_path)
    key = compute_idempotency_key(
        source_snapshot_sha256=request.source_snapshot_sha256,
        input_docx_sha256=input_hash,
        semantic_document_revision=request.semantic_document_revision,
        template_revision=request.template_revision,
        producer_identity=producer,
    )
    return key, compute_receipt_id(key)


def _run_dir(request: ProducerRequest, receipt_id: str) -> Path:
    safe_label = _SAFE_LABEL.sub("-", request.label).strip("-") or "word-poc"
    return request.results_root / f"{safe_label}-{receipt_id[-12:]}"


def _event_paths(run_dir: Path) -> list[Path]:
    events = run_dir / "events"
    return sorted(events.glob("*.json")) if events.is_dir() else []


def _current_identity(request: ProducerRequest) -> dict[str, str]:
    return {
        "source_snapshot_sha256": request.source_snapshot_sha256,
        "input_docx_sha256": sha256_file(request.source_path),
        "semantic_document_revision": request.semantic_document_revision,
        "template_revision": request.template_revision,
    }


def _lineage_for_request(
    request: ProducerRequest,
    *,
    input_artifact_id: str,
    input_hash: str,
) -> dict[str, str]:
    lineage = request.edit_reimport_export_lineage
    if lineage is None:
        return {
            "mode": "no_external_edit",
            "source_artifact_id": input_artifact_id,
            "source_artifact_sha256": input_hash,
            "edited_artifact_id": "",
            "edited_artifact_sha256": "",
            "reimported_artifact_id": "",
            "reimported_artifact_sha256": "",
            "merged_semantic_revision": "",
            "reexport_artifact_id": "",
            "reexport_artifact_sha256": "",
        }
    expected = {
        "mode",
        "source_artifact_id",
        "source_artifact_sha256",
        "edited_artifact_id",
        "edited_artifact_sha256",
        "reimported_artifact_id",
        "reimported_artifact_sha256",
        "merged_semantic_revision",
        "reexport_artifact_id",
        "reexport_artifact_sha256",
    }
    if set(lineage) != expected or lineage.get("mode") != "edit_reimport_export":
        raise ProducerFunctionalError(
            "WR_LINEAGE_MANIFEST", "external edit lineage has an unsupported shape"
        )
    result = {name: str(lineage[name]) for name in expected}
    if (
        result["reexport_artifact_id"] != input_artifact_id
        or result["reexport_artifact_sha256"] != input_hash
    ):
        raise ProducerFunctionalError(
            "WR_LINEAGE_REEXPORT", "lineage must bind the exact DOCX handed to Word"
        )
    if result["merged_semantic_revision"] != request.semantic_document_revision:
        raise ProducerFunctionalError(
            "WR_LINEAGE_REVISION", "lineage must bind the current semantic revision"
        )
    if len(
        {
            result["source_artifact_id"],
            result["edited_artifact_id"],
            result["reimported_artifact_id"],
            result["reexport_artifact_id"],
        }
    ) != 4:
        raise ProducerFunctionalError(
            "WR_LINEAGE_IMMUTABILITY", "lineage artifact identities must be distinct"
        )
    return result


def _reconcile_completed_word_invocation(
    *,
    run_dir: Path,
    source_hash: str,
    producer: Mapping[str, Any],
    idempotency_key: str,
    receipt_id: str,
    expected_lineage: Mapping[str, str],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Recover post-processing without replaying a completed Word invocation."""

    reserved_path = run_dir / "events" / "001-reserved.json"
    invocation_path = run_dir / "events" / "002-word-invocation.json"
    required_artifacts = (
        run_dir / "input.docx",
        run_dir / "word-saved.docx",
        run_dir / "word-export.pdf",
    )
    if not reserved_path.is_file() or not invocation_path.is_file():
        raise ProducerFunctionalError(
            "WR_UNKNOWN_OUTCOME", "reservation or Word completion event is missing"
        )
    if not all(path.is_file() for path in required_artifacts):
        raise ProducerFunctionalError(
            "WR_UNKNOWN_OUTCOME", "completed Word event lacks exact DOCX/PDF artifacts"
        )
    reserved = json.loads(reserved_path.read_text(encoding="utf-8"))
    invocation = json.loads(invocation_path.read_text(encoding="utf-8"))
    if reserved.get("source_sha256") != source_hash:
        raise ProducerFunctionalError("WR_SOURCE_CHANGED", "reserved source hash drifted")
    if sha256_file(required_artifacts[0]) != source_hash:
        raise ProducerFunctionalError("WR_SOURCE_CHANGED", "reserved input hash drifted")
    if reserved.get("idempotency_key") != idempotency_key:
        raise ProducerFunctionalError("WR_UNKNOWN_OUTCOME", "idempotency key mismatch")
    if reserved.get("receipt_id") != receipt_id:
        raise ProducerFunctionalError("WR_UNKNOWN_OUTCOME", "receipt identity mismatch")
    if reserved.get("edit_reimport_export_lineage") != dict(expected_lineage):
        raise ProducerFunctionalError(
            "WR_LINEAGE_STALE", "reserved lineage does not match the current request"
        )
    if reserved.get("producer_identity") != dict(producer):
        raise ProducerFunctionalError(
            "WR_UNKNOWN_OUTCOME", "producer implementation identity is unavailable or stale"
        )
    code = int(invocation.get("exit_code", -1))
    stdout = str(invocation.get("stdout", ""))
    stderr = str(invocation.get("stderr", ""))
    word_result = _parse_lines(stdout)
    if code != 0 or "error_code" in word_result:
        raise ProducerFunctionalError(
            "WR_WORD_EXECUTION",
            f"exit={code}; error={word_result.get('error_code', '')}; {word_result.get('error_message', stderr)}",
        )
    return (
        dict(reserved.get("word_inventory_before", {})),
        str(reserved.get("started_at", "")),
        word_result,
    )


def produce_candidate(request: ProducerRequest) -> dict[str, Any]:
    """Run Word once or reuse a completed candidate without replaying side effects."""

    source_hash = sha256_file(request.source_path)
    if source_hash != request.source_snapshot_sha256:
        raise ProducerFunctionalError(
            "WR_SOURCE_SNAPSHOT", "PoC source snapshot must bind the exact source DOCX"
        )
    producer = producer_identity()
    key, receipt_id = _identity(request, producer)
    run_dir = _run_dir(request, receipt_id)
    input_artifact_id = f"word-input-{source_hash[:20]}"
    expected_lineage = _lineage_for_request(
        request,
        input_artifact_id=input_artifact_id,
        input_hash=source_hash,
    )
    final_receipt = run_dir / "receipt.json"
    candidate_path = run_dir / "receipt_candidate.json"
    if final_receipt.is_file():
        receipt = json.loads(final_receipt.read_text(encoding="utf-8"))
        assert_receipt_current(receipt, _current_identity(request))
        if receipt.get("edit_reimport_export_lineage") != expected_lineage:
            raise ProducerFunctionalError(
                "WR_LINEAGE_STALE", "final receipt lineage does not match the current request"
            )
        return {"status": "replayed", "run_dir": str(run_dir), "receipt": receipt}
    if candidate_path.is_file():
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        if candidate.get("edit_reimport_export_lineage") != expected_lineage:
            raise ProducerFunctionalError(
                "WR_LINEAGE_STALE", "candidate lineage does not match the current request"
            )
        return {
            "status": "awaiting_visual_qc",
            "run_dir": str(run_dir),
            "candidate": candidate,
        }
    events = run_dir / "events"
    input_path = run_dir / "input.docx"
    saved_path = run_dir / "word-saved.docx"
    pdf_path = run_dir / "word-export.pdf"
    prior_events = _event_paths(run_dir)
    resumed_postprocessing = False
    if prior_events:
        inventory_before, started_at, word_result = _reconcile_completed_word_invocation(
            run_dir=run_dir,
            source_hash=source_hash,
            producer=producer,
            idempotency_key=key,
            receipt_id=receipt_id,
            expected_lineage=expected_lineage,
        )
        resumed_postprocessing = True
        atomic_write_json_once(
            events / "003-postprocess-resumed.json",
            {
                "event": "postprocess_resumed_without_word_replay",
                "source_word_event_sha256": sha256_file(
                    events / "002-word-invocation.json"
                ),
            },
        )
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        if any(path.exists() for path in (input_path, saved_path, pdf_path)):
            raise ProducerFunctionalError("WR_ARTIFACT_EXISTS", "task output already exists")
        inventory_before = word_inventory()
        started_at = _utc_now()
        atomic_write_json_once(
            events / "001-reserved.json",
            {
                "event": "reserved",
                "started_at": started_at,
                "source_path": str(request.source_path),
                "source_sha256": source_hash,
                "idempotency_key": key,
                "receipt_id": receipt_id,
                "edit_reimport_export_lineage": expected_lineage,
                "producer_identity": producer,
                "word_inventory_before": inventory_before,
            },
        )
        shutil.copyfile(request.source_path, input_path)
        if (
            sha256_file(input_path) != source_hash
            or sha256_file(request.source_path) != source_hash
        ):
            raise ProducerFunctionalError(
                "WR_SOURCE_CHANGED", "source or task input hash changed"
            )
        script = _word_script(input_path, saved_path, pdf_path)
        code, stdout, stderr = _run_applescript(script, timeout=600)
        word_result = _parse_lines(stdout)
        atomic_write_json_once(
            events / "002-word-invocation.json",
            {
                "event": "word_invocation_returned",
                "completed_at": _utc_now(),
                "exit_code": code,
                "stdout": stdout,
                "stderr": stderr,
            },
        )
        if code != 0 or "error_code" in word_result:
            raise ProducerFunctionalError(
                "WR_WORD_EXECUTION",
                f"exit={code}; error={word_result.get('error_code', '')}; {word_result.get('error_message', stderr)}",
            )
    before_ooxml = inspect_docx_ooxml(input_path)
    for key_name in (
        "open_without_repair",
        "repaginate_pass",
        "save_pass",
        "pdf_pass",
        "reopen_pass",
    ):
        if word_result.get(key_name) != "true":
            raise ProducerFunctionalError("WR_WORD_INCOMPLETE", f"{key_name} not proven")
    if not saved_path.is_file() or not pdf_path.is_file():
        raise ProducerFunctionalError("WR_WORD_ARTIFACT", "Word did not create DOCX and PDF")
    if sha256_file(request.source_path) != source_hash or sha256_file(input_path) != source_hash:
        raise ProducerFunctionalError("WR_SOURCE_CHANGED", "source or input changed after Word run")

    after_ooxml = inspect_docx_ooxml(saved_path)
    before_count = int(word_result["field_count_before"])
    after_count = int(word_result["field_count_after"])
    if int(word_result.get("field_update_error_count", "-1")) != 0:
        raise ProducerFunctionalError("WR_FIELD_UPDATE", "Word reported field update errors")
    if int(word_result.get("story_range_count_updated", "0")) < 1:
        raise ProducerFunctionalError("WR_FIELD_SCOPE", "no Word story range was updated")
    bookmark_checks = select_bookmark_checks(before_ooxml, after_ooxml)
    cross_reference_checks = select_cross_reference_checks(after_ooxml)
    if not bookmark_checks:
        raise ProducerFunctionalError("WR_BOOKMARK_EVIDENCE", "no stable bookmark target survived")
    if not cross_reference_checks:
        raise ProducerFunctionalError("WR_REFERENCE_EVIDENCE", "no resolved REF/PAGEREF survived")

    pages, page_producer = render_pdf_page_evidence(pdf_path, run_dir / "pages")
    for page in pages:
        page["visual_qc_status"] = "pending_visual_qc"
    saved_hash = sha256_file(saved_path)
    pdf_hash = sha256_file(pdf_path)
    saved_artifact_id = f"word-saved-{saved_hash[:20]}"
    pdf_artifact_id = f"word-pdf-{pdf_hash[:20]}"
    unavailable = [
        item
        for item in word_result.get("unavailable_fonts", "").split("|||")
        if item and item != "missing value"
    ]
    ooxml_fingerprint = normalized_ooxml_fingerprint(saved_path)
    ooxml_fingerprint["artifact_id"] = saved_artifact_id
    ooxml_fingerprint["artifact_sha256"] = saved_hash
    completed_at = _utc_now()
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "verification_engine": VERIFICATION_ENGINE,
        "verification_status": VERIFICATION_STATUS,
        "workflow": WORKFLOW,
        "source_snapshot_sha256": request.source_snapshot_sha256,
        "input_artifact_id": input_artifact_id,
        "input_docx_sha256": source_hash,
        "semantic_document_revision": request.semantic_document_revision,
        "template_revision": request.template_revision,
        "word_application_version": f"Microsoft Word for Mac {word_result['word_version']}",
        "os_and_font_environment": font_environment(
            after_ooxml["fonts"], unavailable
        ),
        "open_without_repair": True,
        "field_update_scope": "all_story_ranges",
        "field_update_error_count": 0,
        "field_count_before": before_count,
        "field_count_after": after_count,
        "toc_count": int(word_result["toc_count"]),
        "repaginate_pass": True,
        "bookmark_checks": bookmark_checks,
        "cross_reference_checks": cross_reference_checks,
        "saved_artifact_id": saved_artifact_id,
        "saved_docx_sha256": saved_hash,
        "reopen_pass": True,
        "pdf_artifact_id": pdf_artifact_id,
        "pdf_sha256": pdf_hash,
        "page_count": len(pages),
        "page_evidence_producer": page_producer,
        "page_evidence": pages,
        "page_evidence_manifest_sha256": page_manifest(pdf_path, pages),
        "normalized_ooxml_fingerprint": ooxml_fingerprint,
        "edit_reimport_export_lineage": expected_lineage,
        "started_at": started_at,
        "completed_at": completed_at,
        "producer_identity": producer,
        "idempotency_key": key,
    }
    inventory_after = word_inventory()
    original_before = inventory_before.get("documents", [])
    original_after = inventory_after.get("documents", [])
    if original_before != original_after:
        raise ProducerFunctionalError(
            "WR_USER_DOCUMENT_DRIFT",
            "existing Word document inventory changed during task-copy run",
        )
    atomic_write_json_once(candidate_path, candidate)
    candidate_event_name = (
        "004-candidate-ready.json"
        if resumed_postprocessing
        else "003-candidate-ready.json"
    )
    atomic_write_json_once(
        events / candidate_event_name,
        {
            "event": "candidate_ready_for_visual_qc",
            "completed_at": completed_at,
            "saved_docx_sha256": saved_hash,
            "pdf_sha256": pdf_hash,
            "page_count": len(pages),
            "normalized_ooxml_sha256": ooxml_fingerprint["sha256"],
            "word_inventory_after": inventory_after,
        },
    )
    return {"status": "awaiting_visual_qc", "run_dir": str(run_dir), "candidate": candidate}


def finalize_visual_qc(run_dir: Path, *, passed_pages: list[int]) -> dict[str, Any]:
    """Create the final immutable receipt after independent visible page review."""

    candidate_path = run_dir / "receipt_candidate.json"
    receipt_path = run_dir / "receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate_receipt(receipt)
        return {"status": "replayed", "receipt": receipt}
    if not candidate_path.is_file():
        raise ProducerFunctionalError("WR_CANDIDATE_MISSING", str(candidate_path))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    expected_pages = list(range(1, int(candidate["page_count"]) + 1))
    if passed_pages != expected_pages:
        raise ProducerFunctionalError(
            "WR_VISUAL_QC_INCOMPLETE", "every page must be reviewed in order"
        )
    for page in candidate["page_evidence"]:
        page["visual_qc_status"] = "pass"
    pdf_path = run_dir / "word-export.pdf"
    candidate["page_evidence_manifest_sha256"] = page_manifest(
        pdf_path, candidate["page_evidence"]
    )
    receipt = validate_receipt(candidate)
    atomic_write_json_once(receipt_path, receipt)
    atomic_write_json_once(
        run_dir / "events" / "004-receipt-finalized.json",
        {
            "event": "receipt_finalized_after_visual_qc",
            "completed_at": _utc_now(),
            "receipt_id": receipt["receipt_id"],
            "page_count": receipt["page_count"],
        },
    )
    return {"status": "completed", "receipt": receipt}
