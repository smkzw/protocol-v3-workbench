"""样本量计算器纯函数库（WP-M4-CALC）。

支持四种设计，均支持脱落率补膨胀与不等分配比（allocation_ratio = 试验组:对照组 = r:1）：
- continuous      连续型主终点：两样本 t 检验，正态近似
- binary          二分类主终点：两独立比例比较，合并 p̄ 的 z 检验
- time_to_event   时间-事件主终点：log-rank，Schoenfeld 事件数法
- non_inferiority 非劣效（固定边际法，单侧），分连续/二分类两种口径

设计原则（02_ARCHITECTURE）：数字由确定性代码产出，本库不依赖 scipy，
正态分位数用手写有理近似（Acklam），标准值误差 < 1e-9。
不涉及任何药物/疾病/项目专名。

用法：
    from sample_size import calculate
    result = calculate({"endpoint_type": "continuous", "mean_diff": 1, "sd": 1})
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


class SampleSizeInputError(ValueError):
    """输入非法：携带面向用户的中文错误信息。"""


# ---------------------------------------------------------------------------
# 正态分位数（无需 scipy）
# ---------------------------------------------------------------------------

def _z_quantile(p: float) -> float:
    """标准正态分布的分位数函数（Acklam 有理近似，|误差| < 1.15e-9）。

    # ponytail: 单一近似覆盖任意 0<p<1；如需更高精度再换 Wichura AS241。
    """
    if not 0.0 < p < 1.0:
        raise SampleSizeInputError(f"正态分位数自变量 p 必须在 (0,1) 内，收到 {p}")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:  # 左尾
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= p_high:  # 中央
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))  # 右尾（对称）
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------

@dataclass
class SampleSizeResult:
    endpoint_type: str                    # continuous | binary | time_to_event | non_inferiority
    formula_name: str                     # 机器可读公式名
    formula_label_zh: str                 # 中文公式名
    n_experimental: Optional[int]         # 试验组（未膨胀）N
    n_control: Optional[int]              # 对照组（未膨胀）N
    n_total: Optional[int]
    n_experimental_adjusted: Optional[int]  # 考虑脱落率后
    n_control_adjusted: Optional[int]
    n_total_adjusted: Optional[int]
    events_required: Optional[int]        # 仅 time_to_event
    parameters: dict = field(default_factory=dict)     # 输入参数回显（规范化后）
    assumptions: list = field(default_factory=list)    # 假设明细（中文）
    intermediate: dict = field(default_factory=dict)   # 未取整中间值，供复核

    def to_dict(self) -> dict:
        return {
            "endpoint_type": self.endpoint_type,
            "formula_name": self.formula_name,
            "formula_label_zh": self.formula_label_zh,
            "n_experimental": self.n_experimental,
            "n_control": self.n_control,
            "n_total": self.n_total,
            "n_experimental_adjusted": self.n_experimental_adjusted,
            "n_control_adjusted": self.n_control_adjusted,
            "n_total_adjusted": self.n_total_adjusted,
            "events_required": self.events_required,
            "parameters": self.parameters,
            "assumptions": list(self.assumptions),
            "intermediate": self.intermediate,
        }


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------

_ENDPOINT_ALIASES = {
    "continuous": "continuous", "连续": "continuous", "连续型": "continuous",
    "binary": "binary", "二分类": "binary", "比例": "binary",
    "time_to_event": "time_to_event", "time-to-event": "time_to_event",
    "tte": "time_to_event", "时间-事件": "time_to_event", "时间事件": "time_to_event",
    "生存": "time_to_event",
    "non_inferiority": "non_inferiority", "non-inferiority": "non_inferiority",
    "ni": "non_inferiority", "非劣效": "non_inferiority",
}


def _require_number(inputs: dict, key: str, msg: str) -> float:
    if key not in inputs or inputs[key] is None:
        raise SampleSizeInputError(f"缺少必填参数 {key}：{msg}")
    v = inputs[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SampleSizeInputError(f"参数 {key} 必须为数值，收到 {v!r}")
    return float(v)


def _check_range(name: str, v: float, low: float, high: float,
                 include_high: bool = False, include_low: bool = False) -> float:
    ok_low = low <= v if include_low else low < v
    ok_high = v <= high if include_high else v < high
    if not (ok_low and ok_high):
        left = "≤" if include_low else "<"
        right = "≤" if include_high else "<"
        raise SampleSizeInputError(f"参数 {name} 必须满足 {low} {left} {name} {right} {high}，收到 {v}")
    return v


def _number_or_default(inputs: dict, key: str, default: float) -> float:
    v = inputs.get(key, default)
    if v is None:
        v = default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SampleSizeInputError(f"参数 {key} 必须为数值，收到 {v!r}")
    return float(v)


def _common_inputs(inputs: dict) -> dict:
    alpha = _check_range("alpha", _number_or_default(inputs, "alpha", 0.05), 0.0, 1.0)
    power = _check_range("power", _number_or_default(inputs, "power", 0.8), 0.0, 1.0)
    two_sided = inputs.get("two_sided", True)
    if not isinstance(two_sided, bool):
        raise SampleSizeInputError(f"参数 two_sided 必须为布尔值，收到 {two_sided!r}")
    alloc = _check_range("allocation_ratio",
                         _number_or_default(inputs, "allocation_ratio", 1.0), 0.0, float("inf"))
    dropout = _check_range("dropout_rate",
                           _number_or_default(inputs, "dropout_rate", 0.0),
                           0.0, 1.0, include_low=True)
    return {"alpha": alpha, "power": power, "two_sided": two_sided,
            "allocation_ratio": alloc, "dropout_rate": dropout}


def _std_devs(inputs: dict) -> tuple[float, float]:
    """返回 (试验组方差, 对照组方差)。支持共同 sd 或分别 sd_experimental/sd_control。"""
    has_common = inputs.get("sd") is not None
    has_sep = inputs.get("sd_experimental") is not None or inputs.get("sd_control") is not None
    if has_sep:
        sd_e = _check_range("sd_experimental", _require_number(inputs, "sd_experimental", "试验组标准差 >0"),
                            0.0, float("inf"))
        sd_c = _check_range("sd_control", _require_number(inputs, "sd_control", "对照组标准差 >0"),
                            0.0, float("inf"))
        return sd_e * sd_e, sd_c * sd_c
    if has_common:
        sd = _check_range("sd", _require_number(inputs, "sd", "共同标准差 >0"), 0.0, float("inf"))
        return sd * sd, sd * sd
    raise SampleSizeInputError("缺少必填参数 sd（或 sd_experimental/sd_control）：标准差必须 >0")


def _split_arms(n_total_raw: float, k: float) -> tuple[int, int]:
    """按分配比 k:1 把总样本量拆到两组（各自向上取整）。返回 (试验组, 对照组)。"""
    n_ctl = math.ceil(n_total_raw / (k + 1.0))
    n_exp = math.ceil(k * n_total_raw / (k + 1.0))
    return n_exp, n_ctl


def _inflate(n: Optional[int], dropout: float) -> Optional[int]:
    if n is None:
        return None
    return math.ceil(n / (1.0 - dropout))


# ---------------------------------------------------------------------------
# 四种设计的计算
# ---------------------------------------------------------------------------

def _calc_continuous(p: dict, label: str, delta: float, var_t: float, var_c: float,
                     margin_is_ni: bool = False, delta_label: Optional[str] = None,
                     method_note: Optional[str] = None) -> SampleSizeResult:
    """两均值（或率差）比较（优效 t 检验 / 非劣效固定边际）统一正态近似。

    注：首版采用正态近似，未做小样本 t 分布迭代校正；每组样本量 <30 时建议
    用精确 t 检验迭代复核（后续版本可加）。
    """
    za = _z_quantile(1 - p["alpha"] / 2) if p["two_sided"] else _z_quantile(1 - p["alpha"])
    zb = _z_quantile(p["power"])
    k = p["allocation_ratio"]
    denom = delta * delta
    n_ctl_raw = (za + zb) ** 2 * (var_t / k + var_c) / denom
    n_exp_raw = k * n_ctl_raw
    n_exp, n_ctl = math.ceil(n_exp_raw), math.ceil(n_ctl_raw)
    dropout = p["dropout_rate"]
    assumptions = [
        f"{'双侧' if p['two_sided'] else '单侧'}检验水准 α={p['alpha']:g}"
        f"（z={za:.4f}），检验效能 1-β={p['power']:g}（z={zb:.4f}）",
        method_note or ("采用两样本 t 检验正态近似公式，未做小样本 t 分布迭代校正；"
                        "每组样本量 <30 时建议复核"),
        f"组间{delta_label or ('均值差' if not margin_is_ni else '非劣效固定边际')} |δ|={delta:g}，"
        f"合并方差口径 σ²(1/n₁+1/n₂)",
    ]
    if k != 1:
        assumptions.append(f"分配比 试验组:对照组={k:g}:1，取整后实际比例略有偏差")
    if dropout > 0:
        assumptions.append(f"脱落率 {dropout:.0%}：按 n/(1-脱落率) 逐组向上取整膨胀")
    return SampleSizeResult(
        endpoint_type="non_inferiority" if margin_is_ni else "continuous",
        formula_name="non_inferiority_fixed_margin" if margin_is_ni else "two_sample_t_normal_approx",
        formula_label_zh=label,
        n_experimental=n_exp, n_control=n_ctl, n_total=n_exp + n_ctl,
        n_experimental_adjusted=_inflate(n_exp, dropout),
        n_control_adjusted=_inflate(n_ctl, dropout),
        n_total_adjusted=(_inflate(n_exp, dropout) or 0) + (_inflate(n_ctl, dropout) or 0),
        events_required=None,
        parameters=p,
        assumptions=assumptions,
        intermediate={"z_alpha": za, "z_beta": zb, "n_control_raw": n_ctl_raw,
                      "n_experimental_raw": n_exp_raw},
    )


def _calc_binary(p: dict, p1: float, p2: float) -> SampleSizeResult:
    """两独立比例比较（合并 p̄，z 检验），含 Fleiss 不等分配推广。"""
    za = _z_quantile(1 - p["alpha"] / 2) if p["two_sided"] else _z_quantile(1 - p["alpha"])
    zb = _z_quantile(p["power"])
    k = p["allocation_ratio"]
    pbar = (k * p1 + p2) / (k + 1.0)
    term = (za * math.sqrt((1 + 1 / k) * pbar * (1 - pbar))
            + zb * math.sqrt(p1 * (1 - p1) / k + p2 * (1 - p2))) / abs(p1 - p2)
    n_ctl_raw = term * term
    n_exp_raw = k * n_ctl_raw
    n_exp, n_ctl = math.ceil(n_exp_raw), math.ceil(n_ctl_raw)
    dropout = p["dropout_rate"]
    assumptions = [
        f"双侧检验水准 α={p['alpha']:g}（z={za:.4f}），检验效能 1-β={p['power']:g}（z={zb:.4f}）",
        f"两独立比例比较，采用合并比例 p̄={pbar:g} 的 z 检验公式（率差口径）",
        f"假设试验组率 p₁={p1:g}、对照组率 p₂={p2:g}",
    ]
    if k != 1:
        assumptions.append(f"分配比 试验组:对照组={k:g}:1（Fleiss 不等分配公式），取整后实际比例略有偏差")
    if dropout > 0:
        assumptions.append(f"脱落率 {dropout:.0%}：按 n/(1-脱落率) 逐组向上取整膨胀")
    return SampleSizeResult(
        endpoint_type="binary",
        formula_name="two_proportion_pooled_z",
        formula_label_zh="两独立比例比较（合并 p̄ 的 z 检验）",
        n_experimental=n_exp, n_control=n_ctl, n_total=n_exp + n_ctl,
        n_experimental_adjusted=_inflate(n_exp, dropout),
        n_control_adjusted=_inflate(n_ctl, dropout),
        n_total_adjusted=(_inflate(n_exp, dropout) or 0) + (_inflate(n_ctl, dropout) or 0),
        events_required=None,
        parameters=p,
        assumptions=assumptions,
        intermediate={"z_alpha": za, "z_beta": zb, "pbar": pbar,
                      "n_control_raw": n_ctl_raw, "n_experimental_raw": n_exp_raw},
    )


def _calc_time_to_event(p: dict, hr: float, event_rate: Optional[float]) -> SampleSizeResult:
    """log-rank 检验，Schoenfeld 事件数法：
    d = (z_{1-α/2} + z_{1-β})² / (p_exp·(1-p_exp)·ln(HR)²)，p_exp 为试验组分配比例。
    """
    za = _z_quantile(1 - p["alpha"] / 2) if p["two_sided"] else _z_quantile(1 - p["alpha"])
    zb = _z_quantile(p["power"])
    k = p["allocation_ratio"]
    p_exp = k / (k + 1.0)
    d_raw = (za + zb) ** 2 / (p_exp * (1 - p_exp) * math.log(hr) ** 2)
    events = math.ceil(d_raw)
    dropout = p["dropout_rate"]
    assumptions = [
        f"双侧检验水准 α={p['alpha']:g}（z={za:.4f}），检验效能 1-β={p['power']:g}（z={zb:.4f}）",
        f"Log-rank 检验 Schoenfeld 事件数法：d=(z₁₋α/₂+z₁₋β)²/(p(1-p)·ln(HR)²)，"
        f"假设比例风险（HR={hr:g} 恒定）",
    ]
    if k != 1:
        assumptions.append(f"分配比 试验组:对照组={k:g}:1，事件数按 p_exp={p_exp:g} 校正")
    n_exp = n_ctl = None
    n_exp_adj = n_ctl_adj = None
    if event_rate is not None:
        n_total_raw = d_raw / event_rate
        n_exp, n_ctl = _split_arms(n_total_raw, k)
        n_exp_adj, n_ctl_adj = _inflate(n_exp, dropout), _inflate(n_ctl, dropout)
        assumptions.append(
            f"研究期内总体事件率 {event_rate:g}：入组样本量=需事件数/事件率"
            f"（未取整 {n_total_raw:.1f} 例）")
    if dropout > 0:
        assumptions.append(f"脱落率 {dropout:.0%}：仅对入组人数按 n/(1-脱落率) 膨胀，需事件数不受影响")
    return SampleSizeResult(
        endpoint_type="time_to_event",
        formula_name="schoenfeld_logrank_events",
        formula_label_zh="Log-rank 检验 Schoenfeld 事件数法",
        n_experimental=n_exp, n_control=n_ctl,
        n_total=(n_exp + n_ctl) if n_exp is not None else None,
        n_experimental_adjusted=n_exp_adj, n_control_adjusted=n_ctl_adj,
        n_total_adjusted=(n_exp_adj + n_ctl_adj) if n_exp_adj is not None else None,
        events_required=events,
        parameters=p,
        assumptions=assumptions,
        intermediate={"z_alpha": za, "z_beta": zb, "p_experimental": p_exp,
                      "events_raw": d_raw, "hazard_ratio": hr},
    )


def _calc_non_inferiority(p: dict, margin: float) -> SampleSizeResult:
    """固定边际法非劣效（单侧）。连续：σ²(1/k+1)/Δ²；二分类：p₀(1-p₀)(1+1/k)/Δ²。"""
    if p["two_sided"]:
        raise SampleSizeInputError("非劣效检验应采用单侧检验：请传 two_sided=False（缺省按单侧处理）")
    ni_type = p.get("ni_data_type")
    has_sd = p.get("sd") is not None or p.get("sd_experimental") is not None
    has_p0 = p.get("p0") is not None
    if ni_type is None:
        if has_sd:
            ni_type = "continuous"
        elif has_p0:
            ni_type = "binary"
        else:
            raise SampleSizeInputError("非劣效计算缺少效应参数：连续型传 sd，二分类传 p0")
    if ni_type == "continuous":
        var_t, var_c = _std_devs(p)
        return _calc_continuous(p, "非劣效固定边际法（连续型，单侧）", margin, var_t, var_c,
                                margin_is_ni=True)
    if ni_type == "binary":
        p0 = _check_range("p0", _require_number(p, "p0", "两组假定的共同率（0<p0<1）"), 0.0, 1.0)
        var_t = var_c = p0 * (1 - p0)
        result = _calc_continuous(
            p, "非劣效固定边际法（二分类，单侧）", margin, var_t, var_c,
            margin_is_ni=True, delta_label="非劣效固定边际（率差）",
            method_note=("采用率差口径 z 检验正态近似公式（固定边际法），"
                         "未做小样本迭代校正"),
        )
        result.assumptions.insert(3, f"两组假定共同率 p₀={p0:g}，方差取 p₀(1-p₀)")
        result.intermediate["p0"] = p0
        return result
    raise SampleSizeInputError(f"ni_data_type 仅支持 continuous/binary，收到 {ni_type!r}")


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def calculate(inputs: dict) -> SampleSizeResult:
    """统一入口：calculate(inputs: dict) -> SampleSizeResult。

    公共参数：endpoint_type（必填）、alpha=0.05、power=0.8、two_sided=True、
    allocation_ratio=1（试验组:对照组=r:1）、dropout_rate=0。
    各设计参数见模块 docstring；非法输入抛 SampleSizeInputError（中文信息）。
    """
    if not isinstance(inputs, dict):
        raise SampleSizeInputError(f"inputs 必须为 dict，收到 {type(inputs).__name__}")
    raw_type = inputs.get("endpoint_type")
    if not isinstance(raw_type, str) or raw_type.strip().lower() not in _ENDPOINT_ALIASES:
        raise SampleSizeInputError(
            f"endpoint_type 必须是 {sorted(set(_ENDPOINT_ALIASES.values()))} 之一（支持中文别名），收到 {raw_type!r}")
    endpoint = _ENDPOINT_ALIASES[raw_type.strip().lower()]
    p = _common_inputs(inputs)

    if endpoint == "continuous":
        delta = abs(_check_range("mean_diff", _require_number(inputs, "mean_diff", "组间均值差（非0）"),
                                 0.0, float("inf")))
        var_t, var_c = _std_devs(inputs)
        p["mean_diff"] = delta
        for key in ("sd", "sd_experimental", "sd_control"):
            if inputs.get(key) is not None:
                p[key] = float(inputs[key])
        return _calc_continuous(p, "两样本 t 检验（正态近似）", delta, var_t, var_c)

    if endpoint == "binary":
        if inputs.get("p_experimental") is not None:
            key1 = "p_experimental"
        elif inputs.get("p1") is not None:
            key1 = "p1"
        else:
            raise SampleSizeInputError(
                "缺少必填参数 p_experimental（别名 p1）：试验组预期率（0<p1<1）")
        if inputs.get("p_control") is not None:
            key2 = "p_control"
        elif inputs.get("p2") is not None:
            key2 = "p2"
        else:
            raise SampleSizeInputError(
                "缺少必填参数 p_control（别名 p2）：对照组预期率（0<p2<1）")
        p1 = _check_range(key1, _require_number(inputs, key1, "试验组预期率（0<p<1）"), 0.0, 1.0)
        p2 = _check_range(key2, _require_number(inputs, key2, "对照组预期率（0<p<1）"), 0.0, 1.0)
        if p1 == p2:
            raise SampleSizeInputError(f"两比例相等（p1=p2={p1:g}），无法计算样本量")
        p["p_experimental"], p["p_control"] = p1, p2
        return _calc_binary(p, p1, p2)

    if endpoint == "time_to_event":
        hr = _require_number(inputs, "hazard_ratio", "风险比 HR（>0 且 ≠1）")
        _check_range("hazard_ratio", hr, 0.0, float("inf"))
        if hr == 1.0:
            raise SampleSizeInputError(f"hazard_ratio=1 无效应可检验，必须 HR>0 且 HR≠1，收到 {hr}")
        event_rate = None
        if inputs.get("event_rate") is not None:
            event_rate = _check_range("event_rate",
                                      _require_number(inputs, "event_rate", "研究期内总体事件率 (0,1]"),
                                      0.0, 1.0, include_high=True)
        p["hazard_ratio"] = hr
        if event_rate is not None:
            p["event_rate"] = event_rate
        return _calc_time_to_event(p, hr, event_rate)

    # non_inferiority
    margin = _check_range("non_inferiority_margin",
                          _require_number(inputs, "non_inferiority_margin", "非劣效固定边际（>0）"),
                          0.0, float("inf"))
    ni_p = dict(p)
    ni_p["two_sided"] = inputs.get("two_sided", False)  # 非劣效默认单侧；显式 True 会报错
    ni_p["non_inferiority_margin"] = margin
    ni_type = inputs.get("ni_data_type")
    if ni_type is not None:
        if ni_type not in ("continuous", "binary"):
            raise SampleSizeInputError(f"ni_data_type 仅支持 continuous/binary，收到 {ni_type!r}")
        ni_p["ni_data_type"] = ni_type
    if "sd" in inputs:
        ni_p["sd"] = inputs["sd"]
    if "sd_experimental" in inputs:
        ni_p["sd_experimental"] = inputs["sd_experimental"]
    if "sd_control" in inputs:
        ni_p["sd_control"] = inputs["sd_control"]
    if "p0" in inputs:
        ni_p["p0"] = inputs["p0"]
    return _calc_non_inferiority(ni_p, margin)
