"""G5 快照权限门回归（0926V1 F05/F06 + 0927V1 SPEC §1-2）。

从零建项（from_zero bootstrap）的旅程 search_plan=None 是模型层合法早期状态
（medical_writing_authoring_journey.py 建项时 framing/search 未就绪即为 None），
此时"已确认的发现篮投影"（confirmation_id + snapshot_id 与批次一致）本身就是
快照权威——这正是 Path B 的设计意图；search_plan 存在时仍是唯一"当前快照"来源。

八个场景（A501-A508 口径）：
A501 None+合法确认投影           → 通过（修复前死锁）
A502 None+无确认（无投影）        → 拒绝（原因不变）
A503 None+投影缺 confirmation_id → 拒绝
A504 search_plan 存在且匹配       → 通过（原 Path B 回归控制）
A505 search_plan 指向更新快照+旧投影 → 拒绝（过期/撤销投影）
A506 discovery.snapshot_id ≠ 请求快照 → 拒绝
A507 Path A finalized + search_plan=None → 通过（修复前被无条件检查误杀）
A508 同 snapshot 两个 prep        → 取 latest 且其范围必须与确认范围一致
"""

from types import SimpleNamespace
import unittest

from services.api.app.writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
)


def _journey(
    *,
    search_plan=None,
    projection=None,
    triage=None,
):
    return SimpleNamespace(
        search_plan=search_plan,
        corpus_triage=triage,
        discovery_basket_projection=projection,
        revision=6,
    )


def _projection(snapshot_id, confirmation_id="ct_conf_g5test", retained=("NCT1", "NCT2")):
    return SimpleNamespace(
        snapshot_id=snapshot_id,
        confirmation_id=confirmation_id,
        retained_nct_ids=list(retained),
    )


def _preparation(snapshot_id, retained=("NCT1", "NCT2"), status="completed"):
    return SimpleNamespace(
        snapshot_id=snapshot_id,
        status=status,
        retained_candidate_ids=list(retained),
    )


class _StubJourneyService:
    def __init__(self, journey):
        self._journey = journey

    def get(self, project_id):
        return self._journey


class _StubRepository:
    def search_snapshot(self, project_id, snapshot_id):
        return SimpleNamespace(snapshot_id=snapshot_id)


class _StubPreparationService:
    def __init__(self, batches):
        # batches: 同 snapshot 可能有多个，latest() 必须取最后一个
        self._batches = list(batches)

    def latest(self, project_id, snapshot_id):
        matches = [b for b in self._batches if b.snapshot_id == snapshot_id]
        if not matches:
            raise KeyError((project_id, snapshot_id))
        return matches[-1]


def _service(journey, batches):
    service = WritingReferenceTranslationBatchService.__new__(
        WritingReferenceTranslationBatchService
    )
    service.journey_service = _StubJourneyService(journey)
    service.repository = _StubRepository()
    service.preparation_service = _StubPreparationService(batches)
    return service


SNAP = "wref_search_g5test"
NEWER = "wref_search_newer"


class G5SnapshotScopeTests(unittest.TestCase):
    def _scope(self, journey, batches):
        return _service(journey, batches)._snapshot_scope("proj_g5", SNAP)

    def test_a501_none_search_plan_with_confirmed_projection_passes(self):
        journey = _journey(search_plan=None, projection=_projection(SNAP))
        journey_r, prep = self._scope(journey, [_preparation(SNAP)])
        self.assertEqual(prep.snapshot_id, SNAP)
        self.assertEqual(sorted(prep.retained_candidate_ids), ["NCT1", "NCT2"])

    def test_a502_none_search_plan_without_projection_rejected(self):
        journey = _journey(search_plan=None, projection=None)
        with self.assertRaisesRegex(ValueError, "finalized corpus triage"):
            self._scope(journey, [_preparation(SNAP)])

    def test_a503_projection_without_confirmation_rejected(self):
        journey = _journey(search_plan=None, projection=_projection(SNAP, confirmation_id=""))
        with self.assertRaisesRegex(ValueError, "finalized corpus triage"):
            self._scope(journey, [_preparation(SNAP)])

    def test_a504_search_plan_present_and_matching_still_passes(self):
        journey = _journey(
            search_plan=SimpleNamespace(latest_snapshot_id=SNAP),
            projection=_projection(SNAP),
        )
        journey_r, prep = self._scope(journey, [_preparation(SNAP)])
        self.assertEqual(prep.snapshot_id, SNAP)

    def test_a505_search_plan_newer_snapshot_stale_projection_rejected(self):
        journey = _journey(
            search_plan=SimpleNamespace(latest_snapshot_id=NEWER),
            projection=_projection(SNAP),
        )
        # Stale projection → Path B cannot confirm (search_plan points elsewhere),
        # so the first gate rejects; either rejection message is a correct refusal.
        with self.assertRaises(ValueError):
            self._scope(journey, [_preparation(SNAP)])

    def test_a506_projection_snapshot_mismatch_rejected(self):
        journey = _journey(
            search_plan=SimpleNamespace(latest_snapshot_id=NEWER),
            projection=_projection(NEWER),
        )
        with self.assertRaisesRegex(ValueError, "finalized corpus triage"):
            self._scope(journey, [_preparation(SNAP)])

    def test_a507_path_a_finalized_with_none_search_plan_passes(self):
        triage = SimpleNamespace(
            status="finalized",
            snapshot_id=SNAP,
            retained_candidate_ids=["NCT1", "NCT2"],
        )
        journey = _journey(search_plan=None, triage=triage)
        journey_r, prep = self._scope(journey, [_preparation(SNAP)])
        self.assertEqual(sorted(prep.retained_candidate_ids), ["NCT1", "NCT2"])

    def test_a508_same_snapshot_two_preparations_uses_latest(self):
        journey = _journey(search_plan=None, projection=_projection(SNAP))
        older = _preparation(SNAP, retained=("NCT1",))
        newer = _preparation(SNAP, retained=("NCT1", "NCT2"))
        journey_r, prep = self._scope(journey, [older, newer])
        self.assertEqual(sorted(prep.retained_candidate_ids), ["NCT1", "NCT2"])


if __name__ == "__main__":
    unittest.main()
