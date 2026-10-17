#!/usr/bin/env python3
"""WP-M1-EVAL 内部自测（不进 tests/ 主套件）。

先于实现编写（TDD）：运行 `python3 eval/selftest.py` 应在实现完成后全部通过。
用法：
    python3 eval/selftest.py                 # 跑全部自测
    python3 eval/selftest.py --with-real     # 额外用真实产物跑一遍端到端
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
sys.path.insert(0, str(EVAL_DIR))

DEFAULT_REAL_INPUT = (
    REPO_ROOT
    / "runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/"
    / "isolated_runtime/medical_writing_full_drafts/proj_user_3f4f11edbdf4/"
    / "mwjob_c998b723219d608ff1e9a389/full-draft.json"
)

NODE_TREE = (
    REPO_ROOT
    / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json"
)

# 泛化红线：eval 代码中不得出现具体药物/疾病/量表名/项目号（数据文件除外）。
# 词面由碎片拼出，避免本文件自身命中红线（被检查的是 align/metrics/report/run 等实现文件）。
GENERALIZATION_BLOCKLIST = [
    "".join(x) for x in [
        ["MY", "009"],
        ["溃疡性", "结肠炎"],
        ["VN", "N1"],
        ["M", "ayo"],
        ["心", "衰"],
        ["CO", "PD"],
        ["CRSw", "NP"],
    ]
]


def _mini_draft() -> dict:
    """构造与 protocol_full_draft_artifact 同构的最小产物（合成，无真实项目语义）。"""
    return {
        "schema_version": "protocol_full_draft_artifact_v10",
        "job_id": "mwjob_selftest",
        "project_id": "proj_selftest",
        "sections": [
            {
                "section_id": "s1",
                "section_number": "1",
                "heading": "方案概要",
                "content_status": "complete",
                "proposal_text": "正文" * 80,  # 160 个中文字符，无占位标记
            },
            {
                "section_id": "s2",
                "section_number": "2",
                "heading": "概述章节",
                "content_status": "partial",
                "semantic_node_id": "v2_n_2",
                "proposal_text": "含占位标记：剂量【待补齐】。",
            },
            {
                "section_id": "s3",
                "section_number": "99",
                "heading": "源缺口章节",
                "content_status": "source_gap",
                "proposal_text": "",
            },
            {
                "section_id": "s4",
                "section_number": "11",
                "heading": "短文章节",
                "content_status": "partial",
                "proposal_text": "太短的正文。",
            },
        ],
    }


class _Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.failures: list[str] = []

    def check(self, cond: bool, msg: str) -> None:
        if not cond:
            self.failures.append(msg)


def test_node_map_data(r: _Result) -> None:
    import align

    node_map = align.load_node_map(EVAL_DIR / "node_map.json")
    tree_ids = {n["id"] for n in json.loads(NODE_TREE.read_text())["outlined_tree"]["nodes"]}
    r.check(len(node_map.entries) > 0, "node_map 应有映射条目")
    for e in node_map.entries:
        r.check(
            e.semantic_node_id in tree_ids,
            f"映射目标 {e.semantic_node_id} 必须存在于 TP-MA-07 v2 节点树",
        )
        r.check(bool(e.section_number), "映射条目必须有 section_number")
        r.check(bool(e.heading), "映射条目必须有 heading")
        r.check(
            e.match_quality in ("exact", "approx"),
            f"match_quality 非法: {e.match_quality}",
        )


def test_align(r: _Result) -> None:
    import align

    node_map = align.load_node_map(EVAL_DIR / "node_map.json")
    aligner = align.Aligner(node_map)
    sections = _mini_draft()["sections"]

    # 1) section 自带 semantic_node_id 时直接采用
    recs = aligner.align_sections(sections)
    by_sid = {rec.section_id: rec for rec in recs}
    r.check(by_sid["s2"].semantic_node_id == "v2_n_2", "原生 semantic_node_id 优先")

    # 2) (section_number, heading) 精确命中
    r.check(by_sid["s1"].semantic_node_id == "v2_n_1_1", "精确映射 (1, 方案概要)")
    r.check(by_sid["s1"].match_quality == "exact", "精确映射质量为 exact")

    # 3) 未命中 → None，且记录 match_quality 为 unmatched
    r.check(by_sid["s3"].semantic_node_id is None, "未收录 section 对齐为 None")
    r.check(by_sid["s3"].match_quality == "unmatched", "未命中质量标记 unmatched")

    # 4) 编号命中但标题未知 → 编号回退，质量标记 number_only
    r.check(by_sid["s4"].semantic_node_id == "v2_n_13", "编号回退命中 (11)")
    r.check(by_sid["s4"].match_quality == "number_only", "编号回退质量标记 number_only")


def test_metrics(r: _Result) -> None:
    import metrics

    sections = _mini_draft()["sections"]
    aligned = [
        {"section_id": "s1", "semantic_node_id": "v2_n_1_1"},
        {"section_id": "s2", "semantic_node_id": "v2_n_2"},
        {"section_id": "s3", "semantic_node_id": None},
        {"section_id": "s4", "semantic_node_id": "v2_n_11_1"},
    ]
    cov = metrics.coverage(sections, aligned)
    # 适用节点 = 有对齐的 3 节；实质正文 = s1（s2 占位、s4 <100 字）
    r.check(cov["applicable"] == 3, f"适用节点数应为 3，得到 {cov['applicable']}")
    r.check(cov["covered"] == 1, f"覆盖节点数应为 1，得到 {cov['covered']}")
    r.check(abs(cov["ratio"] - 1 / 3) < 1e-9, "覆盖率应等于 1/3")

    ph = metrics.placeholder_counts(sections)
    r.check(ph["marker_count"] == 1, f"占位标记计数应为 1，得到 {ph['marker_count']}")
    r.check(ph["section_count"] == 1, "含占位章节数应为 1")

    leak = metrics.leak_ratio(sections, competitor_terms=None)
    r.check(leak["computed"] is False, "无竞品词表时泄漏指标标记为未计算")

    conflicts = metrics.fact_conflicts(sections, study_definition=None)
    r.check(conflicts == [], "事实冲突首版空实现应返回空列表")


def test_report_and_run(r: _Result) -> None:
    import run as run_mod

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        draft_path = out_dir / "full-draft.json"
        draft_path.write_text(json.dumps(_mini_draft(), ensure_ascii=False), encoding="utf-8")
        rc = run_mod.main(
            [
                "--set",
                "smoke",
                "--input",
                str(draft_path),
                "--reports-dir",
                str(out_dir / "reports"),
            ]
        )
        r.check(rc == 0, "run.main 应返回 0")
        reports = sorted((out_dir / "reports").glob("*.json"))
        r.check(len(reports) == 1, "应生成恰好一份报告 json")
        report = json.loads(reports[0].read_text())
        r.check(report["set"] == "smoke", "报告应记录评测集")
        r.check(
            abs(report["metrics"]["coverage"]["ratio"] - 1 / 3) < 1e-9,
            "端到端覆盖率应为 1/3",
        )
        summaries = sorted((out_dir / "reports").glob("summary*.md"))
        r.check(len(summaries) == 1, "应生成恰好一份 summary.md")
        text = summaries[0].read_text()
        r.check("覆盖率" in text, "summary 应含覆盖率分数")
        r.check(len(text) < 6000, "summary 应保持一页篇幅")


def test_generalization(r: _Result) -> None:
    for py in sorted(EVAL_DIR.glob("*.py")):
        body = py.read_text()
        for term in GENERALIZATION_BLOCKLIST:
            r.check(term not in body, f"{py.name} 不得出现具体项目词 {term!r}")


def test_real_artifact(r: _Result) -> None:
    import run as run_mod

    if not DEFAULT_REAL_INPUT.exists():
        r.failures.append(f"真实产物不存在: {DEFAULT_REAL_INPUT}")
        return
    with tempfile.TemporaryDirectory() as td:
        rc = run_mod.main(
            [
                "--set",
                "smoke",
                "--input",
                str(DEFAULT_REAL_INPUT),
                "--reports-dir",
                str(Path(td)),
            ]
        )
        r.check(rc == 0, "真实产物端到端应成功")
        report = json.loads(sorted(Path(td).glob("*.json"))[0].read_text())
        cov = report["metrics"]["coverage"]["ratio"]
        r.check(cov < 0.9, f"真实产物覆盖率应显著低于 100%（该项目有跳过章节），得到 {cov}")
        dur = report["metrics"]["duration"]
        r.check(
            dur["minutes"] is not None and dur["minutes"] > 0,
            "真实产物应能从 job 记录推出耗时",
        )


def main(argv: list[str]) -> int:
    with_real = "--with-real" in argv
    tests = [
        test_node_map_data,
        test_align,
        test_metrics,
        test_report_and_run,
        test_generalization,
    ]
    if with_real:
        tests.append(test_real_artifact)
    total_fail = 0
    for t in tests:
        res = _Result(t.__name__)
        try:
            t(res)
        except Exception as exc:  # noqa: BLE001 - 自测收集所有异常为失败
            res.failures.append(f"异常: {type(exc).__name__}: {exc}")
        total_fail += len(res.failures)
        status = "PASS" if not res.failures else "FAIL"
        print(f"[{status}] {t.__name__}")
        for f in res.failures:
            print(f"    - {f}")
    print(f"\n{total_fail} failure(s) in {len(tests)} test group(s)")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
