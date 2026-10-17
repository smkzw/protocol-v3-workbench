"""F3/NEW-39 样本量『解析与闸门策略批』（第2轮末修订策略，20261017）。

现场（r2-C 医学总监实算 + 主会话逐 regex 定位）：9.1 声明每组45例、
安慰剂组缓解率15% vs 最优剂量组38%、双侧α=0.05（Bonferroni面α=0.0167）、
『80%功效』——
①把握度正则只认『把握度』，『80%功效』parse 失败（第①洞）；
②比例假设解析器不认分立表述『安慰剂组…15%』+『最优剂量组…38%』
（第②洞）；
③α first-match 取 0.05，忽略操作性更强的 Bonferroni 校正 α=0.0167
（第③洞，45 vs 54 假自洽）；
④守卫幂等使假设补齐后旧悬置标记永不刷新——『系统无法复算』过期 gate
文本与正文自相矛盾上纸（第④洞）；
⑤独立复算：α=0.0167 下 45 例/组实算把握度≈53.3%（不校正 70.2%）、80%
需约72例/组——宣称把握度与声明 n 不闭合，±20% 例数门放行的场景需按
『不一致』路径合闸（第⑤洞）。

契约（反例先红）：五洞全数闭合。
"""
from __future__ import annotations

from services.api.app.medical_writing_full_draft import (
    _parse_sample_size_assumptions,
    apply_sample_size_guard_to_section,
    sample_size_declaration_check,
)

# r2-C 现场原文要素句（UC 项目 9.1 形态）。
NEW39_TEXT = (
    "样本量：主要终点为内镜应答率。安慰剂组缓解率15%，"
    "最优剂量组缓解率38%，双侧α=0.05（多重性校正α=0.0167），"
    "80%功效，每组45例（共135例）。"
)


def test_new39_power_synonym_parses():
    """第①洞：『功效/检验效能』同义词必须解析。"""
    assumptions = _parse_sample_size_assumptions("双侧α=0.05，80%功效。")
    assert assumptions["power"] == 0.8
    assumptions2 = _parse_sample_size_assumptions("检验效能90%。")
    assert assumptions2["power"] == 0.9


def test_new39_disjunct_proportion_pair_parses():
    """第②洞：分立比例表述（安慰剂组15% / 最优剂量组38%）必须解析。"""
    assumptions = _parse_sample_size_assumptions(NEW39_TEXT)
    assert assumptions["p1"] is not None and assumptions["p2"] is not None
    assert {round(assumptions["p1"], 4), round(assumptions["p2"], 4)} == {
        round(0.15, 4),
        round(0.38, 4),
    }


def test_new39_bonferroni_min_alpha_selected():
    """第③洞：同文多α且出现多重性/校正 → 取最小α（0.0167）。"""
    result = sample_size_declaration_check(NEW39_TEXT)
    assert result is not None
    assert result["status"] == "不一致"
    detail = str(result.get("detail"))
    assert "0.0167" in detail, "α 选择策略必须注记取最小校正α"
    # 比例公式（α=0.0167、80%把握度、15% vs 38%）复算 ≈ 72 例/组。
    assert result["required_per_group"] in range(68, 76)


def test_new39_power_closure_gate_fires_without_bonferroni():
    """第⑤洞：无校正α（0.05）时 ±20% 例数门会放行（45/54=0.83），但按
    声明45例实算把握度≈70.2% 与宣称80% 偏差>5个百分点 → 必须判不一致。"""
    text = NEW39_TEXT.replace("（多重性校正α=0.0167）", "")
    result = sample_size_declaration_check(text)
    assert result is not None
    assert result["status"] == "不一致", "宣称80%与实算70.2%必须判不一致"
    detail = str(result.get("detail"))
    assert "偏差超过5个百分点" in detail and "实算把握度" in detail, (
        "不一致明细必须给出按声明n实算的把握度"
    )


def test_new39_guard_marker_refreshes_when_assumptions_complete():
    """第④洞：悬置标记的节在假设补齐后重过守卫 → 摘除过期标记并判自洽。"""
    incomplete = "样本量：每组45例，安慰剂组缓解率15%，最优剂量组缓解率38%。"
    section = {
        "section_number": "9.1",
        "heading": "9.1 样本量",
        "proposal_text": incomplete,
    }
    apply_sample_size_guard_to_section(section, anchor="")
    marked = str(section.get("proposal_text"))
    assert "【样本量待确认" in marked, "要素未齐必须先挂悬置标记（前置态）"

    # 作者补齐假设并把声明例数修正为复算值（54例/组）后重过守卫：
    # 过期标记必须摘除并判自洽；溯源标注保持一份（幂等不重复）。
    body_fixed = marked.replace(
        "每组45例，安慰剂组缓解率15%，最优剂量组缓解率38%。",
        "安慰剂组缓解率15%，最优剂量组缓解率38%，双侧α=0.05，"
        "80%功效，每组54例（共108例）。",
    )
    section2 = {
        "section_number": "9.1",
        "heading": "9.1 样本量",
        "proposal_text": body_fixed,
    }
    apply_sample_size_guard_to_section(section2, anchor="")
    text2 = str(section2.get("proposal_text"))
    assert "【样本量待确认" not in text2, "过期悬置标记必须摘除（NEW-44面）"
    check = section2.get("sample_size_check") or {}
    assert check.get("status") == "自洽"
    assert text2.count("样本量假设未具名溯源") == 1, "溯源标注幂等：刷新不得追加第二份"
