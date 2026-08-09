from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.rux_monitoring_service import (  # noqa: E402
    BSA_SHEET,
    EASI_SHEET,
    RuxMonitoringService,
)


LISTING_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/"
    "RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/"
    "V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)


@unittest.skipUnless(
    LISTING_PATH.exists() and PROTOCOL_PATH.exists(),
    "real RUX Patient Profile sources are required",
)
class RuxPatientProfileDuplicateTrendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RuxMonitoringService(LISTING_PATH, PROTOCOL_PATH)

    def test_s23010_region_components_project_one_bsa_and_easi_total_event(self) -> None:
        profile = self.service.subject_monitoring("proj_rux_03_002", "S23010")
        efficacy = {metric.metric_key: metric for metric in profile.efficacy_trends}

        bsa_points = efficacy["bsa_total"].points
        easi_points = efficacy["easi_total"].points
        self.assertEqual(1, len(bsa_points))
        self.assertEqual(1, len(easi_points))

        bsa_point = bsa_points[0]
        self.assertEqual(("SCR", "2024-09-06", 19.0), (
            bsa_point.visit_code,
            bsa_point.assessment_date,
            bsa_point.value,
        ))
        self.assertIn("FORMOID:bsa", bsa_point.source_record_id)
        self.assertNotIn(":row:", bsa_point.source_record_id)
        self.assertEqual(
            set(range(6695, 6699)),
            {int(locator.rsplit(":row:", 1)[1]) for locator in bsa_point.source_component_locators},
        )

        easi_point = easi_points[0]
        self.assertEqual(("SCR", "2024-09-06", 8.3), (
            easi_point.visit_code,
            easi_point.assessment_date,
            easi_point.value,
        ))
        self.assertIn("FORMOID:easi", easi_point.source_record_id)
        self.assertNotIn(":row:", easi_point.source_record_id)
        self.assertEqual(4, len(easi_point.source_component_locators))
        self.assertTrue(all("EASI--" in locator for locator in easi_point.source_component_locators))

        for sheet, location_key in ((BSA_SHEET, "BSALOC"), (EASI_SHEET, "EASILOC")):
            source_rows = self.service._rows(sheet, "S23010")
            stable_form_ids = {
                tuple(row.get(field, "") for field in ("SUBJID", "VISTOID", "VISTREP", "FORMOID", "FORMREP"))
                for _, row in source_rows
            }
            self.assertEqual(1, len(stable_form_ids))
            self.assertEqual({"1", "2", "3", "4"}, {row["RECREP"] for _, row in source_rows})
            self.assertEqual(4, len({row[location_key] for _, row in source_rows}))

    def test_coalescing_uses_form_event_identity_and_preserves_conflicts(self) -> None:
        def row(form_repeat: str, record_repeat: str, value: str) -> dict[str, str]:
            return {
                "SUBJID": "S23010",
                "VISTOID": "SCR",
                "VISTREP": "0",
                "FORMOID": "bsa",
                "FORMREP": form_repeat,
                "RECREP": record_repeat,
                "BSADAT": "2024-09-06",
                "BSARESS": value,
            }

        same_date_value_distinct_events = [
            (1, row("0", "1", "19")),
            (2, row("0", "2", "19")),
            (3, row("1", "1", "19")),
            (4, row("1", "2", "19")),
        ]
        projected = self.service._coalesce_visit_level_total_rows(
            same_date_value_distinct_events,
            sheet_name=BSA_SHEET,
            date_key="BSADAT",
            value_getter=lambda item: float(item["BSARESS"]),
        )
        self.assertEqual(2, len(projected))
        self.assertEqual(
            {"FORMREP:0", "FORMREP:1"},
            {
                next(part for part in event_row["__source_record_id__"].split("|") if part.startswith("FORMREP:"))
                for _, event_row in projected
            },
        )

        conflicting_same_event = [
            (1, row("0", "1", "19")),
            (2, row("0", "2", "20")),
        ]
        conflict_projection = self.service._coalesce_visit_level_total_rows(
            conflicting_same_event,
            sheet_name=BSA_SHEET,
            date_key="BSADAT",
            value_getter=lambda item: float(item["BSARESS"]),
        )
        self.assertEqual(conflicting_same_event, conflict_projection)


if __name__ == "__main__":
    unittest.main()
