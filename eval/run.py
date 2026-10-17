#!/usr/bin/env python3
"""WP-M1-EVAL 评测入口。

用法：
    python3 eval/run.py --set smoke --input <full-draft.json 路径>

可选：
    --jobs-db <medical_writing_durable_jobs.sqlite3>   缺省从 --input 的上级目录自动发现
    --competitor-terms <词表文件，每行一个竞品词>        缺省无词表，泄漏指标标记未计算
    --reports-dir <目录>                                缺省 eval/reports

输出：eval/reports/<date>_<sha8>.json 与同目录一页 summary.md。
评测体系见 plans/mw_reboot_20261017/04_EVAL.md；对象 schema 见 eval/SCHEMAS.md。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))

import align  # noqa: E402
import metrics  # noqa: E402
import report  # noqa: E402

JOBS_DB_FILENAME = "medical_writing_durable_jobs.sqlite3"


def find_jobs_db(input_path: Path) -> Path | None:
    """从输入文件目录向上查找 durable jobs sqlite（通用机制，不含项目专属路径）。"""
    for parent in [input_path.resolve().parent, *input_path.resolve().parents]:
        candidate = parent / JOBS_DB_FILENAME
        if candidate.exists():
            return candidate
    return None


def load_job_times(jobs_db: Path, job_id: str) -> dict:
    """只读查询 job 的 created/finished 时间戳；查不到返回空。"""
    try:
        con = sqlite3.connect(f"file:{jobs_db}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT created_at, finished_at FROM durable_mw_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    if not row:
        return {}
    return {"created_at": row[0], "finished_at": row[1]}


def summarize_alignment(records: list[align.AlignmentRecord]) -> dict:
    by_kind = {"native": 0, "exact": 0, "approx": 0, "number_only": 0, "unmatched": 0}
    for r in records:
        by_kind[r.match_quality] = by_kind.get(r.match_quality, 0) + 1
    aligned = sum(v for k, v in by_kind.items() if k != "unmatched")
    return {
        "sections_total": len(records),
        "aligned": aligned,
        "unaligned": by_kind["unmatched"],
        "by_kind": by_kind,
    }


def load_competitor_terms(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    terms = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return terms or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="医学写作全文评测（WP-M1-EVAL 骨架）")
    parser.add_argument("--set", dest="eval_set", default="smoke", choices=["smoke", "dev", "heldout"])
    parser.add_argument("--input", required=True, help="full-draft.json 产物路径")
    parser.add_argument("--reports-dir", default=str(EVAL_DIR / "reports"))
    parser.add_argument("--jobs-db", default=None, help="durable jobs sqlite 路径（缺省自动发现）")
    parser.add_argument("--competitor-terms", default=None, help="竞品词表文件（每行一词）")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"输入不存在: {input_path}", file=sys.stderr)
        return 2
    artifact = json.loads(input_path.read_text(encoding="utf-8"))
    sections = artifact.get("sections")
    if not isinstance(sections, list) or not sections:
        print("输入缺少非空 sections 列表，不像 full-draft 产物", file=sys.stderr)
        return 2

    node_map = align.NodeMap.load(EVAL_DIR / "node_map.json")
    tree_problems = node_map.validate_against_tree()
    if tree_problems:
        for p in tree_problems:
            print(f"node_map 校验问题: {p}", file=sys.stderr)
        return 2

    aligner = align.Aligner(node_map)
    records = aligner.align_sections(sections)
    aligned_dicts = [
        {
            "section_id": r.section_id,
            "section_number": r.section_number,
            "heading": r.heading,
            "semantic_node_id": r.semantic_node_id,
        }
        for r in records
    ]
    alignment_summary = summarize_alignment(records)

    cov = metrics.coverage(sections, aligned_dicts)
    ph = metrics.placeholder_counts(sections)
    leak = metrics.leak_ratio(sections, load_competitor_terms(Path(args.competitor_terms) if args.competitor_terms else None))
    conflicts = metrics.fact_conflicts(sections, study_definition=None)

    jobs_db = Path(args.jobs_db) if args.jobs_db else find_jobs_db(input_path)
    job_id = str(artifact.get("job_id") or "")
    if jobs_db and job_id:
        times = load_job_times(jobs_db, job_id)
        duration = metrics.duration_minutes(times.get("created_at"), times.get("finished_at"))
        duration["source"] = str(jobs_db)
    else:
        duration = metrics.duration_minutes(None, None)
        duration["source"] = None

    issues = report.build_issues(sections, aligned_dicts, cov)
    rep = report.build_report(
        eval_set=args.eval_set,
        input_path=input_path,
        artifact=artifact,
        alignment_summary=alignment_summary,
        metrics_block={
            "coverage": cov,
            "placeholder": ph,
            "leak": leak,
            "fact_conflicts": {"computed": False, "count": len(conflicts)},
            "duration": duration,
        },
        issues=issues,
    )
    report_path, summary_path = report.write_outputs(rep, Path(args.reports_dir))

    cov_ratio = cov["ratio"]
    print(f"报告: {report_path}")
    print(f"摘要: {summary_path}")
    print(
        f"覆盖率 {cov_ratio * 100:.1f}% ({cov['covered']}/{cov['applicable']})"
        if cov_ratio is not None
        else "覆盖率 N/A（无可对齐章节）",
        f"| 占位 {ph['marker_count']} 处/{ph['section_count']} 节"
        f"| 对齐 {alignment_summary['aligned']}/{alignment_summary['sections_total']}"
        f"| 耗时 {duration['minutes'] if duration['computed'] else '未知'} 分钟",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
