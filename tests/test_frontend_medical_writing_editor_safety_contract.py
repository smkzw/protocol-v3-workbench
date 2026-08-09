from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"
STYLES_SOURCE = ROOT / "frontend" / "src" / "styles.css"


class FrontendMedicalWritingEditorSafetyContractTests(unittest.TestCase):
    """E2 unit/source evidence only; browser interaction remains an E4 gate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_SOURCE.read_text(encoding="utf-8")
        cls.styles = STYLES_SOURCE.read_text(encoding="utf-8")

    def _writing_page(self) -> str:
        match = re.search(
            r"function WritingPage\(.*?function approvalTypeLabel",
            self.source,
            re.S,
        )
        self.assertIsNotNone(match)
        return match.group(0)

    def test_recovery_storage_state_machine_executes_in_javascript(self) -> None:
        helper_block = re.search(
            r"const MEDICAL_WRITING_RECOVERY_DRAFT_PREFIX.*?(?=\nfunction workingCopyFreezeLabel)",
            self.source,
            re.S,
        )
        self.assertIsNotNone(helper_block, "Recovery helper block not found")
        node_script = f"""
const vm = require("node:vm");
const helperSource = {json.dumps(helper_block.group(0))};
const context = {{}};
vm.runInNewContext(helperSource + `
globalThis.recoveryApi = {{
  medicalWritingRecoveryDraftKey,
  persistMedicalWritingRecoveryDraft,
  listMedicalWritingRecoveryDrafts,
  clearMedicalWritingRecoveryDrafts,
  medicalWritingRecoveryDraftState,
}};`, context);
class MemoryStorage {{
  constructor() {{ this.data = new Map(); }}
  get length() {{ return this.data.size; }}
  key(index) {{ return Array.from(this.data.keys())[index] ?? null; }}
  getItem(key) {{ return this.data.has(key) ? this.data.get(key) : null; }}
  setItem(key, value) {{ this.data.set(key, String(value)); }}
  removeItem(key) {{ this.data.delete(key); }}
}}
const storage = new MemoryStorage();
const api = context.recoveryApi;
const identity = {{ projectId: "proj-A", documentId: "doc-A", sectionId: "sec-1", baseRevision: 4 }};
const saved = api.persistMedicalWritingRecoveryDraft(storage, identity, [{{
  block_id: "p1",
  text: "真实医学修订",
  rich_text: {{ type: "doc", content: [] }},
  file_bytes: "must-not-persist",
  api_key: "must-not-persist",
  image_data: "data:image/png;base64,AAAA",
}}], new Date("2026-07-22T08:00:00.000Z"));
const otherRevisionKey = api.medicalWritingRecoveryDraftKey({{ ...identity, baseRevision: 5 }});
const drafts = api.listMedicalWritingRecoveryDrafts(storage, identity);
const result = {{
  keyContainsRevision: saved.storageKey.endsWith(":4") && otherRevisionKey.endsWith(":5"),
  isolatedRevisionKeys: saved.storageKey !== otherRevisionKey,
  count: drafts.length,
  text: drafts[0].contentBlocks[0].text,
  fileBytesRemoved: !("file_bytes" in drafts[0].contentBlocks[0]),
  apiKeyRemoved: !("api_key" in drafts[0].contentBlocks[0]),
  imageDataRemoved: !("image_data" in drafts[0].contentBlocks[0]),
  hash: drafts[0].contentHash,
  matching: api.medicalWritingRecoveryDraftState(4, drafts[0]),
  conflict: api.medicalWritingRecoveryDraftState(5, drafts[0]),
}};
api.clearMedicalWritingRecoveryDrafts(storage, identity);
result.cleared = storage.length === 0;
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["keyContainsRevision"])
        self.assertTrue(result["isolatedRevisionKeys"])
        self.assertEqual(1, result["count"])
        self.assertEqual("真实医学修订", result["text"])
        self.assertTrue(result["fileBytesRemoved"])
        self.assertTrue(result["apiKeyRemoved"])
        self.assertTrue(result["imageDataRemoved"])
        self.assertRegex(result["hash"], r"^fnv1a32:[0-9a-f]{8}$")
        self.assertEqual("matching", result["matching"])
        self.assertEqual("conflict", result["conflict"])
        self.assertTrue(result["cleared"])

    def test_dirty_lifecycle_registers_beforeunload_and_session_debounce(self) -> None:
        writing = self._writing_page()
        self.assertIn('addEventListener?.("beforeunload", handleBeforeUnload)', writing)
        self.assertIn('removeEventListener?.("beforeunload", handleBeforeUnload)', writing)
        self.assertIn("if (!workingCopyDirty) return undefined", writing)
        self.assertIn("persistCurrentRecoveryDraft(), 450", writing)
        self.assertIn("clearCurrentRecoveryDraft();", writing)

    def test_section_reads_keep_failure_distinct_and_reject_stale_responses(self) -> None:
        writing = self._writing_page()
        self.assertIn("workingCopyRequestRef.current !== requestId", writing)
        self.assertIn("loadedEditorIdentity === expectedEditorIdentity", writing)
        self.assertIn("setWorkingCopyLoadError(`章节正文或工作副本读取失败", writing)
        self.assertIn("当前内存中的编辑内容未被清空", writing)
        self.assertIn("Array.isArray(sectionContent?.content_blocks)", writing)

        load_effect = re.search(
            r"Promise\.all\(\[\s*fetch\(`/api/projects/\$\{projectId\}/medical-writing/document-session/sections/.*?\n\s*\}, \[projectId, isDemoWritingSession, documentSession\?\.document_id, selectedSection, workingCopyReloadNonce\]\);",
            writing,
            re.S,
        )
        self.assertIsNotNone(load_effect, "Section loading effect not found")
        failure_branch = re.search(r"\.catch\(\(error\) => \{(?P<body>.*?)\n\s*\}\)", load_effect.group(0), re.S)
        self.assertIsNotNone(failure_branch)
        self.assertNotIn("setWorkingCopy(null)", failure_branch.group("body"))
        self.assertNotIn("setWorkingCopyDraftBlocks([])", failure_branch.group("body"))
        self.assertNotIn("setSectionContent(null)", failure_branch.group("body"))

    def test_navigation_uses_explicit_chinese_choices_not_native_confirm(self) -> None:
        writing = self._writing_page()
        self.assertIn("requestSectionChange", writing)
        self.assertIn("requestWorkingCopyReload", writing)
        self.assertIn("继续编辑", writing)
        self.assertIn("丢弃并切换", writing)
        self.assertIn("恢复会话稿", writing)
        self.assertIn("requestApplicationNavigation", self.source)
        self.assertIn("requestProjectChange", self.source)
        self.assertNotIn("globalThis.confirm", writing)
        self.assertNotIn("window.confirm", writing)

    def test_fullscreen_keeps_save_ai_evidence_and_literature_entries(self) -> None:
        self.assertIn('aria-label="正文全屏关键操作"', self.source)
        self.assertIn("fullscreenSaveState", self.source)
        self.assertIn("onFullscreenSave={saveWorkingCopy}", self.source)
        self.assertIn('["AI", "证据", "文献"]', self.source)
        self.assertIn("AI候选/改写", self.source)
        self.assertIn(".rich-editor-fullscreen-actions", self.styles)
        self.assertIn(".writing-unsaved-navigation-dialog", self.styles)


if __name__ == "__main__":
    unittest.main()
