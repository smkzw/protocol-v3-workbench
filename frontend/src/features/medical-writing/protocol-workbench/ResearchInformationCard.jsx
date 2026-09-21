import {useEffect,useRef,useState} from 'react';
import {sourceRoleDisplayText} from './sourceRoleLabels.mjs';
const LABELS={research_drug:'研究药物',indication:'适应症',clinical_phase:'研究期别',target_or_mechanism:'靶点或作用机制'};
const FACT_PATHS={research_drug:'framing.investigational_product',indication:'framing.indication',clinical_phase:'framing.study_phase',target_or_mechanism:'framing.target_mechanism'};
const DEFAULT_REASON='确认已展示的本次研究信息';
function restored(key){try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}}
function basicValue(value){return typeof value==='string'?Boolean(value.trim()):Array.isArray(value)&&value.length>0&&value.every(item=>typeof item==='string'&&item.trim());}
function displayValue(value){return Array.isArray(value)?value.join('、'):value;}
function message(error){const text=error?.detail?.message||error?.message;return typeof text==='string'&&/[\u3400-\u9fff]/u.test(text)?text:'本次保存结果尚未确认，原选择已保留。';}
function Session({projectId,studyDefinitionId,seedRunId,actorId,proposal,api,compact=false}){
  const key='protocol-v3:research-information:'+JSON.stringify([projectId,studyDefinitionId,seedRunId]);
  const entries=Object.entries(LABELS).filter(([field])=>proposal?.fields?.[field]?.length);
  const [intent,setIntent]=useState(()=>restored(key));
  const [selections,setSelections]=useState(()=>restored(key)?.selections||Object.fromEntries(entries.map(([field])=>[field,0])));
  const [edits,setEdits]=useState(()=>restored(key)?.user_edits||{});
  const [currentValues,setCurrentValues]=useState({});
  const [reason,setReason]=useState(()=>restored(key)?.reason||DEFAULT_REASON);
  const [hasCurrent,setHasCurrent]=useState(false);
  const editing=useRef(false);
  const [study,setStudy]=useState(null),[receipt,setReceipt]=useState(null),[error,setError]=useState('');
  const [busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
  const [notExecuted,setNotExecuted]=useState(()=>Boolean(restored(key)&&restored(key+':not-executed')===restored(key).operation_id));
  const flight=useRef(false),request=useRef(null),alive=useRef(true),apiRef=useRef(api);apiRef.current=api;
  function editValues(values){
    const matches=Object.fromEntries(entries.map(([field])=>[field,proposal.fields[field].findIndex(candidate=>
      JSON.stringify(candidate.candidate)===JSON.stringify(values[field]))]));
    setSelections(Object.fromEntries(entries.map(([field])=>[field,Math.max(0,matches[field])])));
    setEdits(Object.fromEntries(entries.filter(([field])=>matches[field]<0).map(([field])=>[field,values[field]??''])));
  }
  function accept(value,original){
    if(value?.project_id!==projectId||value.study_definition_id!==studyDefinitionId
      ||value.definition?.project_id!==projectId||value.definition.study_definition_id!==studyDefinitionId
      ||!value.effective_decision?.decision_record_id||!value.revision_sha256
      ||!Number.isInteger(value.revision)||value.definition.revision!==value.revision
      ||value.revision<original.expected_revision+1)throw new Error('本次保存回执尚未核对清楚，原选择已保留。');
    setReceipt(value);setError('');
    if(value.definition.facts)setCurrentValues(Object.fromEntries(entries.map(([field])=>[field,value.definition.facts[FACT_PATHS[field]]])));
  }
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();};},[]);
  useEffect(()=>{
    const controller=new AbortController();
    async function load(){
      try{
        if(intent){
          if(notExecuted)return;
          const result=await apiRef.current.recoverResearchInformation(projectId,intent,{signal:controller.signal});
          if(!controller.signal.aborted)accept(result,intent);
        }else{
          const result=await apiRef.current.getStudyDefinition(projectId,studyDefinitionId,{signal:controller.signal});
          if(controller.signal.aborted)return;
          if(result?.definition?.project_id!==projectId||result.definition.study_definition_id!==studyDefinitionId
            ||!Number.isInteger(result.definition.revision)||!result.revision_sha256)throw new Error('当前研究版本尚未读取完整，请再次读取。');
          setStudy(result);
          if(!editing.current&&['confirmed','frozen'].includes(result.definition.canonical_state)){
            const values=Object.fromEntries(entries.map(([field])=>[field,result.definition.facts?.[FACT_PATHS[field]]]));
            if(Object.values(values).every(basicValue)){
              setCurrentValues(values);editValues(values);
              setHasCurrent(true);
            }
          }
        }
      }catch(error){if(!controller.signal.aborted)setError(message(error));}
    }
    load();return()=>controller.abort();
  },[projectId,studyDefinitionId,seedRunId,refresh]);
  async function confirm(){
    if(flight.current||!actorId||(!study&&!intent)||(intent&&!notExecuted)||!Object.values(edits).every(basicValue))return;
    const original=notExecuted?intent:{seed_run_id:seedRunId,study_definition_id:studyDefinitionId,
      operation_id:'research-info:'+crypto.randomUUID(),expected_revision:study.definition.revision,
      snapshot_sha256:study.revision_sha256,actor_id:actorId,decided_at:new Date().toISOString(),
      selections:{...selections},reason:reason.trim()||DEFAULT_REASON,
      ...(Object.keys(edits).length?{user_edits:edits}:{})};
    try{
      localStorage.setItem(key+':attempt:'+original.operation_id,JSON.stringify(original));
      localStorage.setItem(key,JSON.stringify(original));localStorage.removeItem(key+':not-executed');
    }catch{setError('浏览器未能保留本次选择，请恢复存储后再保存。');return;}
    flight.current=true;setBusy(true);setIntent(original);setNotExecuted(false);setError('');
    const controller=new AbortController();request.current=controller;
    try{
      const result=await apiRef.current.adoptResearchInformation(projectId,original,{signal:controller.signal});
      if(!controller.signal.aborted&&alive.current)accept(result,original);
    }catch(error){
      if(controller.signal.aborted||!alive.current)return;
      setError(message(error));
      if(error?.status===424){
        setNotExecuted(true);try{localStorage.setItem(key+':not-executed',JSON.stringify(original.operation_id));}catch{}
      }else if([400,404,409,422].includes(error?.status)){
        try{localStorage.removeItem(key);setIntent(null);setStudy(null);setRefresh(v=>v+1);}catch{}
      }
    }finally{flight.current=false;if(alive.current&&!controller.signal.aborted)setBusy(false);}
  }
  const chosenValue=field=>intent?.user_edits?.[field]??proposal.fields[field][(intent?.selections||selections)[field]]?.candidate;
  const receiptHasCurrent=Boolean(receipt?.definition?.facts);
  const changedSinceChoice=receiptHasCurrent&&entries.some(([field])=>JSON.stringify(currentValues[field])!==JSON.stringify(chosenValue(field)));
  return <section className='pvi-proposal pvi-research-information' aria-label='确认本次研究信息'>
    {!compact && <h3>确认本次研究信息</h3>}
    {!(compact && (receipt||hasCurrent)) && <p>{receipt||hasCurrent?'以下为已保存的研究信息；需要更改时可调整。':'已预选资料整理出的建议，请核对它们是否适用于本次研究。'}</p>}
    {error&&<p role='alert'>{error}</p>}
    {receipt||hasCurrent?<><p role='status'>{compact?'已确认':receipt?'本次研究信息选择已保存':'当前研究已保存这些信息'}</p>
      {changedSinceChoice&&<p>研究信息后来有更新。下方显示当前内容，原确认记录已保留。</p>}
      <dl>{entries.map(([field,label])=><div key={field}><dt>{label}</dt><dd>{displayValue(receipt&&!receiptHasCurrent?chosenValue(field):currentValues[field])??'当前未记录'}</dd></div>)}</dl>
      {changedSinceChoice&&<details><summary>查看这次确认时的选择</summary><dl>{entries.map(([field,label])=><div key={field}><dt>{label}</dt><dd>{displayValue(chosenValue(field))}</dd></div>)}</dl></details>}
      <button type='button' onClick={()=>{
      try{localStorage.removeItem(key);localStorage.removeItem(key+':not-executed');}
      catch{setError('浏览器未能保留调整状态，请恢复存储后再试。');return;}
      if(receiptHasCurrent)editValues(currentValues);
      editing.current=true;setHasCurrent(false);setIntent(null);setReceipt(null);setStudy(null);setNotExecuted(false);setRefresh(value=>value+1);
    }}>调整研究信息</button></>:<>
      <fieldset disabled={busy||Boolean(intent)}>
        {entries.map(([field,label])=><div className='pvi-information-field' key={field}><label>{label}
          <select aria-label={label} value={Object.hasOwn(edits,field)?'custom':selections[field]??0} onChange={event=>{
            editing.current=true;
            if(event.target.value==='custom')setEdits(value=>({...value,[field]:proposal.fields[field][selections[field]??0].candidate}));
            else{setSelections(value=>({...value,[field]:Number(event.target.value)}));setEdits(value=>{const next={...value};delete next[field];return next;});}
          }}>
            {proposal.fields[field].map((candidate,index)=><option key={index} value={index}>
              {Array.isArray(candidate.candidate)?candidate.candidate.join('、'):candidate.candidate}
            </option>)}
            <option value='custom'>自行修改</option>
          </select></label>
          {Object.hasOwn(edits,field)?<><label>{label}（自行修改）<textarea aria-label={`${label}（自行修改）`}
            value={Array.isArray(edits[field])?edits[field].join('\n'):edits[field]}
            onChange={event=>setEdits(value=>({...value,[field]:Array.isArray(value[field])?event.target.value.split('\n'):event.target.value}))}/></label>
            <p>{Array.isArray(edits[field])?'每行一项。':''}作为你对本次研究的修改保存，不改写资料原文。</p>
            {!basicValue(edits[field])&&<p>请填写修改内容，或改选已有建议。</p>}</>
            :proposal.fields[field][selections[field]??0]?.reason&&<p>{sourceRoleDisplayText(proposal.fields[field][selections[field]??0].reason)}</p>}
        </div>)}
        <label>确认说明（可选修改）<textarea value={reason} onChange={event=>setReason(event.target.value)}/></label>
      </fieldset>
      <button type='button' disabled={busy||!actorId||(!study&&!intent)||(Boolean(intent)&&!notExecuted)||!Object.values(edits).every(basicValue)} onClick={confirm}>
        {notExecuted?'继续保存原选择':'确认研究信息'}
      </button>
      {intent&&!notExecuted&&!busy&&<button type='button' onClick={()=>setRefresh(v=>v+1)}>核对本次研究信息保存</button>}
      {!intent&&!study&&error&&<button type='button' onClick={()=>setRefresh(v=>v+1)}>重新读取当前研究</button>}
    </>}
  </section>;
}
export function ResearchInformationCard(props){
  if(!props.proposal||!Object.keys(LABELS).some(field=>props.proposal.fields?.[field]?.length))return null;
  return <Session key={JSON.stringify([props.projectId,props.studyDefinitionId,props.seedRunId])} {...props}/>;
}
