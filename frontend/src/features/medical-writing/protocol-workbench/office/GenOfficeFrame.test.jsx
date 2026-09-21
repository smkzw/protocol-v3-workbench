import React from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GenOfficeFrame } from './GenOfficeFrame';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const savedDocument = { document: { revision: 3, study_definition_sha256: 'b'.repeat(64) }, document_sha256: 'a'.repeat(64) };
test('saved Office head drives download; save receipt changes download without remounting editor', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  const api = { latestOfficeSnapshot: vi.fn(async () => ({ operation_id: 'old', artifact_revision: 1, study_revision_sha256: 'c'.repeat(64) })) };
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" actorId="a" savedDocument={savedDocument} api={api}/>);
  expect((await screen.findByText('下载当前 Word 工作稿')).getAttribute('href')).toContain('/old/content');
  const frame = await screen.findByTitle('GenOffice文档编辑器');
  const src = frame.getAttribute('src');
  expect(new URL(src, location.origin).searchParams.get('openedStudySha')).toBe('c'.repeat(64));
  window.dispatchEvent(new MessageEvent('message', { origin: location.origin, source: frame.contentWindow,
    data: { type: 'protocol-office:saved', receipt: { operation_id: 'new', artifact_revision: 2 } } }));
  await waitFor(() => expect(screen.getByText('下载当前 Word 工作稿').getAttribute('href')).toContain('/new/content'));
  expect(screen.getByTitle('GenOffice文档编辑器')).toBe(frame);
  expect(frame.getAttribute('src')).toBe(src);
});
test('unavailable current head does not silently offer an older semantic export', async () => {
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" savedDocument={savedDocument}
    api={{ latestOfficeSnapshot: async () => { throw { status: 503 }; } }}/>);
  await screen.findByText('暂时无法读取已保存工作稿，请重新打开页面后再试。');
  expect(screen.queryByText('下载当前 Word 工作稿')).toBeNull();
  expect(screen.getByText('打开文档编辑器').disabled).toBe(true);
});
test('no Office snapshot permits the initial document', async () => {
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" savedDocument={savedDocument}
    api={{ latestOfficeSnapshot: async () => { throw { status: 404 }; } }}/>);
  expect((await screen.findByText('下载当前 Word 工作稿')).getAttribute('href')).toContain('/candidate/docx');
});

test('a newer generated candidate needs an explicit choice before replacing the current Word', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  const api={latestOfficeSnapshot:async()=>({operation_id:'previous-word',artifact_revision:7,document_revision:2,study_revision_sha256:'c'.repeat(64)})};
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" savedDocument={savedDocument} api={api}/>);
  await screen.findByText(/本次新起草候选尚未替换现有工作稿/);
  expect(screen.queryByTitle('GenOffice文档编辑器')).toBeNull();
  expect(screen.getByText('下载当前 Word 工作稿').getAttribute('href')).toContain('/previous-word/content');
  fireEvent.click(screen.getByText('编辑本次新起草候选'));
  const frame=await screen.findByTitle('GenOffice文档编辑器');
  const query=new URL(frame.getAttribute('src'),location.origin).searchParams;
  expect(query.get('docUrl')).toContain('/candidate/docx');
  expect(query.get('baseArtifactRevision')).toBe('7');
  expect(query.get('openedStudySha')).toBe('b'.repeat(64));
});
test('actual renderer dirty state reaches the existing application navigation guard', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  const onNavigationGuardChange=vi.fn();
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" savedDocument={savedDocument}
    api={{latestOfficeSnapshot:async()=>({operation_id:'saved',artifact_revision:1})}}
    onNavigationGuardChange={onNavigationGuardChange}/>);
  const frame=await screen.findByTitle('GenOffice文档编辑器');
  window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame.contentWindow,data:{type:'protocol-office:dirty',dirty:true}}));
  await waitFor(()=>expect(onNavigationGuardChange).toHaveBeenLastCalledWith(expect.objectContaining({dirty:true})));
  window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:frame.contentWindow,data:{type:'protocol-office:dirty',dirty:false}}));
  await waitFor(()=>expect(onNavigationGuardChange).toHaveBeenLastCalledWith(null));
});

test('a new candidate does not prevent explicitly continuing the existing Word and its study binding', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  const api={latestOfficeSnapshot:async()=>({operation_id:'previous-word',artifact_revision:7,document_revision:2,study_revision_sha256:'c'.repeat(64)})};
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" savedDocument={savedDocument} api={api}/>);
  fireEvent.click(await screen.findByText('继续编辑已保存的 Word'));
  const frame=await screen.findByTitle('GenOffice文档编辑器');
  const query=new URL(frame.getAttribute('src'),location.origin).searchParams;
  expect(query.get('docUrl')).toContain('/previous-word/content');
  expect(query.get('openedStudySha')).toBe('c'.repeat(64));
  expect(query.get('baseArtifactRevision')).toBe('7');
  expect(screen.getByText('下载当前 Word 工作稿').getAttribute('href')).toContain('/previous-word/content');
});

test('Word version history offers original snapshot downloads without replacing the open editor', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
  const versions=[{operation_id:'second',artifact_revision:2,saved_at:'2026-09-21T02:00:00Z'},{operation_id:'first',artifact_revision:1,saved_at:'2026-09-21T01:00:00Z'}];
  const api={latestOfficeSnapshot:async()=>versions[0],officeSnapshotHistory:vi.fn(async()=>({snapshots:versions}))};
  render(<GenOfficeFrame projectId="p" studyDefinitionId="s" savedDocument={savedDocument} api={api}/>);
  const frame=await screen.findByTitle('GenOffice文档编辑器');
  fireEvent.click(screen.getByText('Word 版本记录'));
  expect((await screen.findByText('下载第 1 版')).getAttribute('href')).toContain('/first/content');
  expect(screen.getByText('下载当前 Word 工作稿').getAttribute('href')).toContain('/second/content');
  expect(screen.getByTitle('GenOffice文档编辑器')).toBe(frame);
});
