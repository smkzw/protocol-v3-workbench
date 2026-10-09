"""A11 permanent regression: the generation-context route-digest tests must
pass under ANY collection order relative to tests/test_ai_execution_policy.py.

Evidence chain (2026-09-27, this repo, HEAD 5b4c8c1):
- polluter: tests/test_ai_execution_policy.py — its COLLECTION-TIME import
  (from services.api.app.main import app, line 27) seeds
  ai_provider_settings.json (enabled cloud fallback chain) into the current
  WORKBENCH_RUNTIME_DIR via main.py:1840 import-time store bootstrap;
- victim: tests/test_medical_writing_generation_context_v2.py digest tests —
  their _policy_runner resolvers do not set test_only_provider_injection, so
  route_identity_snapshot(refresh=True, task_type=medical_writing_revision)
  consults the live settings (ai_execution_policy.py:458-464,
  _capture_revision_cloud_route :359-383) and overrides both pinned routes —
  digests become identical and the policy-change assertion fails.
- Victim solo (settings file absent) passes; under the polluter's import it
  fails in EVERY collection order (import order = collection order), which is
  the honest import-order-pollution signature. Fix: the harness boundary flag
  test_only_provider_injection=True in _policy_runner (the product's
  documented freeze, ai_execution_policy.py:446-452). No assertion changed.

Each step runs a REAL subprocess pytest with a hard timeout (red line 6-2);
offline, zero models (A16); the subprocess env deliberately omits
WORKBENCH_RUNTIME_DIR so tests/conftest.py provisions a fresh private runtime
per run — no state leaks between steps.

0927V1 家族级加固（本会话实测）:
- 全仓 AST 普查: tests/ 下 22 个文件共 61 处 AiExecutionPolicyResolver(
  构造点，24 处已冻结；37 处未冻结散布在 13 个文件 → 已逐项核实并白名单化
  （A11_RESOLVER_FREEZE_ALLOWLIST，每项一行核实理由）。守卫在"白名单未
  定稿"（空）状态下对真实扫描结果红（列出未冻结散点），定稿后绿。
- 本文件加入守卫后整文件实跑 6 passed（15.43s，step1-4 为真实 pytest
  子进程）。victim 文件整文件双序各 55 passed（39.9s×2）为上一会话
  （0926V2 实施会话，HEAD 5bca561）实测记录，本轮未重跑。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

VICTIM = ("tests/test_medical_writing_generation_context_v2.py"
          "::GenerationContextDescriptorTests::test_policy_change_changes_digest")
POLLUTER = ("tests/test_ai_execution_policy.py"
            "::AiExecutionPolicyTests::test_ai_result_reads_fail_closed_before_runner_access")

ORDER_PLUGIN = ["-p", "pytest_order_control"]
SUBPROCESS_TIMEOUT_S = 240


def _run_nodes(*nodes: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "PYTHONPATH": "services/api:.:tools/acceptance",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    cmd = [sys.executable, "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider",
           *(extra or [])]
    return subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True,
                          text=True, timeout=SUBPROCESS_TIMEOUT_S)


def test_a11_step1_victim_alone_passes():
    proc = _run_nodes(VICTIM)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_a11_step2_polluter_before_victim_passes():
    # pre-fix this was RED in every order: collecting the polluter seeds the
    # live settings that override the victim's pinned routes.
    proc = _run_nodes(POLLUTER, VICTIM)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_a11_step3_victim_before_polluter_passes():
    proc = _run_nodes(VICTIM, POLLUTER)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_a11_step4_seeded_random_orders_pass():
    for seed in (20260927, 1, 42):
        proc = _run_nodes(POLLUTER, VICTIM, extra=[*ORDER_PLUGIN, f"--order-seed={seed}"])
        assert proc.returncode == 0, (seed, proc.stdout + proc.stderr[-1500:])


# ── E1 顺序污染永久回归（2026-10-08 新纪元账本种子①根治）─────────────────
# 污染向量（2026-10-08 本会话实测定位；单向：wrapper→policy 红，反序/单跑
# 全过）：
#   tests/protocol_v3/test_frontend_check_wrapper.py::
#       SideEffectSafetyTests::test_wrapper_import_does_not_import_main_py
# 为验证"wrapper 导入不加载 main.py"，该测试把 sys.modules 里全部 *.main
# 模块逐出却从不恢复。同进程后续任何"收集期 from services.api.app.main
# import app + 运行期 patch('services.api.app.main.<attr>)"的测试（如
# AiExecutionPolicyTests 的 fail-closed 用例）随即发生模块身份分裂：请求
# 由被逐出的旧实例路由服务，patch 落在重新导入的新实例上 → patch 不生效
# → with_principal 期望 403 实得 503（monitoring_principal_unavailable）。
# 修复=污染者根治：逐出前快照、addCleanup 原位恢复（会话身份契约：测试
# 结束时 sys.modules 的 *.main 条目与进入时同物）。以下三步真实 pytest
# 子进程锁定该向量，防止未来任何形式的模块逐出泄漏再犯。

WRAPPER_MODULE_POLLUTER = (
    "tests/protocol_v3/test_frontend_check_wrapper.py"
    "::SideEffectSafetyTests::test_wrapper_import_does_not_import_main_py"
)
E1_POLICY_VICTIMS = (
    "tests/test_ai_execution_policy.py"
    "::AiExecutionPolicyTests::test_ai_result_reads_fail_closed_before_runner_access",
    "tests/test_ai_execution_policy.py"
    "::AiExecutionPolicyTests::test_registered_source_execution_api_fails_closed_before_runner",
)


def test_e1_step1_policy_victims_alone_pass():
    proc = _run_nodes(*E1_POLICY_VICTIMS)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_e1_step2_wrapper_module_before_policy_passes():
    # 修复前红：wrapper→policy 单向顺序污染（新纪元账本 E1）。
    proc = _run_nodes(WRAPPER_MODULE_POLLUTER, *E1_POLICY_VICTIMS)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_e1_step3_policy_before_wrapper_module_passes():
    proc = _run_nodes(*E1_POLICY_VICTIMS, WRAPPER_MODULE_POLLUTER)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


# ── A11 家族级静态守卫（0927V1 目标二之二）────────────────────────────────
# 上述 step1-4 只锁定两个文件的 3 个节点；2026-09-27 全仓普查（AST 扫描）
# 显示 tests/ 下 22 个文件共 61 处 AiExecutionPolicyResolver( 构造点，其中
# 37 处（13 个文件）未传 test_only_provider_injection=True。收集期
# from services.api.app.main import app（main.py 导入期一次性读取
# WORKBENCH_RUNTIME_DIR）播种的设置对同进程后续测试全程可见，任何未来新增
# 的未冻结受害者都会在随机顺序下偶发红。本守卫把"单点修复"升级为"家族级
# 顺序隔离"：凡未冻结的构造点必须落在显式白名单内，且每个白名单条目必须
# 附一行"为什么故意不冻结"的核实理由——未来任何新未冻结站点会在这里红，
# 而不是在生产运行里偶发红。
#
# AST 扫描（非正则）以容忍多行构造写法；kwargs 展开等无字面量关键字的
# 构造按"未冻结"保守处理。

A11_RESOLVER_FREEZE_ALLOWLIST: dict[str, str] = {
    "tests/test_fallback_401_handoff.py": (
        "401回退链路测试：通过 patch runtime store 构造受限配置并断言"
        "真实回退行为，属集成路径验证而非注入越权构造（r12批后复核）。"
    ),
    "tests/test_ai_execution_policy.py": (
        "该文件就是动态解析行为规格本身（A11 记录的收集期污染源）；未冻结"
        "构造点刻意行使真实 TASK_AI_ROUTE_POLICIES 执法与 fail-closed 语义，"
        "冻结会让它测试冻结旁路而不是产品行为。"
    ),
    "tests/test_ai_fallback_chain.py": (
        "空 resolver 在显式 settings-store patch 内运行，专门测试 fallback "
        "chain 对（受控）live 设置的动态读取行为——冻结即失去被测对象。"
    ),
    "tests/test_ai_route_freeze.py": (
        "路由冻结/变更/哈希语义规格：必须在真实解析下跨 route mutation "
        "断言 route_identity_hash 变化，冻结后 mutation 断言恒真。"
    ),
    "tests/test_ai_task_runner.py": (
        "用策略表覆盖的任务类型（protocol_full_draft/protocol_synopsis_"
        "structuring）+ 未冻结旗标，刻意行使 _enforce_task_ai_route_policy "
        "对显式 provider 绑定的真实执法路径。"
    ),
    "tests/test_eligibility_ai_contract.py": (
        "eligibility_rule_review 不在 TASK_AI_ROUTE_POLICIES（ai_execution_"
        "policy.py:175-206），live 设置不参与解析断言；未冻结保持生产解析"
        "路径而非冻结旁路。"
    ),
    "tests/test_eligibility_ai_review.py": (
        "同族 eligibility 契约测试：任务类型不在策略表，断言绑定 service "
        "输出与 fail-closed 路径；未冻结保持生产解析路径。"
    ),
    "tests/test_evidence_ai_revision_service.py": (
        "provider 经 factory 显式注入，断言绑定证据修订 service 输出而非 "
        "route identity；未冻结保持生产解析路径。"
    ),
    "tests/test_medical_writing_durable_job_integration.py": (
        "revision 解析器仅作 plumbing：digest 断言来自同一 resolver 实例的"
        "两次调用（实例内一致），对 live 设置播种不变（2026-09-27 双序整"
        "文件实测存活）。"
    ),
    "tests/test_medical_writing_registered_sources.py": (
        "disabled profile / DisabledAiProvider 的 fail-closed 断言；revision "
        "cloud 捕获抛 AiExecutionPolicyDenied 被捕获（ai_execution_policy."
        "py:464-466），live 设置无法改变 disabled 语义。"
    ),
    "tests/test_medical_writing_revision_api.py": (
        "DisabledAiProvider blocked-path 断言：live 设置无法使 disabled "
        "provider 成功，409/blocked 语义与设置无关。"
    ),
    "tests/test_medical_writing_revision_durable.py": (
        "resolver 仅喂 durable job 身份 plumbing（durable create/dedupe/"
        "reuse，无真实 AI 调用），断言不依赖 route identity。"
    ),
    "tests/test_source_content_validation.py": (
        "listing_semantic_mapping 不在 TASK_AI_ROUTE_POLICIES，断言注册表"
        "内容一致性校验而非路由；未冻结保持生产解析路径。"
    ),
    "tests/test_source_registry.py": (
        "registry 任务类型（competitive_intelligence/listing_semantic_"
        "mapping/monitoring_risk_interpretation/safety_case_medical_review）"
        "均不在策略表，断言注册表契约而非路由。"
    ),
}


def _unfrozen_resolver_sites() -> list[tuple[str, int]]:
    """AST-scan tests/ for AiExecutionPolicyResolver( construction sites
    without the test_only_provider_injection freeze flag."""
    import ast

    sites: list[tuple[str, int]] = []
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name != "AiExecutionPolicyResolver":
                continue
            frozen = any(
                kw.arg == "test_only_provider_injection" for kw in node.keywords
            )
            if not frozen:
                sites.append((str(path.relative_to(REPO_ROOT)), node.lineno))
    return sites


class A11ResolverFreezeFamilyGuard(unittest.TestCase):
    """未冻结的 AiExecutionPolicyResolver 构造点必须逐项白名单化。"""

    def test_every_unfrozen_resolver_site_is_allowlisted_with_reason(self):
        strays = [
            (path, line)
            for path, line in _unfrozen_resolver_sites()
            if path not in A11_RESOLVER_FREEZE_ALLOWLIST
        ]
        self.assertEqual(
            [],
            strays,
            "未冻结的 AiExecutionPolicyResolver 构造点必须要么加 "
            "test_only_provider_injection=True（测试边界冻结旗标，见 "
            "ai_execution_policy.py:446-452），要么在 "
            "A11_RESOLVER_FREEZE_ALLOWLIST 里附一行'为什么故意不冻结'的"
            "核实理由——否则它会成为下一个顺序敏感 flaky 的受害者。",
        )

    def test_allowlist_entries_are_real_files_with_reasons(self):
        test_files = {
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "tests").rglob("*.py")
        }
        for path, reason in A11_RESOLVER_FREEZE_ALLOWLIST.items():
            self.assertIn(path, test_files, f"白名单指向不存在的测试文件: {path}")
            self.assertTrue(
                isinstance(reason, str) and reason.strip(),
                f"白名单条目缺核实理由: {path}",
            )
