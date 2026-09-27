#!/usr/bin/env python3
"""Generate the human medical-gate queue (medical_gate_queue.md).

Plain-language side-by-side rendering of every fidelity_blocked item:
原文段落 vs 中文译文段落 vs 发现的问题.  Read-only; no disposition.
"""
import json
import re
import sqlite3
from collections import defaultdict

DB = "runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/writing_reference.sqlite3"
OUT = "runs/requirements_v2_20260919/t17_round23_replay/medical_gate_queue.md"

CODE_DESC = {
    "numeric_tokens_changed": "数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）",
    "source_abbreviation_missing": "原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）",
    "comparison_direction_changed": "比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）",
    "unit_sequence_changed": "内容顺序/语序改变（条目排列或分句顺序与原文不同）",
    "unsupported_medical_concept_added": "译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）",
    "numbered_criterion_cardinality_changed": "编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）",
    "regulatory_chinese_term_calque": "监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）",
}
SEG_MARK = re.compile(r"\[\[/?(?:CMS_SEG_\d+)\]\]\s*")
UNIT_RE = re.compile(r"^unit_(\d+):")


def humanize_codes(codes):
    out = []
    for c in codes or []:
        m = UNIT_RE.match(c)
        base = c.split(":", 1)[1] if ":" in c else c
        desc = CODE_DESC.get(base, "（未知问题类型，原文样式的检查器代码）")
        if m:
            out.append(f"译文第 {m.group(1)} 单元（段）：{desc}（检查器代码 `{c}`）")
        else:
            out.append(f"{desc}（检查器代码 `{c}`）")
    return out or ["（该条目未记录单元级忠度代码）"]


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    items = con.execute(
        """
        SELECT payload_json FROM writing_reference_translation_batch_items
        WHERE generation_status='fidelity_blocked'
        ORDER BY project_id, json_extract(payload_json,'$.nct_id'), item_id
        """
    ).fetchall()
    stats = {"total": 0, "with_aligned": 0, "with_raw": 0,
             "lineage": 0, "source_full": 0, "source_short": 0}
    by_project = defaultdict(lambda: defaultdict(list))
    plan_cache, span_cache = {}, {}
    for r in items:
        p = json.loads(r["payload_json"])
        proj = p["project_id"]
        plan_cache.setdefault(proj, {})
        span_cache.setdefault(proj, {})
        stats["total"] += 1
        # --- chapter source via docplan ---
        src = ""
        plan_row = None
        if p.get("document_structure_plan_id"):
            if p["document_structure_plan_id"] not in plan_cache[proj]:
                pr = con.execute(
                    "SELECT payload_json FROM writing_reference_document_structure_plans"
                    " WHERE project_id=? AND plan_id=?",
                    (proj, p["document_structure_plan_id"]),
                ).fetchone()
                plan_cache[proj][p["document_structure_plan_id"]] = (
                    json.loads(pr["payload_json"]) if pr else None)
            plan = plan_cache[proj][p["document_structure_plan_id"]]
            if plan:
                ch = next((c for c in plan.get("chapters", [])
                           if c.get("chapter_id") == p.get("chapter_id")), None)
                texts = []
                for sid in (ch or {}).get("source_span_ids", []):
                    if sid not in span_cache[proj]:
                        sr = con.execute(
                            "SELECT payload_json FROM writing_reference_source_spans"
                            " WHERE project_id=? AND span_id=?", (proj, sid)).fetchone()
                        span_cache[proj][sid] = (
                            json.loads(sr["payload_json"]).get("source_text") or ""
                            if sr else "")
                    texts.append(span_cache[proj][sid])
                src = "\n".join(t for t in texts if t)
        # --- chinese translation via integration row ---
        zh, zh_kind = "", ""
        tr = con.execute(
            "SELECT payload_json FROM writing_reference_translation_records"
            " WHERE project_id=? AND translation_id=? AND revision=?",
            (proj, p.get("translation_id"), p.get("translation_revision")),
        ).fetchone()
        integ_id = (json.loads(tr["payload_json"]).get("chapter_integration_result_id")
                    if tr else None)
        if integ_id:
            ir = con.execute(
                "SELECT payload_json FROM writing_reference_chapter_integration_results"
                " WHERE project_id=? AND integration_id=?", (proj, integ_id)).fetchone()
            if ir:
                d = json.loads(ir["payload_json"])
                zh = d.get("blocked_aligned_output") or ""
                if zh:
                    stats["with_aligned"] += 1
                    zh_kind = "对齐译文（管线组装的被拦译文）"
                else:
                    zh = d.get("blocked_raw_provider_output") or ""
                    if zh:
                        stats["with_raw"] += 1
                        zh_kind = "原始模型输出（未经对齐组装）"
        # --- unit-level lineage (best effort) ---
        lr = con.execute(
            "SELECT payload_json FROM writing_reference_translation_chunks"
            " WHERE project_id=? AND chapter_id=? AND chunk_id LIKE '%:blocked'",
            (proj, p.get("chapter_id")),
        ).fetchall()
        unit_pairs = []
        if lr:
            stats["lineage"] += 1
            d = json.loads(lr[0]["payload_json"])
            targets = d.get("unit_targets") or {}
            if targets and d.get("source_text"):
                import sys
                sys.path.insert(0, ".")
                from services.api.app.chapter_translation_pipeline import (
                    split_source_into_units,
                )
                units = {u.ordinal: u.text for u in
                         split_source_into_units(d["source_text"])}
                for k in sorted(targets, key=lambda x: int(x)):
                    unit_pairs.append((k, units.get(int(k), "（源文单元缺失）"),
                                       targets[k]))
        by_project[proj][p.get("nct_id") or "(无NCT)"].append(
            (p, src, zh, zh_kind, unit_pairs))
        if len(src) >= 80:
            stats["source_full"] += 1
        else:
            stats["source_short"] += 1

    lines = []
    ap = lines.append
    ap("# 医学人工门·忠度拦截待处置清单（medical gate queue）")
    ap("")
    ap("生成时间：2026-09-27（第23轮）。本清单只汇总证据、**不做任何处置**；")
    ap("每项是否放行/重译/废弃，由医学经理人工裁定。数据源：隔离runtime库")
    ap("（5301工作台所用 writing_reference.sqlite3）中全部")
    ap("generation_status=fidelity_blocked 的翻译条目。")
    ap("")
    ap("## 范围与数量")
    ap("")
    ap("| 项目 | 研究数 | 拦截条目数 |")
    ap("|---|---|---|")
    for proj, studies in by_project.items():
        label = ("K3 项目（本轮样本与第1波）" if proj == "proj_user_fad9f64f3151"
                 else "存量项目 proj_user_a5f104df6d03")
        ap(f"| {label} | {len(studies)} | {sum(len(v) for v in studies.values())} |")
    ap(f"| **合计** | {sum(len(v) for v in by_project.values())} | {stats['total']} |")
    ap("")
    ap("说明：口径=隔离runtime库现状（存量165 + 本轮第1波新增37 + 样本1）。")
    ap("另一份 390 项的旧快照读的是共享runtime库（2026-09-27 20:44），")
    ap("不属于本工作台本轮操作面，未并入本清单。")
    ap("")
    ap("## 阅读方法")
    ap("")
    ap("- **发现的问题**由确定性忠度检查器输出翻译成人话；“第 N 单元（段）”指")
    ap("  译文按原文切分后的第 N 段。带“请重点复核”的是医学含义风险较高的类型")
    ap("  （比较方向、概念新增、条目数量）。")
    ap("- **原文段落**为该章节的英文原文（按文档计划拼装的源文；个别历史条目")
    ap("  仅存锚点短标题，已如实标注——那是历史谱系缺口的表现）。")
    ap("- **中文译文段落**为被拦时的中文译文（标注“对齐译文”或“原始模型输出”）。")
    ap(f"- 覆盖统计：有对齐译文 {stats['with_aligned']} 项、仅原始输出 {stats['with_raw']} 项；")
    ap(f"  有单元级谱系 {stats['lineage']} 项；原文段落完整（≥80字符）{stats['source_full']} 项、")
    ap(f"  过短/缺失 {stats['source_short']} 项。")
    ap("")
    proj_no = 0
    for proj, studies in sorted(by_project.items()):
        proj_no += 1
        label = ("K3 项目（proj_user_fad9f64f3151）"
                 if proj == "proj_user_fad9f64f3151"
                 else f"存量项目（{proj}）")
        ap(f"\n---\n\n# {proj_no}. {label}\n")
        for nct, items_ in sorted(studies.items()):
            ap(f"## 研究 {nct}（{len(items_)} 项待处置）\n")
            for idx, (p, src, zh, zh_kind, unit_pairs) in enumerate(items_, 1):
                title = p.get("chapter_title") or "（无章节标题）"
                ap(f"### {nct}·条目 {idx}：{title}")
                ap("")
                ap(f"- 条目ID：`{p['item_id']}`（第 {p.get('attempt')} 次尝试被拦）")
                ap("- **发现的问题：**")
                for h in humanize_codes(p.get("fidelity_failure_codes")):
                    ap(f"  - {h}")
                if unit_pairs:
                    ap("- **问题单元对照（仅列被点名单元）：**")
                    for k, usrc, utgt in unit_pairs:
                        ap(f"  - 第 {k} 单元原文：{usrc[:600]}")
                        ap(f"  - 第 {k} 单元译文：{utgt[:600]}")
                ap("")
                ap(f"**【原文段落】**（英文原文）")
                ap("")
                if src:
                    show = src if len(src) <= 2200 else src[:1800] + "\n…（中略）…\n" + src[-300:]
                    ap("> " + show.replace("\n", "\n> "))
                else:
                    ap(">（历史谱系缺口：该条目章节源文未能从库内恢复，")
                    ap("> 如需完整原文请以文档ID调阅原件。）")
                ap("")
                ap(f"**【中文译文段落】**（{zh_kind or '库内未存译文'}）")
                ap("")
                if zh:
                    zh_clean = SEG_MARK.sub("", zh)
                    show = zh_clean if len(zh_clean) <= 2200 else \
                        zh_clean[:1800] + "\n…（中略）…\n" + zh_clean[-300:]
                    ap("> " + show.replace("\n", "\n> "))
                else:
                    ap(">（库内未存该条目的被拦译文文本。）")
                ap("")
    with open(OUT, "w") as f:
        f.write("\n".join(lines))
    print("wrote", OUT, "bytes:", sum(len(x) + 1 for x in lines))
    print("stats:", stats)


if __name__ == "__main__":
    main()
