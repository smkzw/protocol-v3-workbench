#!/usr/bin/env python3
"""Independent source-semantic checks for GLM research-seed candidates.

Read-only against original DOCX / compiled units / outcome.
Writes extracts under this scratch directory only.
Does not import product packages.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(__file__).resolve().parent
DOCX = Path(
    "/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/"
    "MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx"
)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def paragraph_text(element: ET.Element) -> str:
    chunks: list[str] = []
    for node in element.iter():
        tag = node.tag
        if tag == W + "t":
            chunks.append(node.text or "")
        elif tag == W + "tab":
            chunks.append("\t")
        elif tag in {W + "br", W + "cr"}:
            chunks.append("\n")
        elif tag == W + "delText":
            chunks.append("")  # deleted text not admitted as live
    return "".join(chunks).strip()


def paragraph_deleted_text(element: ET.Element) -> str:
    return "".join(
        (n.text or "") for n in element.iter(W + "delText")
    ).strip()


def resolve_locator(xml_roots: dict[str, ET.Element], locator: str) -> ET.Element | None:
    """Walk 0-based index:tag path. Independent of product parser."""
    parts = locator.split("/")
    if len(parts) < 2:
        return None
    # word/document.xml/body/446:p  OR word/header1.xml/...
    if parts[0] == "word" and parts[1].endswith(".xml"):
        part = parts[0] + "/" + parts[1]
        rest = parts[2:]
    else:
        return None
    root = xml_roots.get(part)
    if root is None:
        return None
    node: ET.Element | None = root
    # first rest token may be 'body' without index
    if rest and ":" not in rest[0]:
        tag = rest[0]
        found = None
        for child in list(node):
            if child.tag.split("}")[-1] == tag:
                found = child
                break
        if found is None:
            return None
        node = found
        rest = rest[1:]
    for token in rest:
        if ":" not in token:
            return None
        idx_s, tag = token.split(":", 1)
        try:
            idx = int(idx_s)
        except ValueError:
            return None
        children = list(node)
        if idx < 0 or idx >= len(children):
            return None
        child = children[idx]
        if child.tag.split("}")[-1] != tag:
            return None
        node = child
    return node


def nearby_units(units_by_loc: dict, loc: str, window: int = 4) -> list[dict]:
    # order units as stored
    return []  # filled by caller with ordered list


def main() -> None:
    compiled = load_json(ROOT / "original_compiled_input.json")
    outcome = load_json(ROOT / "outcome.json")
    identity = load_json(ROOT / "identity.json")
    receipt = load_json(ROOT / "owner_receipt_summary.json")
    manifest = load_json(ROOT / "artifact_manifest.json")

    hashes = {}
    for item in manifest["files"]:
        p = Path(item["path"])
        hashes[p.name] = {
            "path": str(p),
            "expected": item["sha256"],
            "actual": sha256_file(p),
            "size": p.stat().st_size,
            "match": sha256_file(p) == item["sha256"],
        }

    src = compiled["sources"][0]
    units = src["units"]
    units_by_loc = {u["locator"]: u for u in units}
    loc_order = [u["locator"] for u in units]
    loc_index = {loc: i for i, loc in enumerate(loc_order)}

    fields = outcome["validation"]["proposal"]["fields"]
    n_cand = sum(len(v) for v in fields.values())
    n_refs = sum(len(c["references"]) for arr in fields.values() for c in arr)

    # load DOCX xml parts
    payload = DOCX.read_bytes()
    xml_roots: dict[str, ET.Element] = {}
    with zipfile.ZipFile(DOCX) as zf:
        namelist = zf.namelist()
        for name in namelist:
            if name.startswith("word/") and name.endswith(".xml"):
                xml_roots[name] = ET.fromstring(zf.read(name))
        drawings = 0
        if "word/document.xml" in xml_roots:
            drawings = len(xml_roots["word/document.xml"].findall(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline"))
            drawings += len(xml_roots["word/document.xml"].findall(".//" + W + "drawing"))
            drawings += len(xml_roots["word/document.xml"].findall(".//" + W + "pict"))

    # tracked changes?
    tracked = False
    for root in xml_roots.values():
        if root.find(".//" + W + "ins") is not None or root.find(".//" + W + "del") is not None:
            tracked = True
            break

    rows = []
    quote_issues = []
    xml_issues = []
    context_pack = {}

    for field, arr in fields.items():
        for idx, cand in enumerate(arr):
            rec = {
                "id": f"{field}[{idx}]",
                "field": field,
                "index": idx,
                "candidate": cand["candidate"],
                "raw": cand["raw"],
                "reason": cand["reason"],
                "confidence": cand["confidence"],
                "confidence_basis": cand.get("confidence_basis"),
                "basis": cand.get("basis"),
                "source_support": cand.get("source_support"),
                "requires_confirmation": cand.get("requires_confirmation"),
                "canonical": cand.get("canonical"),
                "n_refs": len(cand["references"]),
                "refs": [],
            }
            # candidate extras vs raw
            rec["candidate_equals_raw"] = cand["candidate"] == cand["raw"]
            rec["raw_in_candidate"] = cand["raw"].rstrip("；。;.") in cand["candidate"]
            rec["candidate_added_suffix"] = None
            if cand["candidate"].startswith(cand["raw"].rstrip("；。;")):
                rec["candidate_added_suffix"] = cand["candidate"][len(cand["raw"].rstrip("；。;")) :]
            elif cand["raw"].rstrip("；。;") in cand["candidate"]:
                rec["candidate_added_suffix"] = "contains_raw_plus_other"

            for r_i, ref in enumerate(cand["references"]):
                loc = ref["locator"]
                quote = ref["quote"]
                sid = ref["source_artifact_id"]
                unit = units_by_loc.get(loc)
                unit_text = unit["text"] if unit else None
                unit_role = unit.get("role") if unit else None
                unit_kind = unit.get("kind") if unit else None
                quote_eq_unit = unit_text == quote if unit_text is not None else False
                quote_in_unit = (quote in unit_text) if unit_text is not None else False
                raw_eq_quote = cand["raw"] == quote
                raw_in_unit = (cand["raw"] in unit_text) if unit_text is not None else False

                xml_node = resolve_locator(xml_roots, loc)
                xml_text = paragraph_text(xml_node) if xml_node is not None else None
                xml_tag = xml_node.tag.split("}")[-1] if xml_node is not None else None
                xml_deleted = paragraph_deleted_text(xml_node) if xml_node is not None else None
                quote_eq_xml = xml_text == quote if xml_text is not None else False
                quote_in_xml = (quote in xml_text) if xml_text is not None else False
                unit_eq_xml = (unit_text == xml_text) if unit_text is not None and xml_text is not None else False

                # neighbors
                neighbors = []
                if loc in loc_index:
                    i0 = loc_index[loc]
                    for j in range(max(0, i0 - 5), min(len(loc_order), i0 + 6)):
                        u = units[j]
                        neighbors.append({
                            "offset": j - i0,
                            "locator": u["locator"],
                            "role": u.get("role"),
                            "kind": u.get("kind"),
                            "text": u["text"][:400],
                        })

                ref_rec = {
                    "ref_index": r_i,
                    "locator": loc,
                    "quote": quote,
                    "source_artifact_id": sid,
                    "sid_match": sid == src["source_artifact_id"],
                    "unit_found": unit is not None,
                    "unit_role": unit_role,
                    "unit_kind": unit_kind,
                    "quote_eq_unit": quote_eq_unit,
                    "quote_in_unit": quote_in_unit,
                    "raw_eq_quote": raw_eq_quote,
                    "raw_in_unit": raw_in_unit,
                    "xml_found": xml_node is not None,
                    "xml_tag": xml_tag,
                    "quote_eq_xml": quote_eq_xml,
                    "quote_in_xml": quote_in_xml,
                    "unit_eq_xml": unit_eq_xml,
                    "xml_text": xml_text,
                    "xml_deleted": xml_deleted,
                    "unit_text": unit_text,
                    "quote_xml_diff": None if quote_eq_xml else {
                        "quote": quote,
                        "xml": xml_text,
                    },
                    "neighbors": neighbors,
                }
                rec["refs"].append(ref_rec)
                if not quote_eq_unit or not quote_eq_xml or not unit or xml_node is None:
                    quote_issues.append({
                        "id": rec["id"],
                        "locator": loc,
                        "quote_eq_unit": quote_eq_unit,
                        "quote_eq_xml": quote_eq_xml,
                        "unit_found": unit is not None,
                        "xml_found": xml_node is not None,
                        "unit_role": unit_role,
                        "sid_match": sid == src["source_artifact_id"],
                    })
                context_pack[f"{rec['id']}#r{r_i}"] = {
                    "locator": loc,
                    "neighbors": neighbors,
                    "xml_text": xml_text,
                    "unit_text": unit_text,
                    "quote": quote,
                }
            rows.append(rec)

    # numeric token check: numbers/units in candidate vs union of quotes/raw
    num_pat = re.compile(
        r"\d+(?:\.\d+)?\s*(?:mg|ml|mL|kg|周|天|岁|例|分|次|%|mg/kg)?"
        r"|Q\d+W|W\d+|III|Ⅲ|1\s*[:：]\s*1|IL-4Rα|IgG4|FcRn",
        re.I,
    )

    def tokens(s: str) -> set[str]:
        return set(num_pat.findall(s)) | set(re.findall(r"\d+(?:\.\d+)?", s))

    for rec in rows:
        cand_toks = tokens(rec["candidate"]) | tokens(rec["reason"])
        src_toks = tokens(rec["raw"])
        for ref in rec["refs"]:
            src_toks |= tokens(ref["quote"])
            if ref["unit_text"]:
                src_toks |= tokens(ref["unit_text"])
            for nb in ref["neighbors"]:
                if abs(nb["offset"]) <= 2:
                    src_toks |= tokens(nb["text"])
        rec["candidate_reason_tokens"] = sorted(cand_toks)
        rec["source_tokens_near"] = sorted(src_toks)
        rec["tokens_not_in_near_source"] = sorted(cand_toks - src_toks)

    # keyword inventory in full units for missing-context scan
    full_text = "\n".join(u["text"] for u in units if u.get("role") == "body")
    searches = {
        "主要终点": "主要终点",
        "次要终点": "次要终点",
        "关键次要": "关键次要",
        "样本量226": "226",
        "开放标签": "开放",
        "继续治疗期": "继续治疗期",
        "随访": "随访期",
        "筛选期": "筛选期",
        "双盲治疗期": "双盲治疗期",
        "哮喘": "哮喘",
        "特应性皮炎": "特应性皮炎",
        "AD": "AD",
        "度普利尤": "度普利尤",
        "奥马珠": "奥马珠",
        "rescue": "急救",
        "背景治疗": "背景治疗",
        "分层": "分层",
        "UAS7": "UAS7",
        "ISS7": "ISS7",
        "HSS7": "HSS7",
        "AAS7": "AAS7",
        "UCT": "UCT",
        "青少年": "青少年",
        "儿童": "儿童",
        "妊娠": "妊娠",
        "排除": "排除标准",
        "入选": "入选标准",
        "Q2W": "Q2W",
        "Q4W": "Q4W",
        "600 mg": "600 mg",
        "300 mg": "300 mg",
        "150 mg": "150 mg",
        "图2": "图2",
        "研究流程图": "研究流程图",
        "安慰剂对照": "安慰剂对照",
        "阳性对照": "阳性对照",
        "活性对照": "活性对照",
        "多中心": "多中心",
        "中国": "中国",
        "全球": "全球",
        "PK": "药代",
        "ADA": "ADA",
        "免疫原性": "免疫原性",
        "负荷": "负荷",
        "维持": "维持",
        "交叉": "交叉",
        "揭盲": "揭盲",
        "盲态": "盲态",
        "西替利嗪": "西替利嗪",
        "氯雷他定": "氯雷他定",
        "倍剂量": "倍剂量",
        "4倍": "4倍",
        "批准剂量": "批准剂量",
        "II期": "II期",
        "I期": "I期",
        "Ⅲ期": "Ⅲ期",
        "III期": "III期",
        "CSU": "CSU",
        "慢性自发性荨麻疹": "慢性自发性荨麻疹",
        "慢性诱导性": "慢性诱导性",
        "CIndU": "CIndU",
        "体重": "体重",
        "30kg": "30kg",
        "12周岁": "12周岁",
        "75周岁": "75周岁",
        "IL-4R": "IL-4R",
        "IL-13": "IL-13",
        "IgE": "IgE",
        "预充式": "预充式",
        "皮下": "皮下",
        "静脉": "静脉",
        "注射液": "注射液",
        "人源化": "人源化",
        "CHO": "CHO",
        "FcRn": "FcRn",
        "半衰期": "半衰期",
        "方案编号": "方案编号",
        "V1.3": "1.3",
        "湖南麦济": "湖南麦济",
        "晋红中": "晋红中",
        "随机": "随机",
        "双盲": "双盲",
        "1:1": "1:1",
        "1：1": "1：1",
        "113例": "113",
        "80%": "80%",
        "检验效能": "检验效能",
        "抗IgE": "抗IgE",
        "血管性水肿": "血管性水肿",
        "知情同意": "知情同意",
        "筛选时确诊": "筛选时确诊",
        "6个月": "6个月",
        "W0-W24": "W0",
        "W24-W48": "W24",
        "W48": "W48",
        "W56": "W56",
        "安全随访": "安全随访",
    }
    search_hits = {}
    for key, needle in searches.items():
        hits = []
        for u in units:
            if needle in u["text"] and u.get("role") == "body":
                hits.append({"locator": u["locator"], "kind": u["kind"], "text": u["text"][:240]})
        search_hits[key] = {"count": len(hits), "sample": hits[:8]}

    # heading inventory
    headings = [
        {"locator": u["locator"], "text": u["text"]}
        for u in units
        if u.get("role") == "heading"
    ]

    # table 135 structure dump for dose/synopsis
    tbl135 = [u for u in units if u["locator"].startswith("word/document.xml/body/135:tbl/")]
    tbl135_rows = defaultdict(list)
    for u in tbl135:
        m = re.search(r"/(\d+):tr/", u["locator"])
        if m:
            tbl135_rows[int(m.group(1))].append(u)

    synopsis_rows = []
    for ri, cells in sorted(tbl135_rows.items()):
        texts = [c["text"][:120] for c in cells]
        synopsis_rows.append({"tr": ri, "n_cells": len(cells), "texts": texts[:6]})

    # dose section body paras 400-460
    dose_window = []
    for u in units:
        m = re.match(r"word/document.xml/body/(\d+):p$", u["locator"])
        if m and 390 <= int(m.group(1)) <= 460:
            dose_window.append({"locator": u["locator"], "role": u.get("role"), "text": u["text"]})

    design_window = []
    for u in units:
        m = re.match(r"word/document.xml/body/(\d+):p$", u["locator"])
        if m and 250 <= int(m.group(1)) <= 330:
            design_window.append({"locator": u["locator"], "role": u.get("role"), "text": u["text"][:500]})

    pop_window = []
    for u in units:
        m = re.match(r"word/document.xml/body/(\d+):p$", u["locator"])
        if m and 315 <= int(m.group(1)) <= 380:
            pop_window.append({"locator": u["locator"], "role": u.get("role"), "text": u["text"][:500]})

    mech_window = []
    for u in units:
        m = re.match(r"word/document.xml/body/(\d+):p$", u["locator"])
        if m and 170 <= int(m.group(1)) <= 220:
            mech_window.append({"locator": u["locator"], "role": u.get("role"), "text": u["text"][:500]})

    # whitespace-normalized quote mismatches
    def norm(s: str | None) -> str:
        if s is None:
            return ""
        return re.sub(r"\s+", "", s)

    ws_only = []
    for rec in rows:
        for ref in rec["refs"]:
            if ref["xml_text"] and not ref["quote_eq_xml"]:
                ws_only.append({
                    "id": rec["id"],
                    "locator": ref["locator"],
                    "norm_eq": norm(ref["quote"]) == norm(ref["xml_text"]),
                    "quote": ref["quote"],
                    "xml": ref["xml_text"],
                })

    # unique locators
    all_locs = [ref["locator"] for rec in rows for ref in rec["refs"]]
    loc_counter = Counter(all_locs)

    summary = {
        "hashes": hashes,
        "identity": identity,
        "receipt_observed_model": receipt["receipt"]["observed_model"],
        "receipt_output_sha256": receipt["receipt"]["output_sha256"],
        "compiled_file_sha256": hashes["original_compiled_input.json"]["actual"],
        "identity_input_sha256": identity["input_sha256"],
        "proposal_input_sha256": outcome["validation"]["proposal"]["input_sha256"],
        "source_artifact_id": src["source_artifact_id"],
        "source_content_sha256": src["content_sha256"],
        "source_role": src["source_role"],
        "source_version": src["source_version"],
        "parser_version": src["parser_version"],
        "n_units": len(units),
        "unit_kind": dict(Counter(u["kind"] for u in units)),
        "unit_role": dict(Counter(u.get("role") for u in units)),
        "diagnostics": src["diagnostics"],
        "n_candidates": n_cand,
        "n_references": n_refs,
        "candidates_per_field": {k: len(v) for k, v in fields.items()},
        "docx_sha256": hashes[DOCX.name]["actual"],
        "tracked_changes_xml": tracked,
        "drawing_nodes_approx": drawings,
        "quote_issue_count": len(quote_issues),
        "quote_issues": quote_issues,
        "ws_only_xml_mismatches": ws_only,
        "unique_locators": len(loc_counter),
        "repeated_locators": {k: v for k, v in loc_counter.items() if v > 1},
        "toc_cited": [
            rec["id"]
            for rec in rows
            for ref in rec["refs"]
            if ref["unit_role"] == "derived_toc"
        ],
        "heading_cited": [
            rec["id"]
            for rec in rows
            for ref in rec["refs"]
            if ref["unit_role"] == "heading"
        ],
        "tokens_not_in_near_source": {
            rec["id"]: rec["tokens_not_in_near_source"]
            for rec in rows
            if rec["tokens_not_in_near_source"]
        },
        "candidate_suffixes": {
            rec["id"]: rec["candidate_added_suffix"]
            for rec in rows
            if rec["candidate_added_suffix"]
        },
        "canonical_all_null": all(c.get("canonical") in (None, {}) for rec in rows for c in [rec]),
        "all_basis_source": all(rec["basis"] == "source" for rec in rows),
        "all_requires_confirmation": all(rec["requires_confirmation"] is True for rec in rows),
        "all_source_support_reference_only": all(rec["source_support"] == "reference_only" for rec in rows),
        "confidence_basis_set": sorted({rec["confidence_basis"] for rec in rows}),
        "missing_fields": outcome["validation"]["proposal"].get("missing_fields"),
        "user_brief_match": compiled["user_brief"] == outcome["validation"]["proposal"]["user_brief"],
    }

    (SCRATCH / "verify_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "candidate_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "search_hits.json").write_text(
        json.dumps(search_hits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "headings.json").write_text(
        json.dumps(headings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "synopsis_table_rows.json").write_text(
        json.dumps(synopsis_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "dose_window.json").write_text(
        json.dumps(dose_window, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "design_window.json").write_text(
        json.dumps(design_window, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "pop_window.json").write_text(
        json.dumps(pop_window, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "mech_window.json").write_text(
        json.dumps(mech_window, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SCRATCH / "context_pack.json").write_text(
        json.dumps(context_pack, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("n_candidates", n_cand, "n_refs", n_refs)
    print("quote_issues", len(quote_issues))
    print("ws_only", len(ws_only))
    print("tokens_not_in_near", summary["tokens_not_in_near_source"])
    print("suffixes")
    for k, v in summary["candidate_suffixes"].items():
        print(" ", k, "=>", repr(v)[:200])
    print("toc_cited", summary["toc_cited"])
    print("tracked", tracked, "drawings", drawings)
    print("input_sha identity vs compiled file", identity["input_sha256"], hashes["original_compiled_input.json"]["actual"])
    print("source_content vs docx", src["content_sha256"], hashes[DOCX.name]["actual"])


if __name__ == "__main__":
    main()
