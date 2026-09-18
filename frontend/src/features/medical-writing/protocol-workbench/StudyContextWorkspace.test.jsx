import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { StudyContextWorkspace } from './StudyContextWorkspace';
afterEach(()=>{cleanup();localStorage.clear();});
const props={projectId:'project:one',seedRunId:'seed:one',actorId:'medical_manager'};
const study={study_definition_id:'study:one',revision:1,revision_sha256:'a'.repeat(64),matches_selected_inputs:true,input_context:{user_brief:'当前写作说明'}};
const receipt={project_id:props.projectId,study_definition_id:study.study_definition_id,revision:1,revision_sha256:study.revision_sha256,
  definition:{project_id:props.projectId,study_definition_id:study.study_definition_id,revision:1},effective_decision:{decision_record_id:'decision:one'}};

it('records the writing request before enabling design, without sending medical values',async()=>{
  const api={listResearchStudies:vi.fn().mockResolvedValueOnce({studies:[]}).mockResolvedValue({studies:[study]}),
    createResearchContext:vi.fn(async()=>receipt)};
  render(<StudyContextWorkspace {...props} api={api}/>);
  fireEvent.click(await screen.findByRole('button',{name:'开始本次方案写作'}));
  await screen.findByRole('button',{name:'整理完整给药建议'});
  expect(api.createResearchContext).toHaveBeenCalledTimes(1);
  expect(Object.keys(api.createResearchContext.mock.calls[0][1]).sort()).toEqual(['actor_id','decided_at','operation_id','seed_run_id']);
});

it('recovers a lost acknowledgement on reopening instead of creating again',async()=>{
  const api={listResearchStudies:vi.fn().mockResolvedValueOnce({studies:[]}).mockResolvedValue({studies:[study]}),
    createResearchContext:vi.fn(async()=>{throw new Error('连接中断');}),recoverResearchContext:vi.fn(async()=>receipt)};
  const view=render(<StudyContextWorkspace {...props} api={api}/>);
  fireEvent.click(await screen.findByRole('button',{name:'开始本次方案写作'}));
  await screen.findByRole('button',{name:'核对本次保存'});
  view.unmount();render(<StudyContextWorkspace {...props} api={api}/>);
  await screen.findByRole('button',{name:'整理完整给药建议'});
  expect(api.createResearchContext).toHaveBeenCalledTimes(1);
  expect(api.recoverResearchContext.mock.calls[0][1]).toEqual(api.createResearchContext.mock.calls[0][1]);
});

it('requires an explicit input update and uses the selected study revision',async()=>{
  const api={listResearchStudies:vi.fn().mockResolvedValueOnce({studies:[{...study,matches_selected_inputs:false}]}).mockResolvedValue({studies:[{...study,revision:2}]}),
    updateResearchInputs:vi.fn(async()=>({...receipt,revision:2,definition:{...receipt.definition,revision:2}}))};
  render(<StudyContextWorkspace {...props} api={api}/>);
  fireEvent.click(await screen.findByRole('button',{name:'使用本次资料继续'}));
  await screen.findByRole('button',{name:'整理完整给药建议'});
  const call=api.updateResearchInputs.mock.calls[0];
  expect(call[1]).toBe(study.study_definition_id);
  expect(call[2].expected_revision).toBe(1);
  expect(call[2].snapshot_sha256).toBe(study.revision_sha256);
});

it('does not enable creation when the existing-study lookup failed',async()=>{
  const api={listResearchStudies:vi.fn(async()=>{throw new Error('读取失败');}),createResearchContext:vi.fn()};
  render(<StudyContextWorkspace {...props} api={api}/>);
  await screen.findByText('读取失败');
  expect(screen.getByRole('button',{name:'开始本次方案写作'}).disabled).toBe(true);
  expect(api.createResearchContext).not.toHaveBeenCalled();
});
