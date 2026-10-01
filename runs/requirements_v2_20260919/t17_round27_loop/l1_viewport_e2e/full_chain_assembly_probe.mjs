#!/usr/bin/env node
// NEW-1 全链验收探针（实现师 FAST 自查仪器）：1512×814 真实浏览器（CDP）
// 走完整用户链——新建项目（从零开始）→ 研究框架两步 → PICOS 六组+设计确认
// → 例外放行 → 进入写作平台 → 建立工作稿成功。只新建自己的项目，不动既有
// 项目；除 UI 操作与只读状态查询外不直接调任何写接口。
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_URL = "http://127.0.0.1:5186/";
const DEBUG_PORT = 9653;
const OUT_DIR = path.dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PRODUCT = process.env.PROBE_PRODUCT || "MSC-201";
const INDICATION = process.env.PROBE_INDICATION || "绝经后血管舒缩症状（潮热）";
const PHASE = "II期";

function createCdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const cb = pending.get(message.id);
      pending.delete(message.id);
      message.error ? cb.reject(new Error(message.error.message)) : cb.resolve(message.result || {});
      return;
    }
    for (const listener of listeners.get(message.method) || []) listener(message.params || {});
  });
  return {
    ready: new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    }),
    send(method, params = {}) {
      const id = nextId++;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    on(method, cb) {
      listeners.set(method, [...(listeners.get(method) || []), cb]);
    },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
}

async function waitFor(cdp, expression, timeoutMs = 30000, label = "") {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(cdp, expression)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`timeout(${timeoutMs}ms): ${label || expression}`);
}

async function shot(cdp, name) {
  const image = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(path.join(OUT_DIR, name), Buffer.from(image.data, "base64"));
}

const setValue = (selector, value, proto = "HTMLInputElement") => `(() => {
  const el = document.querySelector(${JSON.stringify(selector)});
  if (!el) return false;
  const setter = Object.getOwnPropertyDescriptor(${proto}.prototype, "value").set;
  setter.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
})()`;

const setSelectByLabel = (label, value) => `(() => {
  const el = Array.from(document.querySelectorAll("select")).find((item) =>
    (item.getAttribute("aria-label") || "").includes(${JSON.stringify(label)})
    || (item.closest("label")?.textContent || "").includes(${JSON.stringify(label)}));
  if (!el) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
  setter.call(el, ${JSON.stringify(value)});
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
})()`;

const checkByLabel = (label, checked) => `(() => {
  const el = Array.from(document.querySelectorAll('input[type="checkbox"]')).find((item) =>
    (item.getAttribute("aria-label") || "").includes(${JSON.stringify(label)})
    || (item.closest("label")?.textContent || "").includes(${JSON.stringify(label)}));
  if (!el) return false;
  if (el.checked !== ${checked ? "true" : "false"}) el.click();
  return true;
})()`;

const clickButton = (text) => `(() => {
  const el = Array.from(document.querySelectorAll("button")).find((item) =>
    !item.disabled && item.textContent.trim().includes(${JSON.stringify(text)}));
  if (!el) return false;
  el.click();
  return true;
})()`;

const textPresent = (text) => `document.body.textContent.includes(${JSON.stringify(text)})`;

const userDataDir = await mkdtemp(path.join(tmpdir(), "fullchain-probe-"));
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${DEBUG_PORT}`,
  `--user-data-dir=${userDataDir}`, "--no-first-run", "--no-default-browser-check", "about:blank",
], { stdio: "ignore" });

const trace = [];
const step = (name, detail) => { trace.push({ name, detail, at: new Date().toISOString() }); console.error(`[probe] ${name} ${detail || ""}`); };

let cdp;
try {
  for (let i = 0; i < 40; i++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json();
      cdp = createCdp(targets.find((item) => item.type === "page").webSocketDebuggerUrl);
      await cdp.ready;
      break;
    } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1512, height: 814, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: APP_URL });
  await waitFor(cdp, `document.body.textContent.includes("新建项目")`, 30000, "dashboard");

  // 1) 新建项目（从零开始）——点击后弹窗未开则重试一次
  await evaluate(cdp, clickButton("新建项目"));
  await new Promise((r) => setTimeout(r, 800));
  if (!(await evaluate(cdp, `Boolean(document.querySelector('.new-project-dialog'))`))) {
    await evaluate(cdp, clickButton("新建项目"));
    await new Promise((r) => setTimeout(r, 1200));
  }
  await waitFor(cdp, `Boolean(document.querySelector('.new-project-dialog'))`, 15000, "new project dialog");
  await evaluate(cdp, setValue('.new-project-fields label:nth-of-type(1) input', PRODUCT));
  await evaluate(cdp, setValue('.new-project-fields label:nth-of-type(2) input', INDICATION));
  await evaluate(cdp, setValue('.new-project-fields label:nth-of-type(3) select', PHASE, "HTMLSelectElement"));
  await evaluate(cdp, `(() => { const d = document.querySelector('.new-project-dialog'); d.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); return true; })()`);
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`, 60000, "journey shell");
  await shot(cdp, "chain_01_created.png");
  step("project created");
  // 等竞品流水线进入稳定等待位（等待语料准入），避免其推进修订号打断后续提交
  await waitFor(cdp, `document.querySelector('.authoring-research-progress-details summary small')?.textContent === "等待语料准入" || document.body.textContent.includes("等待语料准入")`, 240000, "pipeline stable-wait").catch(() => step("pipeline wait skipped"));

  // 影响确认面板：流水线占用时确认按钮禁用，按界面出口「取消本次流水线并
  // 立即提交」走（真实用户路径）
  const confirmImpactPanel = async (shotLabel) => {
    await new Promise((r) => setTimeout(r, 1000));
    if (await evaluate(cdp, `document.body.textContent.includes("取消本次流水线并立即提交")`)) {
      await evaluate(cdp, clickButton("取消本次流水线并立即提交"));
      await waitFor(cdp, `Array.from(document.querySelectorAll('.authoring-impact-panel button')).some(b => b.textContent.includes("确认取消流水线并提交变更"))`, 15000, `${shotLabel} arm confirm`);
      await evaluate(cdp, clickButton("确认取消流水线并提交变更"));
    } else {
      await evaluate(cdp, clickButton("确认变更并重新核验"));
    }
    await waitFor(cdp, `!Boolean(document.querySelector('.authoring-impact-panel'))`, 180000, `${shotLabel} impact confirm`).catch(async () => {
      step(`${shotLabel} impact panel stuck`, JSON.stringify(await evaluate(cdp, `({
        buttons: Array.from(document.querySelectorAll('.authoring-impact-panel button')).map((b) => ({ text: b.textContent.trim(), disabled: b.disabled })),
        msg: document.body.textContent.includes("暂不能保存研究框架"),
      })`)));
      throw new Error(`${shotLabel} impact panel did not clear`);
    });
  };

  // 2) 研究框架（第一步）：项目身份 + 设计意图
  await waitFor(cdp, `Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('完成第一步') && !b.disabled) ? true : false`, 20000, "framing editable").catch(async () => {
    // 高级微调可能需要展开
    await evaluate(cdp, `(() => { const d = document.querySelector('.authoring-advanced-refinement'); if (d && !d.open) { const s = d.querySelector('summary'); s && s.click(); } return true; })()`);
    await waitFor(cdp, `Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('完成第一步'))`, 10000, "framing button");
  });
  await evaluate(cdp, setValue('input[aria-label="方案号"], label textarea, input', "")); // noop guard
  // 通过 label 文本定位输入
  const setInputByLabel = (label, value, tag = "input") => `(() => {
    const PROTOS = { TEXTAREA: HTMLTextAreaElement, SELECT: HTMLSelectElement, INPUT: HTMLInputElement };
    const lab = Array.from(document.querySelectorAll("label")).find((item) => item.textContent.trim().startsWith(${JSON.stringify(label)}));
    if (!lab) return false;
    const el = lab.querySelector(${JSON.stringify(tag)}) || lab.querySelector("textarea");
    if (!el) return false;
    const proto = PROTOS[el.tagName] || HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, "value").set;
    setter.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`;
  await evaluate(cdp, setInputByLabel("方案号", "MSC-201-001"));
  await evaluate(cdp, setInputByLabel("版本", "V0.1"));
  await evaluate(cdp, setInputByLabel("方案标题", "MSC-201治疗绝经后血管舒缩症状的II期研究方案"));
  await evaluate(cdp, setInputByLabel("适应症", INDICATION));
  await evaluate(cdp, setInputByLabel("试验药物", PRODUCT));
  await evaluate(cdp, `(() => {
    const sel = document.querySelector('select[aria-label="药物技术类型"]');
    if (!sel) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(sel, 'small_molecule');
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  await evaluate(cdp, setSelectByLabel("剂型", "口服固体制剂"));
  await evaluate(cdp, setSelectByLabel("暴露范围", "systemic"));
  await evaluate(cdp, checkByLabel("口服", true));
  // 内在研究目的在「研究目的」组：先切组再勾选
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '研究目的'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 300));
  await evaluate(cdp, checkByLabel("概念验证", true));
  // 总体设计意图/目标研究人群意图在「总体设计」组
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '总体设计'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 300));
  await evaluate(cdp, setInputByLabel("总体设计", "随机、双盲、安慰剂对照、平行组、多中心研究", "textarea"));
  await evaluate(cdp, setInputByLabel("目标研究人群", "40-65岁绝经后女性中重度血管舒缩症状患者", "textarea"));
  await shot(cdp, "chain_02_framing_filled.png");
  // 诊断：完成第一步按钮的禁用状态与禁用原因（L4修复后title会点名缺什么）
  const framingDiag = await evaluate(cdp, `(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第一步"));
    return { disabled: btn?.disabled ?? null, title: btn?.title || "" };
  })()`);
  step("framing button diag", JSON.stringify(framingDiag));
  // 完成第一步（可能要求影响预览确认）
  await evaluate(cdp, clickButton("完成第一步"));
  await new Promise((r) => setTimeout(r, 2500));
  step("framing after-click diag", JSON.stringify(await evaluate(cdp, `({
    impact: Boolean(document.querySelector('.authoring-impact-panel')),
    strip0done: Array.from(document.querySelectorAll('.authoring-stage-strip button'))[0]?.className,
    msg: Array.from(document.querySelectorAll('.authoring-journey-message, .authoring-journey-footer span')).map((el) => el.textContent.trim().slice(0, 120)),
    pipelineStage: document.querySelector('.authoring-research-progress-details summary small')?.textContent || "",
  })`)));
  // 修订号被流水线推进导致的 stale 失败：走「保存草稿」恢复链（draft保存
  // 自带刷新重试），再提交（真实用户路径）
  for (let attempt = 1; attempt <= 3; attempt++) {
    const bodyText = await evaluate(cdp, `document.body.textContent`);
    if (String(bodyText).includes("stale authoring journey revision")) {
      step("stale revision hit, saving draft to refresh", `attempt=${attempt}`);
      await evaluate(cdp, clickButton("保存草稿"));
      await new Promise((r) => setTimeout(r, 4000));
      await evaluate(cdp, clickButton("完成第一步"));
      await new Promise((r) => setTimeout(r, 2500));
      continue;
    }
    break;
  }
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-impact-panel')) || Array.from(document.querySelectorAll('.authoring-stage-strip button'))[0]?.className.includes('done') || document.body.textContent.includes("暂不能保存研究框架")`, 45000, "framing commit response");
  // 流水线占用时按界面提示取消研究流水线再提交（真实用户路径）
  if (!(await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-stage-strip button'))[0]?.className.includes('done')`))) {
    await evaluate(cdp, `(() => { const d = document.querySelector('.authoring-research-progress-details'); if (d && !d.open) { const s = d.querySelector('summary'); s && s.click(); } return true; })()`);
    await evaluate(cdp, clickButton("取消研究流水线"));
    await new Promise((r) => setTimeout(r, 3000));
    await evaluate(cdp, clickButton("完成第一步"));
    await waitFor(cdp, `Boolean(document.querySelector('.authoring-impact-panel')) || Array.from(document.querySelectorAll('.authoring-stage-strip button'))[0]?.className.includes('done')`, 45000, "framing commit response after cancel");
  }
  if (await evaluate(cdp, `Boolean(document.querySelector('.authoring-impact-panel'))`)) {
    await shot(cdp, "chain_03_impact_framing.png");
    await confirmImpactPanel("framing");
  }
  await waitFor(cdp, `Array.from(document.querySelectorAll('.authoring-stage-strip button'))[0]?.className.includes('done')`, 120000, "framing strip done");
  await shot(cdp, "chain_04_framing_done.png");
  step("framing committed");

  // 框架完成后自动调研会重启：等忙碌位释放（真实用户此时也在等）
  await waitFor(cdp, `!Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('正在处理中')) && Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.disabled === false`, 240000, "picos strip enabled").catch(() => step("picos strip wait skipped"));
  // 3) PICOS（第二步）：六组逐项填写
  await evaluate(cdp, `(() => {
    const tab = Array.from(document.querySelectorAll('.authoring-stage-strip button')).find(b => b.textContent.includes('PICOS设计'));
    if (tab && !tab.disabled) { tab.click(); return true; }
    return false;
  })()`);
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-group-tabs')) || Boolean(document.querySelector('.authoring-advanced-refinement'))`, 30000, "picos stage");
  const setByLabelText = (label, value, tag = "input") => `(() => {
    const PROTOS = { TEXTAREA: HTMLTextAreaElement, SELECT: HTMLSelectElement, INPUT: HTMLInputElement };
    const lab = Array.from(document.querySelectorAll("label")).find((item) => item.textContent.trim().startsWith(${JSON.stringify(label)}));
    if (!lab) return false;
    const el = lab.querySelector(${JSON.stringify(tag)}) || lab.querySelector("textarea");
    if (!el) return false;
    const proto = PROTOS[el.tagName] || HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, "value").set;
    setter.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`;
  const addStructuredRow = async (label, text) => {
    const found = await evaluate(cdp, `(() => {
      const fs = Array.from(document.querySelectorAll('fieldset.authoring-structured-list')).find((f) => (f.querySelector('legend')?.textContent || '').trim().startsWith(${JSON.stringify(label)}));
      if (!fs) return 'no-fieldset';
      const add = Array.from(fs.querySelectorAll('button')).find((b) => b.textContent.includes('新增'));
      if (!add) return 'no-add';
      add.click();
      return 'added';
    })()`);
    await new Promise((r) => setTimeout(r, 200));
    const filled = await evaluate(cdp, `(() => {
      const fs = Array.from(document.querySelectorAll('fieldset.authoring-structured-list')).find((f) => (f.querySelector('legend')?.textContent || '').trim().startsWith(${JSON.stringify(label)}));
      if (!fs) return 'no-fieldset';
      const areas = Array.from(fs.querySelectorAll('textarea'));
      const target = areas[areas.length - 1];
      if (!target) return 'no-area';
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(target, ${JSON.stringify(text)});
      target.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    return { found, filled };
  };
  const addStructuredRows = async (label, items) => {
    const out = [];
    for (const text of items) out.push(await addStructuredRow(label, text));
    return out;
  };

  // 适用性组：设计类型 + 结构化设计确认
  await evaluate(cdp, `(() => { const el = document.querySelector('input[name="picos-design-archetype"][value="randomized_confirmatory"]'); if (el && !el.checked) el.click(); return true; })()`);
  await evaluate(cdp, setSelectByLabel("随机化", "randomized"));
  await evaluate(cdp, setSelectByLabel("盲法", "double_blind"));
  await evaluate(cdp, setSelectByLabel("对照类型", "placebo"));
  await evaluate(cdp, setSelectByLabel("分组", "平行组"));
  await evaluate(cdp, setSelectByLabel("中心模式", "多中心"));
  await evaluate(cdp, `(() => {
    const picks = [["适应性设计","false"],["交叉设计","false"],["开放标签延伸","false"],["治疗转换","false"],["样本量重估","false"],["期中分析","false"],["SRC","false"],["DMC","false"]];
    for (const [label, value] of picks) {
      const sel = Array.from(document.querySelectorAll('select')).find((s) => (s.getAttribute('aria-label')||'').includes(label));
      if (!sel) continue;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      setter.call(sel, value);
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return true;
  })()`);
  // 研究人群组
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '研究人群'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 400));
  await evaluate(cdp, setByLabelText("目标人群概述", "40-65岁绝经后女性，中重度血管舒缩症状（每周≥49次潮热）。", "textarea"));
  await addStructuredRows("入选标准", ["40-65岁自然绝经或手术绝经女性", "筛选前一周平均每日中重度潮热≥7次"]);
  await addStructuredRows("排除标准", ["已知激素依赖性肿瘤史", "筛查前3个月内使用过研究相关激素治疗"]);
  // 干预组
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '干预措施'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 400));
  await evaluate(cdp, setByLabelText("试验药物干预概述", `${PRODUCT} 20mg与40mg两个剂量组，每日一次口服。`, "textarea"));
  await evaluate(cdp, setByLabelText("试验药物常规用法用量", "每日一次口服20mg或40mg，连续12周。", "textarea"));
  await addStructuredRows("背景治疗", ["稳定剂量甲状腺激素替代治疗"]);
  await addStructuredRows("允许使用", ["对乙酰氨基酚（≤2g/日）"]);
  await addStructuredRows("限制/禁止", ["研究期间禁止使用任何激素类潮热治疗"]);
  // 对照组
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '对照'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 400));
  await evaluate(cdp, setByLabelText("对照", "匹配安慰剂，每日一次口服，连续12周。", "textarea"));
  // 结局指标组
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '结局指标'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 400));
  await evaluate(cdp, setByLabelText("主要终点", "第12周每周中重度潮热频率较基线变化。", "textarea"));
  await evaluate(cdp, setByLabelText("安全性终点", "TEAE、SAE及导致停药的AE发生率", "textarea"));
  // 执行与统计组
  await evaluate(cdp, `(() => { const t = Array.from(document.querySelectorAll('.authoring-group-tabs button')).find(b => b.textContent.trim() === '执行与统计'); t && t.click(); return true; })()`);
  await new Promise((r) => setTimeout(r, 400));
  await evaluate(cdp, setByLabelText("研究时期", "筛选期（最多4周）\n双盲治疗期（12周）", "textarea"));
  await evaluate(cdp, setByLabelText("访视策略", "筛选、基线，治疗期每4周访视，末次给药后4周安全性随访。", "textarea"));
  await evaluate(cdp, setByLabelText("估计目标", "治疗策略估计目标下第12周潮热频率差异。", "textarea"));
  await evaluate(cdp, setByLabelText("样本量策略", "基于预期潮热频率差异、双侧0.05与80%把握度估算，约120例。", "textarea"));
  await evaluate(cdp, setByLabelText("统计分析策略", "主要终点采用MMRM分析并进行多重性控制。", "textarea"));
  await shot(cdp, "chain_05_picos_filled.png");
  let picosDiag = await evaluate(cdp, `(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第二步"));
    return { disabled: btn?.disabled ?? null, title: btn?.title || "" };
  })()`);
  step("picos button diag", JSON.stringify(picosDiag));
  for (let attempt = 1; attempt <= 20 && picosDiag.disabled && String(picosDiag.title || "").includes("正在处理中"); attempt++) {
    await new Promise((r) => setTimeout(r, 3000));
    picosDiag = await evaluate(cdp, `(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第二步"));
      return { disabled: btn?.disabled ?? null, title: btn?.title || "" };
    })()`);
  }
  step("picos button diag settled", JSON.stringify(picosDiag));
  // 冻结提示指向「竞品处理抽屉取消本次流水线」：按界面指引取消后再提交
  if (picosDiag.disabled && String(picosDiag.title || "").includes("取消本次流水线")) {
    await evaluate(cdp, `(() => { const d = document.querySelector('.authoring-research-progress-details'); if (d && !d.open) { const s = d.querySelector('summary'); s && s.click(); } return true; })()`);
    await new Promise((r) => setTimeout(r, 500));
    await evaluate(cdp, clickButton("取消研究流水线"));
    await new Promise((r) => setTimeout(r, 4000));
    for (let attempt = 1; attempt <= 15; attempt++) {
      picosDiag = await evaluate(cdp, `(() => {
        const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第二步"));
        return { disabled: btn?.disabled ?? null, title: btn?.title || "" };
      })()`);
      if (!picosDiag.disabled) break;
      await new Promise((r) => setTimeout(r, 3000));
    }
    step("picos button diag after cancel", JSON.stringify(picosDiag));
  }
  // 取消流水线会使第一步回到草稿态：按界面提示回第一步重新完成
  for (let round = 0; round < 3; round++) {
    picosDiag = await evaluate(cdp, `(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第二步"));
      return { disabled: btn?.disabled ?? null, title: btn?.title || "" };
    })()`);
    if (!picosDiag.disabled) break;
    if (String(picosDiag.title || "").includes("完成第一步")) {
      step("step1 back to draft, re-completing", `round=${round}`);
      await evaluate(cdp, `(() => {
        const tab = Array.from(document.querySelectorAll('.authoring-stage-strip button')).find(b => b.textContent.includes('研究框架'));
        if (tab && !tab.disabled) { tab.click(); return true; }
        return false;
      })()`);
      await new Promise((r) => setTimeout(r, 1200));
      await evaluate(cdp, clickButton("完成第一步"));
      await waitFor(cdp, `Boolean(document.querySelector('.authoring-impact-panel')) || Array.from(document.querySelectorAll('.authoring-stage-strip button'))[0]?.className.includes('done') || document.body.textContent.includes("暂不能保存研究框架")`, 45000, "reframe response");
      if (await evaluate(cdp, `Boolean(document.querySelector('.authoring-impact-panel'))`)) {
        await confirmImpactPanel("reframe");
      }
      // 再次冻结则再取消一次流水线
      const refreeze = await evaluate(cdp, `(() => {
        const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第二步"));
        return { disabled: btn?.disabled ?? null, title: btn?.title || "" };
      })()`);
      if (refreeze.disabled && String(refreeze.title || "").includes("取消本次流水线")) {
        await evaluate(cdp, `(() => { const d = document.querySelector('.authoring-research-progress-details'); if (d && !d.open) { const s = d.querySelector('summary'); s && s.click(); } return true; })()`);
        await evaluate(cdp, clickButton("取消研究流水线"));
        await new Promise((r) => setTimeout(r, 4000));
      }
      await evaluate(cdp, `(() => {
        const tab = Array.from(document.querySelectorAll('.authoring-stage-strip button')).find(b => b.textContent.includes('PICOS设计'));
        if (tab && !tab.disabled) { tab.click(); return true; }
        return false;
      })()`);
      await new Promise((r) => setTimeout(r, 1200));
      continue;
    }
    break;
  }
  const waitCommitEnabled = async (label) => {
    for (let attempt = 1; attempt <= 20; attempt++) {
      const diag = await evaluate(cdp, `(() => {
        const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.includes("完成第二步"));
        return { disabled: btn?.disabled ?? null };
      })()`);
      if (!diag.disabled) return true;
      await new Promise((r) => setTimeout(r, 2000));
    }
    step("commit button still disabled", label);
    return false;
  };
  for (let commitRound = 1; commitRound <= 3; commitRound++) {
    if (await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className.includes('done')`)) break;
    step("picos commit round", `round=${commitRound}`);
  await evaluate(cdp, clickButton("完成第二步"));
  // PICOS 提交同样可能撞上流水线推进的 stale：保存草稿刷新后重试
  for (let attempt = 1; attempt <= 3; attempt++) {
    const msg = await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-journey-message')).map((el) => el.textContent).join("|")`);
    if (!String(msg).includes("stale authoring journey revision")) break;
    step("picos stale, saving draft to refresh", `attempt=${attempt}`);
    await evaluate(cdp, clickButton("保存草稿"));
    await waitCommitEnabled(`after draft save ${attempt}`);
    await evaluate(cdp, clickButton("完成第二步"));
    await new Promise((r) => setTimeout(r, 2500));
  }
  step("picos final diag", JSON.stringify(await evaluate(cdp, `({
    impact: Boolean(document.querySelector('.authoring-impact-panel')),
    strip1: Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className,
    msg: Array.from(document.querySelectorAll('.authoring-journey-message')).map((el) => el.textContent.trim().slice(0, 140)),
    btn: (() => { const b = Array.from(document.querySelectorAll("button")).find((x) => x.textContent.includes("完成第二步")); return { disabled: b?.disabled, title: (b?.title || "").slice(0, 120) }; })(),
    fieldsetDisabled: document.querySelector('.authoring-journey-fieldset')?.disabled ?? null,
  })`)));
  await waitFor(cdp, `Boolean(document.querySelector('.authoring-impact-panel')) || Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className.includes('done')`, 45000, "picos commit response").catch(async () => {
    step("picos commit timeout diag", JSON.stringify(await evaluate(cdp, `({
      impact: Boolean(document.querySelector('.authoring-impact-panel')),
      strip1: Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className,
      msg: Array.from(document.querySelectorAll('.authoring-journey-message')).map((el) => el.textContent.trim().slice(0, 140)),
      btn: (() => { const b = Array.from(document.querySelectorAll("button")).find((x) => x.textContent.includes("完成第二步")); return { disabled: b?.disabled, title: (b?.title || "").slice(0, 160) }; })(),
    })`)));
    throw new Error("picos commit did not land");
  });
  if (await evaluate(cdp, `Boolean(document.querySelector('.authoring-impact-panel'))`)) {
    await shot(cdp, "chain_06_impact_picos.png");
    await confirmImpactPanel("picos");
  }
  await waitFor(cdp, `Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className.includes('done')`, 45000, "picos strip done").catch(() => step("picos strip not done this round"));
  if (await evaluate(cdp, `Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className.includes('done')`)) {
    await shot(cdp, "chain_07_picos_committed.png");
    step("picos committed");
  }
  }
  await waitFor(cdp, `Array.from(document.querySelectorAll('.authoring-stage-strip button'))[1]?.className.includes('done')`, 60000, "picos strip done final");
  await shot(cdp, "chain_07_picos_committed.png");
  step("picos committed");

  // 4) 语料准备：例外进入写作
  await waitFor(cdp, `document.body.textContent.includes('语料准备') || document.body.textContent.includes('准入条件')`, 30000, "corpus stage", );
  await new Promise((r) => setTimeout(r, 1500));
  await shot(cdp, "chain_08_corpus.png");
  // 展开例外放行抽屉（details 默认收起）
  await evaluate(cdp, `(() => {
    const d = document.querySelector('.authoring-override');
    if (d && !d.open) { const s = d.querySelector('summary'); s && s.click(); }
    return true;
  })()`);
  // 逐项勾选全部缺口
  await evaluate(cdp, `(() => {
    const boxes = Array.from(document.querySelectorAll('.authoring-gate-checklist input[type="checkbox"]')).filter((b) => !b.disabled && !b.checked);
    boxes.forEach((b) => b.click());
    return boxes.length;
  })()`);
  await evaluate(cdp, `(() => {
    const area = Array.from(document.querySelectorAll('textarea')).find((t) => (t.placeholder || '').includes('例外') || (t.previousElementSibling?.textContent || '').includes('例外'));
    if (!area) return 'no-reason-box';
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(area, '竞品语料暂不可得，医学经理确认先以既有研究事实建稿。');
    area.dispatchEvent(new Event('input', { bubbles: true }));
    return 'ok';
  })()`);
  await shot(cdp, "chain_09_override_filled.png");
  await evaluate(cdp, clickButton("确认例外并放行"));
  await new Promise((r) => setTimeout(r, 3000));
  step("override click diag", JSON.stringify(await evaluate(cdp, `({
    overrideDetailsOpen: document.querySelector('.authoring-override')?.open ?? null,
    overrideBtn: (() => { const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent.includes('确认例外并放行')); return b ? { disabled: b.disabled, title: (b.title || '').slice(0, 80) } : 'gone'; })(),
    msg: Array.from(document.querySelectorAll('.authoring-journey-message')).map((el) => el.textContent.trim().slice(0, 120)),
    gateText: (document.querySelector('.authoring-gate-checklist')?.textContent || '').slice(0, 200),
  })`)));
  await waitFor(cdp, textPresent("已记录医学例外放行") || textPresent("进入写作平台"), 60000, "override granted");
  await shot(cdp, "chain_10_override_granted.png");
  step("corpus override granted");

  // 5) 进入写作平台 → 建立工作稿
  await evaluate(cdp, clickButton("进入写作平台"));
  await new Promise((r) => setTimeout(r, 3000));
  await shot(cdp, "chain_11_after_enter_writing.png");
  const failure = await evaluate(cdp, `document.body.textContent.includes('建立工作稿失败')`);
  const blockersListed = await evaluate(cdp, `Boolean(document.querySelector('[data-testid="authoring-blocker-guidance"]'))`);
  if (failure) {
    step("assembly FAILED", `blocker-guidance-shown=${blockersListed}`);
    await shot(cdp, "chain_12_assembly_failed.png");
  } else {
    await waitFor(cdp, `!document.body.textContent.includes('建立工作稿失败') && (document.body.textContent.includes('工作副本') || document.body.textContent.includes('写作平台') || document.body.textContent.includes('章节'))`, 120000, "document created");
    await shot(cdp, "chain_12_document_created.png");
    step("document created OK");
  }

  const finalState = await evaluate(cdp, `({
    failure: document.body.textContent.includes('建立工作稿失败'),
    blockerGuidance: Boolean(document.querySelector('[data-testid="authoring-blocker-guidance"]')),
    bodySnippet: document.body.textContent.slice(0, 400),
  })`);
  await writeFile(path.join(OUT_DIR, "full_chain_result.json"), JSON.stringify({ trace, finalState, product: PRODUCT, indication: INDICATION }, null, 2));
  console.log(JSON.stringify({ trace, finalState }, null, 2));
} finally {
  if (cdp) cdp.close();
  chrome.kill();
}
