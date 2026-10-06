import { describe, expect, test } from 'vitest';
import {
  medicalWritingSafeErrorText,
  medicalWritingDiagnosticRef,
  redactDiagnosticText,
} from './errorContract.mjs';

// 0926V1 G7 / A701: 默认文案使用受控状态/错误码，不以黑名单“不命中即原样输出”。
// 反例先证失败（0927V1）：product_ai_provider_transient / failed_retryable /
// network 及未知工程文本都必须落到受控中文，不允许英文错误码漏给用户。
describe('A701 受控状态/错误码合同', () => {
  test.each([
    ['product_ai_provider_transient: APIConnectionError(max retries exceeded)'],
    ['failed_retryable: chunk 3 download failed'],
    ['network: URLError connection reset by peer'],
  ])('错误码 %j 输出受控安全中文，不漏英文原文', (raw) => {
    const shown = medicalWritingSafeErrorText({ message: raw });
    expect(shown).toMatch(/[\u3400-\u9fff]/);
    expect(shown).not.toContain('product_ai_provider_transient');
    expect(shown).not.toContain('failed_retryable');
    expect(shown).not.toBe(raw);
  });

  test('未知非中文错误回落受控默认文案，不原样透传', () => {
    const raw = 'X-Internal segfault stage=mwq_7 batch=deadbeef';
    const shown = medicalWritingSafeErrorText({ message: raw });
    expect(shown).toMatch(/[\u3400-\u9fff]/);
    expect(shown).not.toBe(raw);
  });

  test('自家中文业务消息仍原样保留（正向：来自后端合同的文案）', () => {
    const raw = '本次资料尚未冻结，请先确认来源版本。';
    expect(medicalWritingSafeErrorText({ message: raw })).toBe(raw);
  });
});

// 0926V1 G7 / A702: 超时不得无证据称“任务仍在后台”。
describe('NEW-P0-25批三A：FastAPI 422原始JSON人话化（R2现场string_too_short数组直出）', () => {
  test('校验错误数组输出受控中文，不漏内部字段名', () => {
    const raw = JSON.stringify([
      { type: 'string_too_short', loc: ['body', 'idempotency_key'], msg: 'String should have at least 8 characters' },
    ]);
    const shown = medicalWritingSafeErrorText({ message: raw });
    expect(shown).toMatch(/[\u3400-\u9fff]/);
    expect(shown).not.toContain('string_too_short');
    expect(shown).not.toContain('idempotency_key');
    expect(shown).toContain('系统内部校验未通过');
  });

  test('单条pydantic错误对象同样人话化', () => {
    const raw = "[{'type': 'missing', 'loc': ['body', 'indication'], 'msg': 'Field required'}]";
    const shown = medicalWritingSafeErrorText({ message: raw });
    expect(shown).toContain('系统内部校验未通过');
    expect(shown).toMatch(/[\u3400-\u9fff]/);
  });
});

// R6 片B′（P0-25）现场（r6-D report.md:175）：全文初稿失败消息把
// `full_draft.sections[0] contains unexpected key: rationale_note`、
// `ValueError: 草稿导出含 74 处【待补齐】`、`chunk 0` 等工程串直接
// 摆进用户界面。契约：含这些工程痕迹的混合中文消息必须整体替换为
// 受控中文，不得因“以中文开头/含中文”而原样透传。
describe('R6 片B′：全文初稿工程串不得透传到用户消息', () => {
  test.each([
    ['独立AI全文初稿未通过校验：full_draft.sections[0] contains unexpected key: rationale_note; full_draft.sections[1] contains unexpected key: rationale_note'],
    ['全文初稿续跑失败：artifact chunk 0 locator missing'],
    ['AI provider request failed after bounded retries: HTTP 507'],
  ])('工程痕迹消息 %j 输出受控中文', (raw) => {
    const shown = medicalWritingSafeErrorText({ message: raw });
    expect(shown).toMatch(/[\u3400-\u9fff]/);
    expect(shown).not.toMatch(/full_draft\.sections|unexpected key|rationale_note|ValueError|chunk 0|HTTP 507/);
  });

  test('ValueError 前缀只剥前缀，中文合同正文保留（译文管线现场）', () => {
    const shown = medicalWritingSafeErrorText({ message: 'ValueError: 译文管线暂时不可用' });
    expect(shown).toContain('译文管线暂时不可用');
    expect(shown).not.toContain('ValueError');
  });

  test('草稿导出占位提示剥前缀后仍是用户可读中文', () => {
    const shown = medicalWritingSafeErrorText({ message: 'ValueError: 草稿导出含 74 处【待补齐】占位或测试标记' });
    expect(shown).not.toContain('ValueError');
    expect(shown).toContain('【待补齐】');
  });
});

describe('A702 超时与后台声明', () => {
  test('超时且job状态未知：不声称仍在后台', () => {
    const shown = medicalWritingSafeErrorText({ message: 'Request timed out after 30000 ms' });
    expect(shown).toMatch(/[\u3400-\u9fff]/);
    expect(shown).not.toMatch(/仍在后台|后台执行|后台运行/);
  });

  test('超时且job确认仍在运行：才可告知后台进行', () => {
    const shown = medicalWritingSafeErrorText(
      { message: 'Request timed out after 30000 ms' },
      { jobState: 'confirmed_running' },
    );
    expect(shown).toMatch(/后台/);
    expect(shown).toMatch(/[\u3400-\u9fff]/);
  });
});

// 0926V1 G7 / A701: 诊断按权限脱敏展开——展开是显式动作，内容须先脱敏。
describe('诊断脱敏展开', () => {
  test('诊断ref保留技术信息供显式展开（任何非空错误都可诊断）', () => {
    const raw = 'product_ai_provider_transient: Traceback KeyError: stage_run_id';
    expect(medicalWritingDiagnosticRef({ message: raw })).toBe(raw);
    expect(medicalWritingDiagnosticRef({ message: 'plain failure' })).toBe('plain failure');
    expect(medicalWritingDiagnosticRef({ message: '' })).toBe('');
  });

  test('redactDiagnosticText抹去URL主机/凭证/邮箱', () => {
    const raw = 'POST http://10.1.2.3:8001/v1/chat failed api_key=sk-secret123 '
      + 'Authorization: Bearer abc.def.ghi contact guest@kangzhe.com';
    const out = redactDiagnosticText(raw);
    expect(out).not.toContain('10.1.2.3');
    expect(out).not.toContain('sk-secret123');
    expect(out).not.toContain('abc.def.ghi');
    expect(out).not.toContain('guest@kangzhe.com');
    expect(out).toContain('api_key=');
    expect(out).toContain('http://***');
  });
});
