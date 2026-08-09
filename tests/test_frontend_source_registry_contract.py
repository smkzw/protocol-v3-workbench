from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "src" / "App.jsx"
STYLES = ROOT / "frontend" / "src" / "styles.css"


class FrontendSourceRegistryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")
        cls.styles = STYLES.read_text(encoding="utf-8")

    def test_project_level_source_ledger_is_navigable(self) -> None:
        self.assertIn('{ key: "sourceRegistry", label: "来源台账"', self.source)
        self.assertIn('function SourceRegistryPage({ projectId, onOpenModule })', self.source)
        self.assertIn('return <SourceRegistryPage projectId={activeProjectId}', self.source)
        self.assertIn('前往模块', self.source)

    def test_ledger_uses_current_validation_and_sanitized_history_contract(self) -> None:
        self.assertIn("content_validation_histories", self.source)
        self.assertIn("data?.project_id !== plannedModuleProjectIdRef.current", self.source)
        self.assertIn("核验与确认记录", self.source)
        self.assertIn("尚无历史核验记录。", self.source)
        self.assertIn("确认沿用只改变使用状态，不会把原警告或不一致改为匹配", self.source)
        self.assertNotIn("file_sha256", self.source)
        self.assertNotIn("expected_context_hash", self.source)

    def test_override_requires_all_checks_and_substantive_reason(self) -> None:
        self.assertIn('unresolvedChecks.every((check) => acknowledgedCodes.includes(check.check_code))', self.source)
        self.assertIn("reason.trim().length >= 10", self.source)
        self.assertIn('expected_revision: selected.validation.revision', self.source)
        self.assertIn('/content-validation/confirm', self.source)

    def test_desktop_workspace_has_stable_split_layout(self) -> None:
        self.assertIn(".source-ledger-page", self.styles)
        self.assertIn("min-width: 1120px", self.styles)
        self.assertIn("grid-template-columns: minmax(390px, 0.82fr) minmax(580px, 1.4fr)", self.styles)


if __name__ == "__main__":
    unittest.main()
