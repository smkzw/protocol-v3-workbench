from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FrontendMedicalWritingStudySchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "frontend/src/App.jsx").read_text(encoding="utf-8")
        cls.editor = (
            ROOT / "frontend/src/features/medical-writing/StudySchemaEditor.jsx"
        ).read_text(encoding="utf-8")
        cls.styles = (ROOT / "frontend/src/styles.css").read_text(encoding="utf-8")

    def test_specialized_node_uses_schema_editor_and_hides_generic_ai_rail(self):
        self.assertIn('section.nodeKind === "study_schema"', self.app)
        self.assertIn('section.interactionTypes?.includes("study_schema_editor")', self.app)
        self.assertIn("<StudySchemaEditor", self.app)
        self.assertIn("hidden={isStudySchemaSection}", self.app)
        self.assertIn("writing-study-schema-layout", self.app)

    def test_editor_keeps_preview_commit_and_layout_as_distinct_actions(self):
        for path in (
            "/proposal",
            "/impact-preview",
            "/commit",
            "/layout",
        ):
            self.assertIn(path, self.editor)
        self.assertIn("expected_journey_revision", self.editor)
        self.assertIn("expected_schema_revision", self.editor)
        self.assertIn("expected_layout_revision", self.editor)
        self.assertIn("impact_preview_id", self.editor)
        self.assertIn("changeReason.trim().length < 10", self.editor)

    def test_editor_uses_image_boundary_for_server_svg_and_limited_layout(self):
        self.assertIn("data:image/svg+xml", self.editor)
        self.assertNotIn("dangerouslySetInnerHTML", self.editor)
        self.assertIn("clamp(current.dx + dx, -48, 48)", self.editor)
        self.assertIn("clamp(current.dy + dy, -32, 32)", self.editor)
        self.assertIn("位置微调已写入独立布局版本，未改变研究事实", self.editor)

    def test_desktop_workspace_has_stable_three_column_geometry(self):
        self.assertIn(".study-schema-workspace", self.styles)
        self.assertIn("grid-template-columns: 250px minmax(520px, 1fr) 286px", self.styles)
        self.assertIn(".study-schema-editor.is-fullscreen", self.styles)
        self.assertIn("min-height: 480px", self.styles)

    def test_deleting_selected_graph_items_falls_back_to_a_remaining_item(self):
        self.assertIn('setSelectedNodeId(nodes[0]?.node_id || "")', self.editor)
        self.assertIn('setSelectedEdgeId(edges[0]?.edge_id || "")', self.editor)
        self.assertIn("deleteEdge(selectedEdge.edge_id)", self.editor)


if __name__ == "__main__":
    unittest.main()
