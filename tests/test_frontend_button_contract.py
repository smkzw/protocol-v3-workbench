from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "frontend" / "src" / "App.jsx"


class FrontendButtonContractTests(unittest.TestCase):
    def test_every_visible_button_has_an_action_or_explicit_disabled_state(self) -> None:
        source = APP_SOURCE.read_text(encoding="utf-8")
        violations = []
        for match in re.finditer(r"<button\b(?P<attrs>[^>]*)>", source, re.S):
            attributes = match.group("attrs")
            if "onClick=" in attributes or re.search(r"\bdisabled(?:=|\s|$)", attributes):
                continue
            line = source.count("\n", 0, match.start()) + 1
            opening_tag = " ".join(match.group(0).split())[:180]
            violations.append(f"line {line}: {opening_tag}")

        self.assertEqual([], violations, "Buttons without action/disabled contract:\n" + "\n".join(violations))

    def test_product_ui_does_not_expose_codex_or_raw_engineering_labels(self) -> None:
        source = APP_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn("Codex 运行依赖", source)
        self.assertNotIn("搜索 raw source 摘要或任务状态", source)
        self.assertNotIn("历史对照（legacy comparison）", source)
        self.assertNotIn("当前项目 raw 证据节点", source)
        self.assertNotIn("codex_runtime_dependency=false", source)

    def test_disabled_buttons_explain_why_they_are_unavailable(self) -> None:
        source = APP_SOURCE.read_text(encoding="utf-8")
        violations = []
        for match in re.finditer(r"<button\b(?P<attrs>[^>]*)>", source, re.S):
            attributes = match.group("attrs")
            if not re.search(r"\bdisabled(?:=|\s|$)", attributes):
                continue
            if "title=" in attributes or "aria-describedby=" in attributes:
                continue
            line = source.count("\n", 0, match.start()) + 1
            opening_tag = " ".join(match.group(0).split())[:220]
            violations.append(f"line {line}: {opening_tag}")

        self.assertEqual([], violations, "Disabled buttons without an explanation:\n" + "\n".join(violations))

    def test_approval_page_does_not_claim_quality_gate_pass_before_server_check(self) -> None:
        source = APP_SOURCE.read_text(encoding="utf-8")
        approval_page = re.search(
            r"function ApprovalPage\(.*?function ModuleUnavailablePage",
            source,
            re.S,
        )
        self.assertIsNotNone(approval_page)
        body = approval_page.group(0)
        self.assertIn("qualityGateLoaded", body)
        self.assertIn("质量门待读取", body)
        self.assertIn('action === "view_quality_gate"', body)
        self.assertIn("!qualityGateLoaded || hasBlockers", body)


if __name__ == "__main__":
    unittest.main()
