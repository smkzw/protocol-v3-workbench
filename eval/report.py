#!/usr/bin/env python3
"""WP-M1-EVAL 报告层：组装报告对象并渲染一页 summary.md（只含分数与前10问题）。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

REPORT_SCHEMA_VERSION = "mw_eval_report_v1"
SUMMARY_MAX_ISSUES = 10

# 问题severity排序：占位/空节 > 短文/未对齐
_SEVERITY_RANK = {"placeholder_marker": 0, "empty_body": 1, "short_body": 2, "unaligned": 3}
_SEVERITY_LABEL = {
    "placeholder_marker": "占位标记",
    "empty_body": "空正文",
    "short_body": "正文过短",
    "unaligned": "未能对齐",
}


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha8(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def build_issues(sections: list[dict], aligned_records: list[dict], coverage_result: dict) -> list[dict]:
    """按文档顺序生成节级问题清单；排序后取前 N 由调用方决定。"""
    from metrics import MIN_BODY_CJK_CHARS, cjk_char_count, has_placeholder_marker

    node_by_sid = {r["section_id"]: r.get("semantic_node_id") for r in aligned_records}
    issues: list[dict] = []
    for s in sections:
        sid = str(s.get("section_id", ""))
        text = s.get("proposal_text") or ""
        where = f"§{s.get('section_number', '')} {s.get('heading', '')}".strip()
        if has_placeholder_marker(text):
            issues.append({"kind": "placeholder_marker", "severity": "high", "where": where})
        elif not text.strip() and node_by_sid.get(sid):
            issues.append({"kind": "empty_body", "severity": "high", "where": where})
        elif 0 < cjk_char_count(text) < MIN_BODY_CJK_CHARS and node_by_sid.get(sid):
            issues.append({"kind": "short_body", "severity": "medium", "where": where})
        if not node_by_sid.get(sid):
            issues.append({"kind": "unaligned", "severity": "medium", "where": where})
    issues.sort(key=lambda i: (_SEVERITY_RANK.get(i["kind"], 9),))
    _ = coverage_result
    return issues


def build_report(
    eval_set: str,
    input_path: Path,
    artifact: dict,
    alignment_summary: dict,
    metrics_block: dict,
    issues: list[dict],
) -> dict:
    input_sha = sha256_of_file(input_path)
    sha8 = git_sha8(input_path.resolve().parent) or input_sha[:8]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "set": eval_set,
        "input": {
            "path": str(input_path),
            "sha256": input_sha,
            "sha8": sha8,
            "schema_version": artifact.get("schema_version"),
            "job_id": artifact.get("job_id"),
            "project_id": artifact.get("project_id"),
            "document_id": artifact.get("document_id"),
        },
        "alignment": alignment_summary,
        "metrics": metrics_block,
        "issues_total": len(issues),
        "issues_top": issues[:SUMMARY_MAX_ISSUES],
    }


def render_summary_md(report: dict) -> str:
    m = report["metrics"]
    cov = m["coverage"]
    ph = m["placeholder"]
    leak = m["leak"]
    dur = m["duration"]
    conf = m["fact_conflicts"]
    lines = [
        "# 医学写作全文评测 summary",
        "",
        f"- 评测集：{report['set']}　生成时间：{report['generated_at']}",
        f"- 产物：job `{report['input']['job_id']}`（project `{report['input']['project_id']}`）",
        f"- 输入 sha8：`{report['input']['sha8']}`　schema：{report['input']['schema_version']}",
        "",
        "## 分数",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 覆盖率 | {_pct(cov['ratio'])}（{cov['covered']}/{cov['applicable']} 个适用节点） |",
        f"| 占位标记 | {ph['marker_count']} 处（{ph['section_count']} 节） |",
        "| 泄漏率 | "
        + (_pct(leak["section_leak_ratio"]) if leak.get("computed") else "未计算（无竞品词表）")
        + " |",
        "| 事实冲突 | " + (str(conf["count"]) if conf.get("computed") else "未计算（首版空实现）") + " |",
        "| 全文耗时 | "
        + (f"{dur['minutes']} 分钟" if dur.get("computed") and dur.get("minutes") is not None else "未知")
        + " |",
        f"| 对齐 | {report['alignment']['aligned']}/{report['alignment']['sections_total']} 节"
        f"（exact {report['alignment']['by_kind']['exact']}、approx {report['alignment']['by_kind']['approx']}、"
        f"number_only {report['alignment']['by_kind']['number_only']}、"
        f"native {report['alignment']['by_kind']['native']}、未对齐 {report['alignment']['by_kind']['unmatched']}） |",
        "",
        f"## 前 {SUMMARY_MAX_ISSUES} 问题（共 {report['issues_total']}）",
        "",
    ]
    top = report["issues_top"]
    if not top:
        lines.append("（无）")
    for i, issue in enumerate(top, 1):
        label = _SEVERITY_LABEL.get(issue["kind"], issue["kind"])
        lines.append(f"{i}. [{issue['severity']}] {label}：{issue['where']}")
    lines.append("")
    lines.append("> 本 summary 只含分数与问题清单，不含参照正文。")
    return "\n".join(lines)


def _pct(ratio: float | None) -> str:
    return f"{ratio * 100:.1f}%" if ratio is not None else "N/A"


def write_outputs(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    report_path = reports_dir / f"{date}_{report['input']['sha8']}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary_path = reports_dir / "summary.md"
    summary_path.write_text(render_summary_md(report), encoding="utf-8")
    return report_path, summary_path
