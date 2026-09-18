import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {ResearchInformationCard} from './ResearchInformationCard';
afterEach(()=>{cleanup();localStorage.clear();});
const props={projectId:'project:one',studyDefinitionId:'study:one',seedRunId:'seed:one',actorId:'user:one',
 proposal:{fields:{research_drug:[{candidate:'合成药X',reason:'来自说明'}],clinical_phase:[{candidate:'Ⅱ期'},{candidate:'Ⅲ期'}],
 anticipated_dose:[{candidate:'不应在此采用'}]}}};
const current={definition:{project_id:'project:one',study_definition_id:'study:one',revision:1,facts:{}},revision_sha256:'a'.repeat(64)};
const receipt={project_id:'project:one',study_definition_id:'study:one',revision:2,revision_sha256:'b'.repeat(64),
 definition:{project_id:'project:one',study_definition_id:'study:one',revision:2},effective_decision:{decision_record_id:'decision:one'}};
it('preselects suggestions and submits only explicit indices with the original study version',async()=>{
 const api={getStudyDefinition:vi.fn(async()=>current),adoptResearchInformation:vi.fn(async()=>receipt),recoverResearchInformation:vi.fn(async()=>receipt)};
 const view=render(<ResearchInformationCard {...props} api={api}/>);
 const button=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(button.disabled).toBe(false));
 expect(screen.queryByText('不应在此采用')).toBeNull();
 expect(screen.getByLabelText('研究期别').value).toBe('0');
 fireEvent.change(screen.getByLabelText('研究期别'),{target:{value:'1'}});
 fireEvent.click(button);
 await screen.findByText('本次研究信息选择已保存');
 const intent=api.adoptResearchInformation.mock.calls[0][1];
 expect(intent.selections).toEqual({research_drug:0,clinical_phase:1});
 expect(intent.snapshot_sha256).toBe(current.revision_sha256);
 expect(intent.fact_updates).toBeUndefined();
 view.unmount();render(<ResearchInformationCard {...props} api={api}/>);
 await screen.findByText('本次研究信息选择已保存');
 expect(api.recoverResearchInformation.mock.calls[0][1]).toEqual(intent);
 expect(api.adoptResearchInformation).toHaveBeenCalledTimes(1);
});
it('retains uncertain writes and only looks up their original receipts',async()=>{
 const api={getStudyDefinition:vi.fn(async()=>current),adoptResearchInformation:vi.fn(async()=>{throw new Error('连接中断');}),recoverResearchInformation:vi.fn(async()=>receipt)};
 render(<ResearchInformationCard {...props} api={api}/>);
 const button=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(button.disabled).toBe(false));fireEvent.click(button);
 const recover=await screen.findByRole('button',{name:'核对本次研究信息保存'});
 fireEvent.click(recover);await screen.findByText('本次研究信息选择已保存');
 expect(api.adoptResearchInformation).toHaveBeenCalledTimes(1);
});
it('allows a saved selection to be revised with a new intent and current version',async()=>{
 const api={getStudyDefinition:vi.fn().mockResolvedValueOnce(current).mockResolvedValue({...current,
   definition:{...current.definition,revision:2},revision_sha256:'c'.repeat(64)}),
   adoptResearchInformation:vi.fn(async()=>receipt),recoverResearchInformation:vi.fn(async()=>receipt)};
 render(<ResearchInformationCard {...props} api={api}/>);
 const save=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(save.disabled).toBe(false));fireEvent.click(save);
 await screen.findByText('本次研究信息选择已保存');
 fireEvent.click(screen.getByRole('button',{name:'调整研究信息'}));
 await waitFor(()=>expect(api.getStudyDefinition).toHaveBeenCalledTimes(2));
 const again=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(again.disabled).toBe(false));fireEvent.click(again);
 await waitFor(()=>expect(api.adoptResearchInformation).toHaveBeenCalledTimes(2));
 const first=api.adoptResearchInformation.mock.calls[0][1],second=api.adoptResearchInformation.mock.calls[1][1];
 expect(second.operation_id).not.toBe(first.operation_id);expect(second.expected_revision).toBe(2);
 expect(Object.keys(localStorage).some(key=>key.endsWith(':attempt:'+first.operation_id))).toBe(true);
});
it('discovers already confirmed study facts in a fresh browser without another confirmation',async()=>{
 const api={getStudyDefinition:vi.fn(async()=>({...current,definition:{...current.definition,
   canonical_state:'confirmed',facts:{'framing.investigational_product':'合成药X','framing.study_phase':'Ⅲ期'}}})),
   adoptResearchInformation:vi.fn(),recoverResearchInformation:vi.fn()};
 render(<ResearchInformationCard {...props} api={api}/>);
 await screen.findByText('当前研究已保存这些信息');
 expect(screen.queryByRole('button',{name:'确认研究信息'})).toBeNull();
 expect(api.adoptResearchInformation).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'调整研究信息'}));
 await waitFor(()=>expect(screen.getByRole('button',{name:'确认研究信息'}).disabled).toBe(false));
 expect(screen.getByLabelText('研究期别').value).toBe('1');
});
it('allows an optional direct correction and recovers that exact text',async()=>{
 const api={getStudyDefinition:vi.fn(async()=>current),adoptResearchInformation:vi.fn(async()=>receipt),recoverResearchInformation:vi.fn(async()=>receipt)};
 const view=render(<ResearchInformationCard {...props} api={api}/>);
 const save=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(save.disabled).toBe(false));
 fireEvent.change(screen.getByLabelText('研究药物'),{target:{value:'custom'}});
 fireEvent.change(screen.getByLabelText('研究药物（自行修改）'),{target:{value:'用户修正药物X'}});
 fireEvent.click(save);await screen.findByText('本次研究信息选择已保存');
 expect(screen.getByText('用户修正药物X')).toBeTruthy();
 const intent=api.adoptResearchInformation.mock.calls[0][1];
 expect(intent.user_edits).toEqual({research_drug:'用户修正药物X'});
 view.unmount();render(<ResearchInformationCard {...props} api={api}/>);
 await screen.findByText('用户修正药物X');
 expect(api.recoverResearchInformation.mock.calls[0][1]).toEqual(intent);
 expect(api.adoptResearchInformation).toHaveBeenCalledTimes(1);
});

it('shows a saved direct correction in a fresh browser without forcing the original suggestion',async()=>{
 const api={getStudyDefinition:vi.fn(async()=>({...current,definition:{...current.definition,
   canonical_state:'confirmed',facts:{'framing.investigational_product':'用户修正药物X','framing.study_phase':'Ⅱ期'}}})),
   adoptResearchInformation:vi.fn(),recoverResearchInformation:vi.fn()};
 render(<ResearchInformationCard {...props} api={api}/>);
 await screen.findByText('当前研究已保存这些信息');
 expect(screen.getByText('用户修正药物X')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'确认研究信息'})).toBeNull();
});
it('preserves a new line while editing multiple drug names and saves the array',async()=>{
 const api={getStudyDefinition:vi.fn(async()=>current),adoptResearchInformation:vi.fn(async()=>receipt),recoverResearchInformation:vi.fn(async()=>receipt)};
 render(<ResearchInformationCard {...props} proposal={{fields:{research_drug:[{candidate:['药物甲','药物乙']}]}}} api={api}/>);
 const save=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(save.disabled).toBe(false));
 fireEvent.change(screen.getByLabelText('研究药物'),{target:{value:'custom'}});
 const input=screen.getByLabelText('研究药物（自行修改）');
 fireEvent.change(input,{target:{value:'修改甲\n'}});
 expect(input.value).toBe('修改甲\n');
 fireEvent.change(input,{target:{value:'修改甲\n修改乙'}});fireEvent.click(save);
 await screen.findByText('本次研究信息选择已保存');
 expect(api.adoptResearchInformation.mock.calls[0][1].user_edits.research_drug).toEqual(['修改甲','修改乙']);
});
it('keeps the original receipt while showing information changed later in the study',async()=>{
 const later={...receipt,revision:3,definition:{...receipt.definition,revision:3,
   facts:{'framing.investigational_product':'后来更新药物','framing.study_phase':'Ⅲ期'}}};
 const api={getStudyDefinition:vi.fn(async()=>current),adoptResearchInformation:vi.fn(async()=>receipt),
   recoverResearchInformation:vi.fn(async()=>later)};
 const view=render(<ResearchInformationCard {...props} api={api}/>);
 const save=screen.getByRole('button',{name:'确认研究信息'});
 await waitFor(()=>expect(save.disabled).toBe(false));fireEvent.click(save);
 await screen.findByText('本次研究信息选择已保存');
 view.unmount();render(<ResearchInformationCard {...props} api={api}/>);
 await screen.findByText('后来更新药物');
 expect(screen.getByText('研究信息后来有更新。下方显示当前内容，原确认记录已保留。')).toBeTruthy();
 expect(api.adoptResearchInformation).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('button',{name:'调整研究信息'}));
 expect(screen.getByLabelText('研究药物（自行修改）').value).toBe('后来更新药物');
});
