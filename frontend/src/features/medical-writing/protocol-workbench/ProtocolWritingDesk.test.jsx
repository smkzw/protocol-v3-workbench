import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ProtocolWritingDesk } from './ProtocolWritingDesk';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

const savedDocument = {
  document: { revision: 3, study_definition_sha256: 'b'.repeat(64) },
  document_sha256: 'a'.repeat(64),
  revision: 3,
};

function stubApi() {
  return {
    getSavedManuscriptDocument: vi.fn(async () => savedDocument),
    getDurableMedicalWritingJob: vi.fn(async () => ({ status: 'completed', can_resume: false })),
    getFullDraftSourcePolicy: vi.fn(async () => ({ status: 'not_required', current: true })),
    latestOfficeSnapshot: vi.fn(async () => {
      const error = new Error('no snapshot'); error.status = 404; throw error;
    }),
  };
}

async function openDeskWithOffice() {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  const api = stubApi();
  render(<ProtocolWritingDesk bridgeMode projectId="p" studyDefinitionId="s" actorId="a"
    api={api} onNavigationGuardChange={() => {}} />);
  fireEvent.click(await screen.findByText('打开工作稿'));
  const iframe = await screen.findByTitle('GenOffice文档编辑器');
  return { api, iframe };
}

// 0926V1 A704: 右栏交互（宽审阅开/关）不得重建 Office iframe，src 冻结，
// dirty 会话状态原样保留。
test('A704: 开/关右栏宽审阅不重建Office iframe、src不变', async () => {
  const { iframe } = await openDeskWithOffice();
  const src = iframe.getAttribute('src');
  fireEvent.click(await screen.findByRole('button', { name: /宽审阅：研究比较/ }));
  expect(screen.getByTitle('GenOffice文档编辑器')).toBe(iframe);
  fireEvent.click(await screen.findByRole('button', { name: /退出宽审阅/ }));
  expect(screen.getByTitle('GenOffice文档编辑器')).toBe(iframe);
  expect(iframe.getAttribute('src')).toBe(src);
});

// 0926V1 A704: savedDocument 在编辑器打开期间刷新只更新外层展示（既有 F03
// 行为），宽审阅开关叠加其上仍不得重建。
test('A704: 宽审阅开关叠加savedDocument刷新，iframe仍不重建', async () => {
  const { api } = await openDeskWithOffice();
  const iframe = screen.getByTitle('GenOffice文档编辑器');
  fireEvent.click(await screen.findByRole('button', { name: /宽审阅：研究比较/ }));
  api.getSavedManuscriptDocument.mockResolvedValueOnce(savedDocument);
  fireEvent.click(await screen.findByRole('button', { name: /退出宽审阅/ }));
  await waitFor(() => expect(screen.getByTitle('GenOffice文档编辑器')).toBe(iframe));
});

// 0926V1 G7: 布局=文档主画布在前，右栏是“任务与摘要”；右栏可进入宽审阅。
test('布局: 文档画布在前、右栏为任务与摘要并带宽审阅入口', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  render(<ProtocolWritingDesk bridgeMode projectId="p" studyDefinitionId="s" actorId="a"
    api={stubApi()} onNavigationGuardChange={() => {}} />);
  const desk = await screen.findByRole('region', { name: /研究方案工作稿|完整方案初稿/ })
    .then((node) => node.closest('.pvi-writing-desk'));
  const documentPane = desk.querySelector('.pvi-document-pane');
  const rail = desk.querySelector('.pvi-design-pane');
  expect(rail.getAttribute('aria-label')).toContain('任务与摘要');
  // document pane must precede the rail in DOM (document canvas first).
  expect(documentPane.compareDocumentPosition(rail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole('button', { name: /宽审阅：研究比较/ })).toBeTruthy();
});

// 0926V1 A703/A704: 宽审阅开启时右栏容器获得宽审阅态（1440/1920/2560 的
// 实际宽度行为由浏览器实测留证，这里钉住类切换合同）。
test('宽审阅态: 开启后desk带pvi-wide-review类，可退出', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  render(<ProtocolWritingDesk bridgeMode projectId="p" studyDefinitionId="s" actorId="a"
    api={stubApi()} onNavigationGuardChange={() => {}} />);
  await screen.findByText('打开工作稿');
  const desk = screen.getByText('打开工作稿').closest('.pvi-writing-desk');
  expect(desk.className).not.toContain('pvi-wide-review');
  fireEvent.click(screen.getByRole('button', { name: /宽审阅：研究比较/ }));
  expect(desk.className).toContain('pvi-wide-review');
  fireEvent.click(screen.getByRole('button', { name: /退出宽审阅/ }));
  expect(desk.className).not.toContain('pvi-wide-review');
});
