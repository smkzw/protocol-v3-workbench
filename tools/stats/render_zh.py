"""SampleSizeResult 的中文确定性渲染器（WP-M4-CALC）。

纯字符串组装，所有数字来自 sample_size.SampleSizeResult，不产生新数字、
不调用模型、无占位符。输出：
- render_zh_paragraph: 统计章正文段落
- render_zh_table_rows: SoA/统计章表格行（list[dict]，键 item/value）
"""
from __future__ import annotations

from typing import Optional

from sample_size import SampleSizeResult

_ENDPOINT_TYPE_ZH = {
    "continuous": "连续型（优效设计）",
    "binary": "二分类（优效设计）",
    "time_to_event": "时间-事件",
    "non_inferiority": "非劣效（固定边际法）",
}


def _num(x) -> str:
    """数字转短字符串：整数不带小数点，浮点用 %g。"""
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return str(int(x)) if x.is_integer() else f"{x:g}"
    return str(x)


def _pct(rate: float) -> str:
    return f"{rate * 100:g}%"


def _alloc_text(k: float) -> str:
    return f"{k:g}:1"


def _enrollment_sentence(r: SampleSizeResult) -> str:
    """入组人数句（含脱落膨胀），无占位符。"""
    if r.n_total is None:
        return "研究期内总体事件率未提供，入组人数待事件率明确后按“需事件数/事件率”换算。"
    base = (f"经计算需试验组{r.n_experimental}例、对照组{r.n_control}例，"
            f"共{r.n_total}例")
    dropout = float(r.parameters.get("dropout_rate", 0.0))
    if dropout <= 0 or r.n_total_adjusted is None:
        return f"{base}。"
    return (f"{base}；考虑{_pct(dropout)}脱落率后，"
            f"试验组需入组{r.n_experimental_adjusted}例、对照组需入组{r.n_control_adjusted}例，"
            f"合计{r.n_total_adjusted}例。")


def _alpha_power_text(r: SampleSizeResult) -> str:
    p = r.parameters
    side = "双侧" if p.get("two_sided", True) else "单侧"
    return f"设定{side}检验水准α={_num(p['alpha'])}、检验效能1-β={_num(p['power'])}"


def render_zh_paragraph(r: SampleSizeResult) -> str:
    """把 SampleSizeResult 渲染成中文正文段落（确定性组装）。"""
    t = r.endpoint_type
    if t == "continuous":
        p = r.parameters
        sd_text = (f"共同标准差为{_num(p['sd'])}" if p.get("sd") is not None
                   else f"试验组标准差{_num(p.get('sd_experimental'))}、"
                        f"对照组标准差{_num(p.get('sd_control'))}")
        alloc = (f"，按试验组:对照组={_alloc_text(p['allocation_ratio'])}分配"
                 if p["allocation_ratio"] != 1 else "")
        return (f"本研究以连续型指标为主要终点，采用两样本t检验（正态近似）。"
                f"{_alpha_power_text(r)}，假设组间均值差为{_num(p['mean_diff'])}、{sd_text}{alloc}，"
                + _enrollment_sentence(r))
    if t == "binary":
        p = r.parameters
        alloc = (f"，按试验组:对照组={_alloc_text(p['allocation_ratio'])}分配"
                 if p["allocation_ratio"] != 1 else "")
        return (f"本研究以二分类指标（率）为主要终点，采用两独立比例比较（合并p̄的z检验）。"
                f"{_alpha_power_text(r)}，假设试验组率为{_num(p['p_experimental'])}、"
                f"对照组率为{_num(p['p_control'])}{alloc}，"
                + _enrollment_sentence(r))
    if t == "time_to_event":
        p = r.parameters
        inter = r.intermediate
        hr_text = _num(inter.get("hazard_ratio", p.get("hazard_ratio")))
        alloc = f"按试验组:对照组={_alloc_text(p['allocation_ratio'])}分配、" \
            if p["allocation_ratio"] != 1 else ""
        head = (f"本研究以时间-事件指标为主要终点，采用Log-rank检验"
                f"（Schoenfeld事件数法），假设两组风险比HR={hr_text}恒定（比例风险）。"
                f"{_alpha_power_text(r)}，需观察到{r.events_required}例事件；")
        if r.n_total is not None:
            rate = _num(inter.get("event_rate", p.get("event_rate")))
            return head + f"{alloc}按研究期内总体事件率{rate}换算，" + _enrollment_sentence(r)
        return head + _enrollment_sentence(r)
    if t == "non_inferiority":
        p = r.parameters
        margin = _num(p["non_inferiority_margin"])
        if p.get("p0") is not None:
            detail = (f"非劣效边际为{margin}（率差口径），"
                      f"假定两组共同率p₀={_num(p['p0'])}")
        else:
            sd = p.get("sd")
            detail = f"非劣效边际为{margin}（均值差口径）"
            if sd is not None:
                detail += f"，共同标准差为{_num(sd)}"
        alloc = (f"，按试验组:对照组={_alloc_text(p['allocation_ratio'])}分配"
                 if p["allocation_ratio"] != 1 else "")
        return (f"本研究为非劣效设计，采用固定边际法（单侧检验）。"
                f"{_alpha_power_text(r)}，{detail}{alloc}，"
                + _enrollment_sentence(r))
    raise ValueError(f"未知 endpoint_type：{t}")


def render_zh_table_rows(r: SampleSizeResult) -> list:
    """渲染成表格行（SoA/统计章用），list[dict]，键为 item/value。"""
    p = r.parameters
    rows: list = []
    rows.append({"item": "主要终点类型", "value": _ENDPOINT_TYPE_ZH[r.endpoint_type]})
    rows.append({"item": "检验方法", "value": r.formula_label_zh})
    side = "双侧" if p.get("two_sided", True) else "单侧"
    rows.append({"item": "检验水准", "value": f"{_num(p['alpha'])}（{side}）"})
    rows.append({"item": "检验效能（1-β）", "value": _num(p["power"])})

    if r.endpoint_type == "continuous":
        rows.append({"item": "组间均值差", "value": _num(p["mean_diff"])})
        if p.get("sd") is not None:
            rows.append({"item": "标准差", "value": _num(p["sd"])})
        else:
            rows.append({"item": "标准差（试验组/对照组）",
                         "value": f"{_num(p.get('sd_experimental'))}/{_num(p.get('sd_control'))}"})
    elif r.endpoint_type == "binary":
        rows.append({"item": "预期率（试验组/对照组）",
                     "value": f"{_num(p['p_experimental'])}/{_num(p['p_control'])}"})
    elif r.endpoint_type == "time_to_event":
        rows.append({"item": "风险比（HR）",
                     "value": _num(r.intermediate.get("hazard_ratio", p.get("hazard_ratio")))})
        rows.append({"item": "需事件数", "value": f"{r.events_required}例"})
        if p.get("event_rate") is not None:
            rows.append({"item": "研究期内总体事件率", "value": _num(p["event_rate"])})
    else:  # non_inferiority
        rows.append({"item": "非劣效边际", "value": _num(p["non_inferiority_margin"])})
        if p.get("p0") is not None:
            rows.append({"item": "假定共同率（p₀）", "value": _num(p["p0"])})
        elif p.get("sd") is not None:
            rows.append({"item": "标准差", "value": _num(p["sd"])})

    k = p["allocation_ratio"]
    rows.append({"item": "分配比（试验组:对照组）", "value": _alloc_text(k)})
    if r.n_total is not None:
        rows.append({"item": "样本量（未考虑脱落）",
                     "value": (f"试验组{r.n_experimental}例；对照组{r.n_control}例；"
                               f"合计{r.n_total}例")})
    dropout = float(p.get("dropout_rate", 0.0))
    if dropout > 0 and r.n_total_adjusted is not None:
        rows.append({"item": "脱落率", "value": _pct(dropout)})
        rows.append({"item": "样本量（考虑脱落后）",
                     "value": (f"试验组{r.n_experimental_adjusted}例；"
                               f"对照组{r.n_control_adjusted}例；"
                               f"合计{r.n_total_adjusted}例")})
    if r.assumptions:
        rows.append({"item": "统计假设", "value": "；".join(r.assumptions)})
    return rows
