#!/usr/bin/env python3
"""WP-M1-FIXTURE 参照正文抽取：成型方案 → 语义节点切分（eval/fixtures 用）。

align.py（WP-M1-EVAL）的方向是 full-draft section → 语义节点；本脚本是它的反向：
对成型方案（docx/pdf）的正文段落按章节标题切分，并把每节归属到 TP-MA-07 v2 语义节点。

确定性规则（本脚本不含任何具体药物/疾病分支）：
- docx：zipfile+xml 按块级元素（w:p/w:tbl）顺序读取。标题识别双机制：
  1) 字面编号：段落文本以 `1.2.3` 式编号开头，且编号序列与前文一致（防正文序号误判）；
  2) 样式编号：字面编号命中过少时，退回标题样式（styles.xml 名称匹配 标题/heading）+
     由层级与顺序合成编号。
  另有前置章节（方案摘要/缩略语表/研究流程表等，无编号）按 FRONT_TITLES 识别。
- pdf：pdftotext -layout 抽文本；先解析目录页（点线引导行）得到权威标题清单，
  再在正文定位每个标题（编号与标题同行，或编号行+标题行相邻），按位置切片。
  页眉页脚等噪声行按默认规则过滤。
- 节点归属：用标题文本对 node_tree.json 的 title_zh 与 node_map.json 的 heading
  做归一化精确匹配 → 包含匹配 → 相似度匹配；都不中则 node_id=unmapped_<slug>。
  刻意不用 align.py 的 number_only 通道：成型方案的章号体系与 full-draft 产物不同，
  仅凭章号映射参照答案噪声过大。

用法：
  python3 tools/fixture/extract_sections.py \
      --source <方案路径> --kind docx|pdf --project-key <key> \
      --out eval/fixtures/<key>/reference_sections.jsonl
输出：reference_sections.jsonl（每行一节）+ stdout 摘要（含未匹配清单）。
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 前置章节标题 → 语义节点（TP-MA-07 v2 front/摘要节点）。归一化后精确匹配。
# 值为 None 表示识别为前置章节但没有对应语义节点（保留原文、标 unmapped）。
FRONT_TITLE_NODES = {
    "方案修订历史记录": "v2_n_front_1",
    "主要研究者签字页": "v2_n_front_2",
    "申办者签字页": "v2_n_front_3",
    "临床试验相关单位联系方式": "v2_n_front_4",
    "缩略语表": "v2_n_front_5",
    "缩略语": "v2_n_front_5",
    "目录": "v2_n_front_6",
    "表目录": "v2_n_front_7",
    "图目录": "v2_n_front_8",
    "方案摘要": "v2_n_1_1",
    "研究概要": "v2_n_1_1",
    "研究流程图": "v2_n_1_2",
    "研究流程表(soa)": "v2_n_1_3",
    "研究流程表": "v2_n_1_3",
    "试验流程表": "v2_n_1_3",
    "pk采血时间表": None,
    "pk采血表": None,
    "研究流程表(soa表)": "v2_n_1_3",
}

# 编号标题正则：`1.2 引言` / `9.2AE和SAE的处理` / `3、研究设计`
NUMBERED_HEADING_RE = re.compile(
    r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})[\.、]?\s+(\S.{0,60})$"
    r"|^\s*(\d{1,2}(?:\.\d{1,2}){0,3})([\u4e00-\u9fffA-Za-z（].{0,60})$"
)
# 标题正文不得以这些符号开头（防表格脚注 `1.＋表示…` 类误判）
BAD_TITLE_START = tuple("＋-—–·*±×>><<（()）【】[]\"'“”‘’/\\|,，、;；:：.。!！?？")


def norm_heading(text: str) -> str:
    """标题归一化：去空白、去结尾标点、统一全角括号，供匹配。"""
    t = re.sub(r"\s+", "", str(text or ""))
    t = t.replace("（", "(").replace("）", ")")
    t = t.rstrip(".:：、·-—")
    return t.lower()


def slugify(heading: str, index: int) -> str:
    """unmapped 节点 slug：保留 CJK 可读性，附加短 hash 防碰撞。"""
    s = re.sub(r"\s+", "_", str(heading or "section").strip())
    s = re.sub(r"[^\w\u4e00-\u9fff-]", "", s)[:24] or "section"
    digest = hashlib.sha1(f"{index}:{heading}".encode("utf-8")).hexdigest()[:6]
    return f"unmapped_{s}_{digest}"


# ---------------------------------------------------------------------------
# 标题序列一致性：编号候选必须"在当前进度之后"，且外层只允许 +1；
# 内层允许下一节（+1）、降级重开（回到1）或 ≤+2 的跳号（中间标题可能漏识别）。
# ---------------------------------------------------------------------------
def heading_sequence_ok(cand: list[int], last: list[int]) -> bool:
    if not cand:
        return False
    if not last:
        return cand[0] == 1
    if cand[0] == last[0] + 1:
        return len(cand) == 1 or cand[1] == 1
    if cand[0] != last[0]:
        return False
    if len(cand) == 1:
        return False  # 同章一级编号重复（如列表项）不算标题
    a, b = cand[1:], last[1:]
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            if i == n - 1 and len(a) > len(b):
                return a[i] == 1  # 进入更深一级
            return a[i] in (b[i] + 1, b[i] + 2, 1)
    # 前缀完全相同：更长 → 加深一级（末位应为1）；更短 → 收拢到上层下一节
    if len(a) > len(b):
        return a[len(b)] == 1
    return True


@dataclass
class RawSection:
    number: str
    heading: str
    level: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def docx_style_levels(path: Path) -> dict[str, int]:
    """styles.xml 里 标题/heading 样式 → 层级。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "word/styles.xml" not in names:
            return {}
        root = ET.fromstring(z.read("word/styles.xml"))
    levels: dict[str, int] = {}
    for st in root.iter(f"{W}style"):
        sid = st.get(f"{W}styleId") or ""
        nm = st.find(f"{W}name")
        name = (nm.get(f"{W}val") if nm is not None else "") or ""
        m = re.search(r"(?:标题|heading)\s*([1-9])", name, re.I)
        if not m:
            m2 = re.fullmatch(r"([1-9])", sid)  # 常见合成 id：'1'=标题1
            if m2 and ("标题" in name or "heading" in name.lower()):
                levels[sid] = int(m2.group(1))
                continue
            continue
        levels[sid] = int(m.group(1))
    return levels


def docx_blocks(path: Path) -> list[tuple[str, str, int | None]]:
    """块级顺序读取：(kind, text, style_id)。kind ∈ {p, tbl}；仅顶层 w:p 参与标题判定。"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")

    def para_text(p: ET.Element) -> str:
        return "".join(t.text or "" for t in p.iter(f"{W}t"))

    def table_text(tbl: ET.Element) -> str:
        rows_out: list[str] = []
        for tr in tbl.findall(f"{W}tr"):
            cells = []
            for tc in tr.findall(f"{W}tc"):
                cell_txt = " ".join(
                    para_text(p).strip() for p in tc.iter(f"{W}p") if para_text(p).strip()
                )
                cells.append(cell_txt)
            rows_out.append(" | ".join(cells))
        return "\n".join(r for r in rows_out if r.strip())

    blocks: list[tuple[str, str, int | None]] = []
    for child in body:
        tag = child.tag.replace(W, "")
        if tag == "p":
            pstyle = child.find(f"{W}pPr/{W}pStyle")
            sid = pstyle.get(f"{W}val") if pstyle is not None else None
            blocks.append(("p", para_text(child).strip(), sid))
        elif tag == "tbl":
            blocks.append(("tbl", table_text(child), None))
    return blocks


def docx_literal_sections(blocks: list[tuple[str, str, int | None]]) -> list[RawSection] | None:
    """机制1：字面编号标题 + 序列一致性。命中过少返回 None（触发样式回退）。"""
    sections: list[RawSection] = []
    last: list[int] = []
    rejected: list[str] = []
    cur: RawSection | None = None
    for kind, text, _sid in blocks:
        if kind != "p" or not text:
            if cur is not None and text:
                cur.lines.append(text)
            continue
        m = NUMBERED_HEADING_RE.match(text)
        accepted = False
        if m:
            num = m.group(1) or m.group(3)
            title = (m.group(2) or m.group(4) or "").strip()
            if not title.startswith(BAD_TITLE_START) and len(title) >= 2:
                cand = [int(x) for x in num.split(".")]
                if heading_sequence_ok(cand, last):
                    last = cand
                    cur = RawSection(
                        number=".".join(str(x) for x in cand),
                        heading=f"{num} {title}".strip(),
                        level=len(cand),
                    )
                    sections.append(cur)
                    accepted = True
        if not accepted:
            rejected.append(text[:40])
            if cur is not None:
                cur.lines.append(text)
    if len(sections) < 8:
        return None
    return sections


def docx_style_sections(
    blocks: list[tuple[str, str, int | None]], style_levels: dict[str, int]
) -> list[RawSection]:
    """机制2：标题样式 + 合成编号（成型方案正文无字面编号时）。"""
    sections: list[RawSection] = []
    counters = [0, 0, 0, 0, 0]
    cur: RawSection | None = None
    for kind, text, sid in blocks:
        if not text:
            continue
        lvl = style_levels.get(sid or "", None)
        if kind == "p" and lvl:
            counters[lvl - 1] += 1
            for k in range(lvl, 5):
                counters[k] = 0
            num = ".".join(str(c) for c in counters[:lvl])
            cur = RawSection(number=num, heading=text, level=lvl)
            sections.append(cur)
            continue
        if cur is not None:
            cur.lines.append(text)
    return sections


def split_docx(path: Path) -> tuple[list[RawSection], list[str]]:
    """返回 (sections, notes)。前置章节（FRONT_TITLES）在首个编号章之前识别。"""
    blocks = docx_blocks(path)
    sections = docx_literal_sections(blocks)
    notes = ["heading=literal_numbered"]
    if sections is None:
        sections = docx_style_sections(blocks, docx_style_levels(path))
        notes = ["heading=style_synthetic_numbering"]
    if not sections:
        return [], notes

    # 在首个编号章之前的块里识别前置章节（方案摘要/缩略语表/研究流程表等）
    first_num_line = None
    seen = 0
    for kind, text, _sid in blocks:
        if kind == "p" and text:
            seen += 1
    # 重新扫描：统计首个编号标题所在块序号
    idx = 0
    first_idx = None
    for i, (kind, text, sid) in enumerate(blocks):
        if kind != "p" or not text:
            continue
        m = NUMBERED_HEADING_RE.match(text)
        if m:
            num = m.group(1) or m.group(3)
            title = (m.group(2) or m.group(4) or "").strip()
            if not title.startswith(BAD_TITLE_START):
                cand = [int(x) for x in num.split(".")]
                if heading_sequence_ok(cand, []) and cand[0] == 1:
                    first_idx = i
                    break
    if first_idx is None:
        return sections, notes + ["front_matter=not_scanned"]

    front: list[RawSection] = []
    cur: RawSection | None = None
    for kind, text, sid in blocks[:first_idx]:
        if kind != "p" or not text:
            if cur is not None and text:
                cur.lines.append(text)
            continue
        key = norm_heading(text)
        if key in FRONT_TITLE_NODES and len(key) <= 12:
            cur = RawSection(number="", heading=text.strip(), level=0)
            front.append(cur)
            continue
        if cur is not None:
            cur.lines.append(text)
    front = [f for f in front if f.text or len(f.heading) <= 12]
    return front + sections, notes + [f"front_sections={len(front)}"]


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
PDF_NOISE_RE = re.compile(
    r"^\s*(机密专用文件|保密声明页脚|第\s*\d+\s*页\s*共\s*\d+\s*页|版本号及日期[:：].*|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*$"
)
TOC_LINE_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+(\S.*?)\s*\.{4,}\s*(\d+)\s*$")
TOC_UNNUM_RE = re.compile(r"^\s*([^\s.\d][^\.]{1,30}?)\s*\.{4,}\s*(\d+)\s*$")


def pdf_lines(path: Path) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), str(tmp)],
            check=True, capture_output=True,
        )
        raw = tmp.read_text(encoding="utf-8").splitlines()
    finally:
        tmp.unlink(missing_ok=True)
    return [ln.rstrip() for ln in raw]


def split_pdf(path: Path) -> tuple[list[RawSection], list[str]]:
    lines = pdf_lines(path)
    notes: list[str] = []
    # 1) 目录 → 权威标题清单（编号章 + 无编号前置章如「概要」）
    toc: list[tuple[str | None, str]] = []
    for ln in lines:
        m = TOC_LINE_RE.match(ln)
        if m:
            toc.append((m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()))
            continue
        m = TOC_UNNUM_RE.match(ln)
        if m and len(toc) == 0:  # 目录块起始处的无编号条目（如「概要」）
            toc.append((None, re.sub(r"\s+", " ", m.group(1)).strip()))
    if len(toc) < 8:
        raise SystemExit(f"pdf 目录解析仅得 {len(toc)} 条，无法定位正文标题：{path}")
    notes.append(f"toc_entries={len(toc)}")

    # 2) 全文顺序定位每个目录标题（成型方案里章1/流程表常排在目录页之前）
    def is_toc_dots(ln: str) -> bool:
        return bool(TOC_LINE_RE.match(ln) or TOC_UNNUM_RE.match(ln))

    positions: list[tuple[int, tuple[str | None, str]]] = []
    cursor = 0
    for num, title in toc:
        found = -1
        title_head = re.sub(r"\s+", "", title)[:6]
        for i in range(cursor, len(lines)):
            ln = lines[i].strip()
            if not ln or is_toc_dots(ln):
                continue
            if num is None:
                if re.sub(r"\s+", "", ln).startswith(title_head):
                    found = i
                    break
                continue
            num_pat = re.escape(num) + r"\.?"
            m = re.match(r"^" + num_pat + r"[\.\s、]+(.+)$", ln)
            if m:
                if re.sub(r"\s+", "", m.group(1)).startswith(title_head):
                    found = i
                    break
            elif re.fullmatch(num_pat + r"\.?", ln):
                # 编号独行，标题在下一非空行
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.sub(r"\s+", "", lines[j]).startswith(title_head):
                    found = i
                    break
        if found < 0:
            notes.append(f"toc_unlocated={num or ''} {title}")
            continue
        positions.append((found, (num, title)))
        cursor = found + 1

    # 3) 切片（噪声行=页眉页脚；行序保持文档顺序）
    sections: list[RawSection] = []
    bounds = [p for p, _ in positions] + [len(lines)]
    pre = [ln for ln in lines[0:bounds[0]] if ln.strip() and not PDF_NOISE_RE.match(ln)]
    if pre:
        sections.append(RawSection(number="", heading="前言（封面/签字页）", level=0, lines=pre))
    for k, (start, (num, title)) in enumerate(positions):
        end = bounds[k + 1]
        body: list[str] = []
        first = lines[start].strip()
        # 编号独行的情形，标题行在下一行；否则本行除编号外即标题/正文
        if num is not None and re.fullmatch(re.escape(num) + r"\.?", first):
            body.append(first)
        for ln in lines[start + 1 : end]:
            s = ln.strip()
            if not s or PDF_NOISE_RE.match(s):
                continue
            body.append(s)
        sections.append(
            RawSection(
                number=num or "",
                heading=(f"{num} {title}" if num else title),
                level=(num.count(".") + 1) if num else 0,
                lines=body,
            )
        )
    return sections, notes


# ---------------------------------------------------------------------------
# 节点归属
# ---------------------------------------------------------------------------
class NodeIndex:
    """TP-MA-07 v2 节点树 title_zh + eval/node_map.json heading 的归一化索引。"""

    # 高置信同义标题别名（成型方案常用章名 ↔ v2 节点）。只收确定项，宁缺毋滥。
    ALIAS_NODES = {
        "简介": "v2_n_2",
        "引言": "v2_n_2",
        "概要": "v2_n_1_1",
        "缩略语列表和术语定义": "v2_n_front_5",
        "试验时间表": "v2_n_1_3",
        "试验开始和结束": "v2_n_4_4",
    }

    def __init__(self, node_tree_path: Path, node_map_path: Path):
        self.title_by_norm: dict[str, tuple[str, str]] = {}
        tree = json.loads(node_tree_path.read_text(encoding="utf-8"))
        for n in tree.get("outlined_tree", {}).get("nodes", []):
            title = str(n.get("title_zh") or "").strip()
            if title:
                self.title_by_norm[norm_heading(title)] = (n["id"], "exact")
        self.map_by_norm: dict[str, tuple[str, str]] = {}
        nmap = json.loads(node_map_path.read_text(encoding="utf-8"))
        for e in nmap.get("entries", []):
            h = norm_heading(e["heading"])
            if h and h not in self.map_by_norm:
                self.map_by_norm[h] = (e["semantic_node_id"], e.get("match_quality", "approx"))

    def lookup(self, heading: str) -> tuple[str | None, str, str]:
        """返回 (node_id|None, match_quality, basis)。"""
        h = norm_heading(heading)
        # 去掉章号前缀再试
        h_bare = h
        m = re.match(r"^\d+(\.\d+)*[\.、]?", h_bare)
        if m and h_bare.startswith(m.group(0)):
            h_bare = h_bare[len(m.group(0)) :]
        for cand in (h, h_bare):
            if cand in self.ALIAS_NODES:
                return self.ALIAS_NODES[cand], "approx", "alias"
            if cand in self.title_by_norm:
                nid, q = self.title_by_norm[cand]
                return nid, q, "node_tree_title"
            if cand in self.map_by_norm:
                nid, q = self.map_by_norm[cand]
                return nid, q, "node_map_heading"
        # 包含匹配（≥4字且短串占长串≥50%，避免「研究药物」吞掉「研究药物临床研究概述」类误挂）；
        # 多个命中取最长标题（更具体）。再去标点包含匹配兜底。
        def strip_punct(s: str) -> str:
            return re.sub(r"[^\w\u4e00-\u9fff]", "", s)

        def contained_best(
            cand: str, table: dict[str, tuple[str, str]]
        ) -> tuple[str, str] | None:
            best: tuple[str, str] | None = None
            best_len = 0
            for norm_title, (nid, q) in table.items():
                if len(norm_title) < 4:
                    continue
                shorter = min(len(norm_title), len(cand))
                longer = max(len(norm_title), len(cand))
                if shorter / longer < 0.5:
                    continue
                if norm_title in cand or cand in norm_title:
                    if len(norm_title) > best_len:
                        best, best_len = (nid, q), len(norm_title)
            return best

        for cand in (h_bare, h):
            if len(cand) >= 4:
                hit = contained_best(cand, self.title_by_norm) or contained_best(
                    cand, self.map_by_norm
                )
                if hit:
                    return hit[0], "approx", "containment"
            c2 = strip_punct(cand)
            if len(c2) >= 4:
                t2_table = {strip_punct(k): v for k, v in self.title_by_norm.items()}
                hit = contained_best(c2, t2_table)
                if not hit:
                    t2_table = {strip_punct(k): v for k, v in self.map_by_norm.items()}
                    hit = contained_best(c2, t2_table)
                if hit:
                    return hit[0], "approx", "containment_nopunct"
        # 相似度
        for cand in (h_bare, h):
            if len(cand) >= 4:
                best, best_ratio = None, 0.0
                for norm_title, (nid, _q) in self.title_by_norm.items():
                    r = difflib.SequenceMatcher(None, cand, norm_title).ratio()
                    if r > best_ratio:
                        best, best_ratio = nid, r
                if best_ratio >= 0.6:
                    return best, "approx", "fuzzy"
        return None, "unmapped", "unmatched"


def attribute(sections: list[RawSection], index: NodeIndex) -> list[dict]:
    out: list[dict] = []
    for i, s in enumerate(sections, 1):
        if not s.number:
            key = norm_heading(s.heading)
            if key in FRONT_TITLE_NODES:
                nid0 = FRONT_TITLE_NODES[key]
                if nid0 is not None:
                    out.append(
                        {
                            "section_id": f"s{i:03d}",
                            "source_order": i,
                            "source_section_number": s.number,
                            "heading": s.heading,
                            "level": s.level,
                            "semantic_node_id": nid0,
                            "match_quality": "exact",
                            "match_basis": "front_title",
                            "char_count": len(s.text),
                            "text": s.text,
                        }
                    )
                    continue
                nid, q, basis = None, "unmapped", "unmatched"
            else:
                nid, q, basis = index.lookup(s.heading)
        else:
            nid, q, basis = index.lookup(s.heading)
        if nid is None:
            nid = slugify(s.heading or s.number or f"s{i}", i)
        out.append(
            {
                "section_id": f"s{i:03d}",
                "source_order": i,
                "source_section_number": s.number,
                "heading": s.heading,
                "level": s.level,
                "semantic_node_id": nid,
                "match_quality": q,
                "match_basis": basis,
                "char_count": len(s.text),
                "text": s.text,
            }
        )
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--kind", choices=["docx", "pdf"], required=True)
    ap.add_argument("--project-key", required=True)
    ap.add_argument("--out", required=True, type=Path)
    repo = Path(__file__).resolve().parents[2]
    ap.add_argument("--node-map", type=Path, default=repo / "eval" / "node_map.json")
    ap.add_argument(
        "--node-tree",
        type=Path,
        default=repo
        / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json",
    )
    args = ap.parse_args()

    if args.kind == "docx":
        sections, notes = split_docx(args.source)
    else:
        sections, notes = split_pdf(args.source)
    index = NodeIndex(args.node_tree, args.node_map)
    records = attribute(sections, index)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    mapped = [r for r in records if not r["semantic_node_id"].startswith("unmapped_")]
    print(f"[{args.project_key}] sections={len(records)} mapped={len(mapped)} "
          f"unmapped={len(records) - len(mapped)} notes={notes}")
    print("-- unmapped 清单 --")
    for r in records:
        if r["semantic_node_id"].startswith("unmapped_"):
            print(f"  {r['source_section_number']:>10} {r['heading'][:44]}")
    zero = [r["heading"] for r in records if r["char_count"] < 20]
    if zero:
        print(f"-- 近空节({len(zero)}) --: " + "; ".join(zero[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
