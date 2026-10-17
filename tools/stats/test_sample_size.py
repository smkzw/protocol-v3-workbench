"""sample_size / render_zh 对拍测试（不依赖主 tests/ 套件）。

对拍策略：
- 环境有 scipy 时，用 scipy.stats.norm.ppf 独立重算期望值并与本库输出比对；
- 无 scipy 时，退化为经典教科书例题的手写期望值（正态分位数取标准硬编码值）。

运行方式：
    python3 tools/stats/test_sample_size.py
    python3 -m unittest discover -s tools/stats -p "test_*.py" -t tools/stats
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sample_size as ss  # noqa: E402
from sample_size import SampleSizeInputError, calculate, _z_quantile  # noqa: E402
from render_zh import render_zh_paragraph, render_zh_table_rows  # noqa: E402

try:
    from scipy.stats import norm as _scipy_norm  # type: ignore
except Exception:  # pragma: no cover - 环境无 scipy 时走手写期望值
    _scipy_norm = None

# 标准正态分位数硬编码参考值（位数足够区分任何舍入误差）
Z_095 = 1.6448536270
Z_0975 = 1.9599639845
Z_080 = 0.8416212336
Z_090 = 1.2815515655


def z_ref(p: float) -> float:
    """参考 z 分位数：优先 scipy，缺失时只支持本测试用到的标准值。"""
    if _scipy_norm is not None:
        return float(_scipy_norm.ppf(p))
    table = {
        0.95: Z_095,
        0.975: Z_0975,
        0.8: Z_080,
        0.9: Z_090,
    }
    key = round(p, 6)
    if key not in table:
        raise AssertionError(f"无 scipy 环境且 p={p} 无硬编码参考值")
    return table[key]


def z_from_inputs(alpha: float, power: float, two_sided: bool = True) -> tuple[float, float]:
    za = z_ref(1 - alpha / 2) if two_sided else z_ref(1 - alpha)
    zb = z_ref(power)
    return za, zb


class TestNormalQuantile(unittest.TestCase):
    """手写 z 分位数近似 vs scipy / 硬编码标准值。"""

    def test_known_quantiles(self) -> None:
        cases = [(0.975, 1.9599639845), (0.95, 1.6448536270), (0.8, 0.8416212336), (0.9, 1.2815515655)]
        for p, expected in cases:
            self.assertAlmostEqual(_z_quantile(p), expected, places=4, msg=f"z({p})")

    def test_symmetry(self) -> None:
        self.assertAlmostEqual(_z_quantile(0.975) + _z_quantile(0.025), 0.0, places=6)

    @unittest.skipIf(_scipy_norm is None, "scipy 不可用")
    def test_against_scipy_grid(self) -> None:
        for p in [0.5 + 1e-6, 0.6, 0.75, 0.9, 0.975, 0.995, 0.999]:
            self.assertAlmostEqual(_z_quantile(p), float(_scipy_norm.ppf(p)), places=6, msg=f"z({p})")


class TestContinuousSuperiority(unittest.TestCase):
    def test_textbook_case_power90(self) -> None:
        # 经典例题：α=0.05 双侧、power=0.9、Δ=1、SD=1 → 每组 n≈22
        r = calculate({"endpoint_type": "continuous", "mean_diff": 1.0, "sd": 1.0, "alpha": 0.05, "power": 0.9})
        za, zb = z_from_inputs(0.05, 0.9)
        expected = math.ceil(2 * (za + zb) ** 2 * 1.0 / 1.0)
        self.assertEqual(r.n_experimental, expected)
        self.assertEqual(r.n_control, expected)
        self.assertIn(r.n_experimental, (21, 22, 23))  # 教科书答案量级（含校正前后的区间）
        self.assertEqual(r.n_total, 2 * r.n_experimental)
        self.assertIsNone(r.events_required)

    def test_textbook_case_power80_delta05(self) -> None:
        # Δ=0.5、SD=1.2、power=0.8 → 每组 n=91
        r = calculate({"endpoint_type": "continuous", "mean_diff": 0.5, "sd": 1.2, "alpha": 0.05, "power": 0.8})
        za, zb = z_from_inputs(0.05, 0.8)
        expected = math.ceil((za + zb) ** 2 * (1.2**2 + 1.2**2) / 0.5**2)
        self.assertEqual(r.n_control, expected)
        self.assertEqual(r.n_control, 91)

    def test_separate_sds_and_allocation_and_dropout(self) -> None:
        # Δ=1、SD_e=SD_c=2、k=2（试验:对照=2:1）、脱落 10%
        r = calculate({
            "endpoint_type": "continuous", "mean_diff": 1.0, "sd": 2.0,
            "alpha": 0.05, "power": 0.9, "allocation_ratio": 2.0, "dropout_rate": 0.1,
        })
        za, zb = z_from_inputs(0.05, 0.9)
        n_ctl = math.ceil((za + zb) ** 2 * (4.0 / 2.0 + 4.0) / 1.0)
        n_exp = math.ceil(2.0 * (za + zb) ** 2 * (4.0 / 2.0 + 4.0) / 1.0)
        self.assertEqual(r.n_control, n_ctl)
        self.assertEqual(r.n_experimental, n_exp)
        self.assertEqual(r.n_control, 64)
        self.assertEqual(r.n_experimental, 127)
        self.assertEqual(r.n_control_adjusted, math.ceil(64 / 0.9))
        self.assertEqual(r.n_experimental_adjusted, math.ceil(127 / 0.9))
        self.assertEqual(r.n_total_adjusted,
                         r.n_experimental_adjusted + r.n_control_adjusted)


class TestBinarySuperiority(unittest.TestCase):
    def test_p06_vs_p04_power80(self) -> None:
        # p1=0.6 vs p2=0.4、α=0.05 双侧、power=0.8 → 每组 97（合并 p̄ 公式）
        r = calculate({"endpoint_type": "binary", "p_experimental": 0.6, "p_control": 0.4,
                       "alpha": 0.05, "power": 0.8})
        za, zb = z_from_inputs(0.05, 0.8)
        pbar = 0.5
        expected = math.ceil(
            (za * math.sqrt(2 * pbar * (1 - pbar))
             + zb * math.sqrt(0.6 * 0.4 + 0.4 * 0.6)) ** 2 / (0.6 - 0.4) ** 2
        )
        self.assertEqual(r.n_experimental, expected)
        self.assertEqual(r.n_experimental, 97)
        self.assertEqual(r.n_total, 194)

    def test_p085_vs_p065_alloc2_power90(self) -> None:
        # p1=0.85 vs p2=0.65、power=0.9、k=2（Fleiss 不等分配合并公式）
        r = calculate({"endpoint_type": "binary", "p1": 0.85, "p2": 0.65,
                       "alpha": 0.05, "power": 0.9, "allocation_ratio": 2.0})
        za, zb = z_from_inputs(0.05, 0.9)
        k = 2.0
        pbar = (k * 0.85 + 0.65) / (k + 1)
        n_ctl = math.ceil(
            (za * math.sqrt((1 + 1 / k) * pbar * (1 - pbar))
             + zb * math.sqrt(0.85 * 0.15 / k + 0.65 * 0.35)) ** 2 / 0.2**2
        )
        n_exp = math.ceil(k * (
            (za * math.sqrt((1 + 1 / k) * pbar * (1 - pbar))
             + zb * math.sqrt(0.85 * 0.15 / k + 0.65 * 0.35)) ** 2 / 0.2**2))
        self.assertEqual(r.n_control, n_ctl)
        self.assertEqual(r.n_experimental, n_exp)
        self.assertEqual((r.n_control, r.n_experimental), (71, 142))

    @unittest.skipIf(_scipy_norm is None, "scipy 不可用")
    def test_binary_against_scipy_recompute(self) -> None:
        r = calculate({"endpoint_type": "binary", "p1": 0.3, "p2": 0.45,
                       "alpha": 0.05, "power": 0.9})
        za, zb = z_from_inputs(0.05, 0.9)
        pbar = 0.375
        expected = math.ceil(
            (float(_scipy_norm.ppf(0.975)) * math.sqrt(2 * pbar * (1 - pbar))
             + float(_scipy_norm.ppf(0.9)) * math.sqrt(0.3 * 0.7 + 0.45 * 0.55)) ** 2 / 0.15**2
        )
        self.assertEqual(r.n_experimental, expected)


class TestTimeToEvent(unittest.TestCase):
    def test_schoenfeld_hr07_events247(self) -> None:
        # HR=0.7、α=0.05 双侧、power=0.8、1:1 → 事件数 ≈247（Schoenfeld）
        r = calculate({"endpoint_type": "time_to_event", "hazard_ratio": 0.7,
                       "alpha": 0.05, "power": 0.8})
        za, zb = z_from_inputs(0.05, 0.8)
        expected = math.ceil((za + zb) ** 2 / (0.25 * math.log(0.7) ** 2))
        self.assertEqual(r.events_required, expected)
        self.assertAlmostEqual(r.events_required, 247, delta=8)  # 经典量级
        # 未给事件率：不换算入组人数
        self.assertIsNone(r.n_total)

    def test_hr075_alloc2_dropout10_with_event_rate(self) -> None:
        # HR=0.75、power=0.9、k=2、总体事件率 0.75、脱落 10%
        r = calculate({"endpoint_type": "time_to_event", "hazard_ratio": 0.75,
                       "alpha": 0.05, "power": 0.9, "allocation_ratio": 2.0,
                       "event_rate": 0.75, "dropout_rate": 0.1})
        za, zb = z_from_inputs(0.05, 0.9)
        p_exp = 2.0 / 3.0
        d_raw = (za + zb) ** 2 / (p_exp * (1 - p_exp) * math.log(0.75) ** 2)
        self.assertEqual(r.events_required, math.ceil(d_raw))
        self.assertEqual(r.events_required, 572)
        n_total_raw = d_raw / 0.75
        n_ctl = math.ceil(n_total_raw / 3.0)
        n_exp = math.ceil(2.0 * n_total_raw / 3.0)
        self.assertEqual((r.n_control, r.n_experimental), (n_ctl, n_exp))
        self.assertEqual((r.n_control, r.n_experimental), (254, 508))
        self.assertEqual(r.n_control_adjusted, math.ceil(254 / 0.9))
        self.assertEqual(r.n_experimental_adjusted, math.ceil(508 / 0.9))

    @unittest.skipIf(_scipy_norm is None, "scipy 不可用")
    def test_tte_against_scipy_recompute(self) -> None:
        r = calculate({"endpoint_type": "time_to_event", "hazard_ratio": 0.8,
                       "alpha": 0.05, "power": 0.9})
        d = (float(_scipy_norm.ppf(0.975)) + float(_scipy_norm.ppf(0.9))) ** 2 / (
            0.25 * math.log(0.8) ** 2)
        self.assertEqual(r.events_required, math.ceil(d))


class TestNonInferiority(unittest.TestCase):
    def test_continuous_margin03(self) -> None:
        # 连续型 NI：边际 0.3、SD=1、单侧 α=0.05、power=0.8 → 每组 138
        r = calculate({"endpoint_type": "non_inferiority", "ni_data_type": "continuous",
                       "non_inferiority_margin": 0.3, "sd": 1.0, "alpha": 0.05, "power": 0.8})
        za, zb = z_from_inputs(0.05, 0.8, two_sided=False)
        expected = math.ceil((za + zb) ** 2 * 2.0 / 0.3**2)
        self.assertEqual(r.n_experimental, expected)
        self.assertEqual(r.n_experimental, 138)
        self.assertIn("单侧", " ".join(r.assumptions))

    def test_binary_p07_margin01_power90(self) -> None:
        # 二分类 NI：p0=0.7、边际 0.1、单侧 α=0.025、power=0.9 → 每组 442
        r = calculate({"endpoint_type": "non_inferiority", "ni_data_type": "binary",
                       "non_inferiority_margin": 0.1, "p0": 0.7, "alpha": 0.025, "power": 0.9})
        za, zb = z_from_inputs(0.025, 0.9, two_sided=False)
        expected = math.ceil((za + zb) ** 2 * 0.7 * 0.3 * 2.0 / 0.1**2)
        self.assertEqual(r.n_experimental, expected)
        self.assertEqual(r.n_experimental, 442)

    def test_ni_infers_data_type(self) -> None:
        r = calculate({"endpoint_type": "non_inferiority", "non_inferiority_margin": 0.3,
                       "sd": 1.0, "alpha": 0.05, "power": 0.8})
        self.assertEqual(r.n_experimental, 138)


class TestCommonValidation(unittest.TestCase):
    def _calc(self, **kw):
        return calculate(kw)

    def test_alpha_out_of_range(self) -> None:
        for bad in (0.0, 1.0, 1.5, -0.05):
            with self.assertRaises(SampleSizeInputError, msg=f"alpha={bad}"):
                self._calc(endpoint_type="continuous", mean_diff=1, sd=1, alpha=bad)

    def test_power_out_of_range(self) -> None:
        for bad in (0.0, 1.0, 1.2, -0.5):
            with self.assertRaises(SampleSizeInputError, msg=f"power={bad}"):
                self._calc(endpoint_type="continuous", mean_diff=1, sd=1, power=bad)

    def test_hazard_ratio_illegal(self) -> None:
        for bad in (0.0, -1.5, 1.0):
            with self.assertRaises(SampleSizeInputError, msg=f"hr={bad}"):
                self._calc(endpoint_type="time_to_event", hazard_ratio=bad)

    def test_dropout_rate_illegal(self) -> None:
        for bad in (1.0, -0.1):
            with self.assertRaises(SampleSizeInputError, msg=f"dropout={bad}"):
                self._calc(endpoint_type="continuous", mean_diff=1, sd=1, dropout_rate=bad)

    def test_allocation_ratio_illegal(self) -> None:
        for bad in (0.0, -2.0):
            with self.assertRaises(SampleSizeInputError, msg=f"alloc={bad}"):
                self._calc(endpoint_type="continuous", mean_diff=1, sd=1, allocation_ratio=bad)

    def test_continuous_illegal(self) -> None:
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="continuous", mean_diff=0.0, sd=1.0)
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="continuous", mean_diff=1.0, sd=0.0)
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="continuous", sd=1.0)  # 缺 mean_diff

    def test_binary_illegal(self) -> None:
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="binary", p1=0.0, p2=0.4)
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="binary", p1=0.6, p2=1.0)
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="binary", p1=0.5, p2=0.5)

    def test_tte_event_rate_illegal(self) -> None:
        for bad in (0.0, -0.2, 1.5):
            with self.assertRaises(SampleSizeInputError, msg=f"event_rate={bad}"):
                self._calc(endpoint_type="time_to_event", hazard_ratio=0.7, event_rate=bad)

    def test_ni_illegal(self) -> None:
        with self.assertRaises(SampleSizeInputError):  # 双侧 + NI 不允许
            self._calc(endpoint_type="non_inferiority", non_inferiority_margin=0.3,
                       sd=1.0, alpha=0.05, two_sided=True)
        with self.assertRaises(SampleSizeInputError):  # 边非正
            self._calc(endpoint_type="non_inferiority", non_inferiority_margin=0.0, sd=1.0)
        with self.assertRaises(SampleSizeInputError):  # 既无 sd 也无 p0
            self._calc(endpoint_type="non_inferiority", non_inferiority_margin=0.3)
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="non_inferiority", non_inferiority_margin=0.1, p0=1.2)

    def test_unknown_endpoint_and_non_dict(self) -> None:
        with self.assertRaises(SampleSizeInputError):
            self._calc(endpoint_type="survival_cure", hazard_ratio=0.7)
        with self.assertRaises(SampleSizeInputError):
            calculate("continuous")  # type: ignore[arg-type]

    def test_result_contract_fields(self) -> None:
        r = calculate({"endpoint_type": "continuous", "mean_diff": 1.0, "sd": 1.0})
        self.assertTrue(r.formula_name)
        self.assertTrue(r.formula_label_zh)
        self.assertIn("alpha", r.parameters)
        self.assertTrue(r.assumptions)
        d = r.to_dict()
        json.dumps(d)  # 必须可 JSON 序列化
        self.assertEqual(d["n_total"], r.n_total)


ZH_PLACEHOLDER_TOKENS = ("XXX", "xxx", "{", "}", "None", "nan", "%s", "TODO")


class TestRenderZh(unittest.TestCase):
    def _assert_no_placeholder(self, text: str) -> None:
        for token in ZH_PLACEHOLDER_TOKENS:
            self.assertNotIn(token, text, msg=f"渲染结果含占位符 {token!r}: {text}")

    def test_continuous_paragraph(self) -> None:
        r = calculate({"endpoint_type": "continuous", "mean_diff": 1.0, "sd": 1.0,
                       "alpha": 0.05, "power": 0.9, "dropout_rate": 0.15})
        para = render_zh_paragraph(r)
        self._assert_no_placeholder(para)
        self.assertIn("44", para) or self.assertIn(str(r.n_total), para)
        self.assertIn(str(r.n_total_adjusted), para)
        self.assertIn("15%", para)
        self.assertIn("试验组", para)
        self.assertIn("对照组", para)

    def test_binary_paragraph_alloc2(self) -> None:
        r = calculate({"endpoint_type": "binary", "p1": 0.85, "p2": 0.65,
                       "alpha": 0.05, "power": 0.9, "allocation_ratio": 2.0})
        para = render_zh_paragraph(r)
        self._assert_no_placeholder(para)
        self.assertIn("2:1", para)
        self.assertIn(str(r.n_experimental), para)
        self.assertIn(str(r.n_control), para)

    def test_tte_paragraph_events(self) -> None:
        r = calculate({"endpoint_type": "time_to_event", "hazard_ratio": 0.7,
                       "alpha": 0.05, "power": 0.8, "event_rate": 0.8, "dropout_rate": 0.1})
        para = render_zh_paragraph(r)
        self._assert_no_placeholder(para)
        self.assertIn("247", para)
        self.assertIn("事件", para)
        self.assertIn(str(r.n_total_adjusted), para)

    def test_tte_paragraph_without_event_rate(self) -> None:
        r = calculate({"endpoint_type": "time_to_event", "hazard_ratio": 0.7,
                       "alpha": 0.05, "power": 0.8})
        para = render_zh_paragraph(r)
        self._assert_no_placeholder(para)
        self.assertIn("247", para)

    def test_ni_paragraph(self) -> None:
        r = calculate({"endpoint_type": "non_inferiority", "ni_data_type": "binary",
                       "non_inferiority_margin": 0.1, "p0": 0.7, "alpha": 0.025, "power": 0.9})
        para = render_zh_paragraph(r)
        self._assert_no_placeholder(para)
        self.assertIn("0.1", para)
        self.assertIn("非劣效", para)

    def test_table_rows(self) -> None:
        r = calculate({"endpoint_type": "time_to_event", "hazard_ratio": 0.75,
                       "alpha": 0.05, "power": 0.9, "allocation_ratio": 2.0,
                       "event_rate": 0.75, "dropout_rate": 0.1})
        rows = render_zh_table_rows(r)
        self.assertTrue(rows)
        flat = " ".join(f"{row['item']}={row['value']}" for row in rows)
        self._assert_no_placeholder(flat)
        for token in ("572", "2:1", "10%", "0.75"):
            self.assertIn(token, flat)
        # 假设明细进表
        self.assertTrue(any("假设" in row["item"] for row in rows))

    def test_render_is_deterministic(self) -> None:
        inputs = {"endpoint_type": "continuous", "mean_diff": 0.8, "sd": 1.1,
                  "alpha": 0.05, "power": 0.8, "allocation_ratio": 1.5, "dropout_rate": 0.2}
        r1 = calculate(dict(inputs))
        r2 = calculate(dict(inputs))
        self.assertEqual(render_zh_paragraph(r1), render_zh_paragraph(r2))
        self.assertEqual(render_zh_table_rows(r1), render_zh_table_rows(r2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
