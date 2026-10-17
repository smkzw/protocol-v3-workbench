#!/usr/bin/env python3
"""WP-M1-FIXTURE fixture 契约自测（先于数据文件编写，TDD）。

校验 eval/fixtures/<key>/ 三件套与 eval/fixtures/manifest.json：
1. reference_sections.jsonl：合法 JSONL，必备字段齐全，char_count==len(text)，
   section_id 唯一且与 source_order 一致，semantic_node_id 要么存在于
   TP-MA-07 v2 节点树、要么是 unmapped_ 前缀占位。
2. opening_input.json：与 eval/SCHEMAS.md §1 ProjectProfile 完全同构
   （字段集不多不少，枚举合法：molecule_type/route/phase）。
3. key_facts.json：覆盖 04_EVAL.md 要求的八类关键设计事实
   （endpoints/estimand/sample_size/doses/control/randomization_blinding/
    key_eligibility/soa_skeleton），每条事实的 evidence.section_id 必须能在
   本 fixture 的 reference_sections.jsonl 中找到（证据可回溯）；
   sample_size.planned_n（如给出）为正整数。
4. manifest.json：收录全部 fixture 目录；每个条目含 source 路径与 sha256；
   源文件存在时校验 sha256 一致（防源文档被换版本）。
5. 泛化红线：本目录 *.py 不得出现具体药物/疾病/项目号词面（数据文件豁免）。

用法：python3 tools/fixture/fixture_selftest.py   # 全绿退出码 0
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "eval" / "fixtures"
NODE_TREE = (
    REPO_ROOT
    / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json"
)

# 泛化红线词面（拼片构造，避免本文件自身命中）。
GENERALIZATION_BLOCKLIST = [
    "".join(x)
    for x in [
        ["MY", "009"],
        ["MY", "004567"],
        ["溃疡性", "结肠炎"],
        ["类风湿", "关节炎"],
        ["特应性", "皮炎"],
        ["芦可", "替尼"],
        ["VN", "N1"],
        ["IRAK", "4"],
        ["MY", "004-RA"],
    ]
]

PROFILE_FIELDS = {
    "drug_name": str,
    "target": (str, type(None)),
    "molecule_type": str,
    "route": str,
    "indication": str,
    "phase": str,
    "optional_materials": dict,
}
MOLECULE_TYPES = {"antibody", "small_molecule", "peptide", "aso", "sirna", "other"}
ROUTES = {"oral", "iv", "sc", "im", "topical", "inhalation", "other"}
PHASES = {"II", "III"}
OPTIONAL_MATERIAL_KEYS = {"ib", "synopsis"}

SECTION_FIELDS = {
    "section_id",
    "source_order",
    "source_section_number",
    "heading",
    "level",
    "semantic_node_id",
    "match_quality",
    "match_basis",
    "char_count",
    "text",
}

# 04_EVAL.md「关键设计事实」八类
KEY_FACT_CATEGORIES = [
    "endpoints",
    "estimand",
    "sample_size",
    "doses",
    "control",
    "randomization_blinding",
    "key_eligibility",
    "soa_skeleton",
]


class Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.failures: list[str] = []

    def check(self, cond: bool, msg: str) -> None:
        if not cond:
            self.failures.append(msg)


def load_sections(key: str) -> list[dict]:
    path = FIXTURES_DIR / key / "reference_sections.jsonl"
    records = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def iter_evidence(node, path=""):
    """递归收集 key_facts 里所有 evidence.section_id。"""
    if isinstance(node, dict):
        if "evidence" in node and isinstance(node["evidence"], dict):
            sid = node["evidence"].get("section_id")
            if sid:
                yield sid
        for k, v in node.items():
            yield from iter_evidence(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_evidence(v, f"{path}[{i}]")


def test_reference_sections(r: Result, key: str) -> list[dict]:
    path = FIXTURES_DIR / key / "reference_sections.jsonl"
    r.check(path.exists(), f"[{key}] 缺 reference_sections.jsonl")
    if not path.exists():
        return []
    records = load_sections(key)
    r.check(len(records) >= 50, f"[{key}] 参照正文节节数过少: {len(records)}")
    tree_ids = {
        n["id"]
        for n in json.loads(NODE_TREE.read_text(encoding="utf-8"))["outlined_tree"][
            "nodes"
        ]
    }
    seen_ids = set()
    for rec in records:
        sid = rec.get("section_id")
        missing = SECTION_FIELDS - set(rec)
        r.check(not missing, f"[{key}] {sid} 缺字段 {sorted(missing)}")
        if sid in seen_ids:
            r.check(False, f"[{key}] section_id 重复: {sid}")
        seen_ids.add(sid)
        r.check(
            rec.get("char_count") == len(rec.get("text", "")),
            f"[{key}] {sid} char_count 与 text 长度不符",
        )
        nid = rec.get("semantic_node_id", "")
        r.check(
            nid in tree_ids or nid.startswith("unmapped_"),
            f"[{key}] {sid} semantic_node_id 非法: {nid}",
        )
    orders = [rec.get("source_order") for rec in records]
    r.check(
        orders == sorted(orders),
        f"[{key}] source_order 非单调递增",
    )
    mapped = sum(1 for rec in records if not str(rec["semantic_node_id"]).startswith("unmapped_"))
    r.check(mapped >= 20, f"[{key}] 映射到语义节点的节数过少: {mapped}")
    return records


def test_opening_input(r: Result, key: str) -> None:
    path = FIXTURES_DIR / key / "opening_input.json"
    r.check(path.exists(), f"[{key}] 缺 opening_input.json（开局输入）")
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    r.check(
        set(data) == set(PROFILE_FIELDS),
        f"[{key}] opening_input 字段集与 ProjectProfile 不符: {sorted(set(data) ^ set(PROFILE_FIELDS))}",
    )
    for field, typ in PROFILE_FIELDS.items():
        if field in data:
            r.check(
                isinstance(data[field], typ),
                f"[{key}] opening_input.{field} 类型应为 {typ}",
            )
    r.check(data.get("drug_name"), f"[{key}] drug_name 不能为空")
    r.check(bool(data.get("indication")), f"[{key}] indication 不能为空")
    r.check(data.get("molecule_type") in MOLECULE_TYPES, f"[{key}] molecule_type 枚举非法")
    r.check(data.get("route") in ROUTES, f"[{key}] route 枚举非法")
    r.check(data.get("phase") in PHASES, f"[{key}] phase 枚举非法")
    om = data.get("optional_materials", {})
    r.check(
        set(om) == OPTIONAL_MATERIAL_KEYS,
        f"[{key}] optional_materials 应含 {OPTIONAL_MATERIAL_KEYS}",
    )


def test_key_facts(r: Result, key: str, records: list[dict]) -> None:
    path = FIXTURES_DIR / key / "key_facts.json"
    r.check(path.exists(), f"[{key}] 缺 key_facts.json（关键设计事实）")
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    facts = data.get("facts", data)
    for cat in KEY_FACT_CATEGORIES:
        r.check(cat in facts, f"[{key}] key_facts 缺类别 {cat}")
    r.check(
        isinstance(facts.get("key_eligibility", {}).get("inclusion"), list)
        and facts["key_eligibility"]["inclusion"],
        f"[{key}] key_eligibility.inclusion 应为非空列表",
    )
    r.check(
        isinstance(facts.get("key_eligibility", {}).get("exclusion"), list)
        and facts["key_eligibility"]["exclusion"],
        f"[{key}] key_eligibility.exclusion 应为非空列表",
    )
    ss = facts.get("sample_size", {})
    if "planned_n" in ss and ss["planned_n"] is not None:
        r.check(
            isinstance(ss["planned_n"], int) and ss["planned_n"] > 0,
            f"[{key}] sample_size.planned_n 应为正整数",
        )
    # 证据指针可回溯
    known = {rec["section_id"] for rec in records} if records else set()
    for sid in iter_evidence(facts):
        r.check(sid in known, f"[{key}] evidence.section_id 无效: {sid}")
    # 冲突声明结构
    for c in data.get("internal_conflicts", []):
        r.check(
            isinstance(c.get("note"), str) and c.get("note"),
            f"[{key}] internal_conflicts 条目缺 note",
        )


def test_manifest(r: Result, fixture_keys: list[str]) -> None:
    path = FIXTURES_DIR / "manifest.json"
    r.check(path.exists(), "缺 eval/fixtures/manifest.json")
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("fixtures", [])
    listed = [e.get("project_key") for e in entries]
    r.check(
        sorted(listed) == sorted(fixture_keys),
        f"manifest 收录 {listed} 与磁盘目录 {fixture_keys} 不一致",
    )
    for e in entries:
        key = e.get("project_key")
        for field in ("source", "sha256", "kind"):
            r.check(bool(e.get(field)), f"manifest[{key}] 缺 {field}")
        r.check(e.get("set") in {"dev", "heldout"}, f"manifest[{key}] set 非法")
        src = Path(str(e.get("source")))
        if src.exists():
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            r.check(
                digest == e.get("sha256"),
                f"manifest[{key}] 源文件 sha256 与记录不符（源文档可能被更换）",
            )
        else:
            r.failures.append(f"manifest[{key}] 源文件不存在: {src}")


def test_generalization(r: Result) -> None:
    for py in sorted(Path(__file__).resolve().parent.glob("*.py")):
        body = py.read_text(encoding="utf-8")
        for term in GENERALIZATION_BLOCKLIST:
            r.check(term not in body, f"{py.name} 不得出现具体项目词 {term!r}")


def main() -> int:
    fixture_keys = sorted(
        d.name for d in FIXTURES_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    res = Result("fixtures")
    res.check(len(fixture_keys) >= 3, f"fixture 目录数不足: {fixture_keys}")
    for key in fixture_keys:
        records = test_reference_sections(res, key)
        test_opening_input(res, key)
        test_key_facts(res, key, records)
    test_manifest(res, fixture_keys)
    test_generalization(res)

    for f in res.failures:
        print(f"FAIL {f}")
    print(f"\n{len(res.failures)} failure(s) over {len(fixture_keys)} fixture(s)")
    return 1 if res.failures else 0


if __name__ == "__main__":
    sys.exit(main())
