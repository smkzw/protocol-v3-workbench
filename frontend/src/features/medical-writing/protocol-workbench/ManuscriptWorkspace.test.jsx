import React from 'react';
import { afterEach, expect, test, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ManuscriptWorkspace } from './ManuscriptWorkspace';
afterEach(()=>{ cleanup(); localStorage.clear(); vi.useRealTimers(); });
test('a completed new draft is not silently replaced by another saved study draft', async () => {
  localStorage.setItem('protocol-v3:manuscript:'+JSON.stringify(['p','s','seed']), JSON.stringify({
    phase:'draft', studySha:'new-study', intent:{expected_workflow_run_id:'new-run'}, sourceRunId:'sources'
  }));
  const api={
    recoverManuscriptDraft:vi.fn(async()=>({workflow_run_id:'new-run',status:'completed',complete_candidate:true,chapters:[]})),
    getSavedManuscriptDocument:vi.fn(async()=>({document:{revision:1},document_sha256:'old'}))
  };
  render(<ManuscriptWorkspace projectId="p" studyDefinitionId="s" seedRunId="seed" actorId="a" api={api}/>);
  await screen.findByText('保存完整初稿');
  expect(api.getSavedManuscriptDocument).not.toHaveBeenCalled();
  expect(screen.queryByTitle('GenOffice文档编辑器')).toBeNull();
});

test('continue reconciles the original run then explicitly resumes it, without starting a replacement', async () => {
  const { fireEvent, waitFor } = await import('@testing-library/react');
  const intent={expected_workflow_run_id:'existing-run',source_run_id:'sources'};
  localStorage.setItem('protocol-v3:manuscript:'+JSON.stringify(['p','s','seed']),JSON.stringify({phase:'draft',studySha:'sha',intent}));
  const api={
    recoverManuscriptDraft:vi.fn(async()=>({workflow_run_id:'existing-run',status:'blocked',can_resume:true,chapters:[]})),
    resumeManuscriptDraft:vi.fn(async()=>({workflow_run_id:'existing-run',status:'running'})),
    startManuscriptDraft:vi.fn()
  };
  render(<ManuscriptWorkspace projectId="p" studyDefinitionId="s" seedRunId="seed" actorId="a" api={api}/>);
  fireEvent.click(await screen.findByText('继续写作（重试未完成的章节）'));
  await waitFor(()=>expect(api.resumeManuscriptDraft).toHaveBeenCalledWith('p','s',intent,expect.any(Object)));
  expect(api.startManuscriptDraft).not.toHaveBeenCalled();
  expect(api.recoverManuscriptDraft.mock.calls.length).toBeGreaterThanOrEqual(2);
});

test('an unresolved running operation is only reconciled and never redispatched', async () => {
  const { fireEvent, waitFor } = await import('@testing-library/react');
  localStorage.setItem('protocol-v3:manuscript:'+JSON.stringify(['p','s','seed']),JSON.stringify({phase:'draft',intent:{expected_workflow_run_id:'unknown-run'}}));
  const api={
    recoverManuscriptDraft:vi.fn(async()=>({workflow_run_id:'unknown-run',status:'blocked',can_resume:false,chapters:[]})),
    resumeManuscriptDraft:vi.fn(),startManuscriptDraft:vi.fn()
  };
  render(<ManuscriptWorkspace projectId="p" studyDefinitionId="s" seedRunId="seed" actorId="a" api={api}/>);
  fireEvent.click(await screen.findByText('核对未完成章节的状态'));
  await waitFor(()=>expect(api.recoverManuscriptDraft.mock.calls.length).toBeGreaterThanOrEqual(2));
  expect(api.resumeManuscriptDraft).not.toHaveBeenCalled();
  expect(api.startManuscriptDraft).not.toHaveBeenCalled();
});


test('partial blockage continues to observe progressing siblings without redispatching', async () => {
  const { act } = await import('@testing-library/react');
  vi.useFakeTimers();
  localStorage.setItem('protocol-v3:manuscript:'+JSON.stringify(['p','s','seed']),JSON.stringify({phase:'draft',intent:{expected_workflow_run_id:'partial'}}));
  const api={recoverManuscriptDraft:vi.fn()
    .mockResolvedValueOnce({workflow_run_id:'partial',status:'blocked',can_resume:true,chapters:[]})
    .mockResolvedValue({workflow_run_id:'partial',status:'blocked',can_resume:false,chapters:[]}),
    resumeManuscriptDraft:vi.fn()};
  await act(async()=>{render(<ManuscriptWorkspace projectId="p" studyDefinitionId="s" seedRunId="seed" actorId="a" api={api}/>);});
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(api.recoverManuscriptDraft).toHaveBeenCalledTimes(2);
  await act(async()=>{await vi.advanceTimersByTimeAsync(30000);});
  expect(api.recoverManuscriptDraft).toHaveBeenCalledTimes(2);
  expect(api.resumeManuscriptDraft).not.toHaveBeenCalled();
});
