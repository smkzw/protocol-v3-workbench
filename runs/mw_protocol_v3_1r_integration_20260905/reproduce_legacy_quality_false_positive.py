"""Synthetic text classification counterexample, not clinical protocol advice."""
import json
from types import SimpleNamespace

from services.api.app.medical_writing_content_quality import MedicalWritingContentQualityDetector

document = SimpleNamespace(project_id="synthetic", document_id="doc", version="1")
section = SimpleNamespace(section_id="consent", heading="知情同意")
examples = {
    "completed_procedural_sentence": "未提供书面知情同意者不进入筛选。",
    "actual_drafting_placeholder": "样本量尚待医学经理确认。",
}
output = []
for kind, text in examples.items():
    findings = MedicalWritingContentQualityDetector().scan_section(
        document, section, [{"block_id": "text", "block_type": "paragraph", "text": text}],
        content_revision=0,
    )
    blocking = [item for item in findings if item.approval_blocking]
    assert len(blocking) == 1 and blocking[0].rule_code == "unresolved_draft_marker"
    output.append({"case": kind, "text": text, "rule": blocking[0].rule_code,
                   "approval_blocking": blocking[0].approval_blocking})
print(json.dumps(output, ensure_ascii=False, indent=2))
