import { ProtocolWritingDesk } from './ProtocolWritingDesk';
import { useEffect, useRef, useState } from 'react';
function restored(key) {try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}}
function message(error) {
  const text=error?.detail?.message||error?.message;
  return typeof text==='string' && /[\u3400-\u9fff]/u.test(text)?text:'本次保存结果尚未核实，资料和原操作已保留。';
}
function ContextSession({projectId,seedRunId,actorId,api,proposal,onNavigationGuardChange}) {
  const key='protocol-v3:study-context:'+JSON.stringify([projectId,seedRunId]);
  const selectionKey='protocol-v3:current-study:'+projectId;
  const [pending,setPending]=useState(()=>restored(key));
  const [studies,setStudies]=useState([]);
  const [selectedId,setSelectedId]=useState(()=>restored(selectionKey));
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[refresh,setRefresh]=useState(0);
  const alive=useRef(true),flight=useRef(false),request=useRef(null),apiRef=useRef(api);apiRef.current=api;
  const selected=studies.find(study=>study.study_definition_id===selectedId);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();};},[]);
  async function execute(packet,recover,controller) {
    if(!recover && flight.current)return;
    if(!recover)flight.current=true;
    setBusy(true);setError('');
    let saved=false;
    try {
      if(!recover) {
        packet={...packet,notExecuted:false};
        localStorage.setItem(key+':attempt:'+packet.intent.operation_id,JSON.stringify(packet));
        localStorage.setItem(key,JSON.stringify(packet));setPending(packet);
      }
      const client=apiRef.current;
      const result=packet.kind==='create'
        ?await client[recover?'recoverResearchContext':'createResearchContext'](projectId,packet.intent,{signal:controller.signal})
        :await client[recover?'recoverResearchInputs':'updateResearchInputs'](projectId,packet.studyId,packet.intent,{signal:controller.signal});
      if(controller.signal.aborted||!alive.current)return;
      const minimum=packet.kind==='create'?1:packet.intent.expected_revision+1;
      if(result?.project_id!==projectId||result.definition?.project_id!==projectId
        ||!result.study_definition_id||result.definition.study_definition_id!==result.study_definition_id
        ||(packet.kind==='update'&&result.study_definition_id!==packet.studyId)
        ||!Number.isInteger(result.revision)||result.revision<minimum||result.definition.revision!==result.revision
        ||!result.revision_sha256||!result.effective_decision?.decision_record_id)throw new Error('本次保存回执尚未核对清楚，原操作已保留。');
      try{localStorage.setItem(selectionKey,JSON.stringify(result.study_definition_id));localStorage.removeItem(key);}
      catch{setNotice('内容已保存，浏览器未能更新本页记录；重新打开时会再次核对。');}
      saved=true;setLoading(true);setSelectedId(result.study_definition_id);setPending(null);setRefresh(v=>v+1);
    } catch(reason) {
      if(controller.signal.aborted||!alive.current)return;
      if(!recover&&reason?.status===424) {
        const rejected={...packet,notExecuted:true};
        try{localStorage.setItem(key,JSON.stringify(rejected));setPending(rejected);}catch{}
      } else if(!recover&&[400,404,409,422].includes(reason?.status)) {
        try{localStorage.removeItem(key);setPending(null);setNotice(message(reason));setRefresh(v=>v+1);}catch{}
      }
      setError(message(reason));
    } finally {
      if(!recover)flight.current=false;
      if(!controller.signal.aborted&&alive.current){setBusy(false);if(!saved)setLoading(false);}
    }
  }
  useEffect(()=>{
    const controller=new AbortController();
    async function load(){
      setLoading(true);
      if(pending){if(pending.notExecuted){setLoading(false);return;}await execute(pending,true,controller);return;}
      try{
        const result=await apiRef.current.listResearchStudies(projectId,seedRunId,{signal:controller.signal});
        if(controller.signal.aborted)return;
        if(!Array.isArray(result?.studies)||result.studies.some(s=>!s.study_definition_id||!Number.isInteger(s.revision)||!s.revision_sha256)
          ||new Set(result.studies.map(s=>s.study_definition_id)).size!==result.studies.length)throw new Error('当前研究列表尚未读取完整，请再次读取。');
        setStudies(result.studies);
        if(result.studies.length===1)setSelectedId(result.studies[0].study_definition_id);
        else if(!result.studies.some(s=>s.study_definition_id===selectedId))setSelectedId(null);
        setError('');
      }catch(reason){if(!controller.signal.aborted)setError(message(reason));}
      finally{if(!controller.signal.aborted)setLoading(false);}
    }
    load();return()=>controller.abort();
  },[projectId,seedRunId,refresh]);
  function save(){
    if(flight.current||!actorId||loading||busy)return;
    const packet=pending?.notExecuted?pending:{kind:selected?'update':'create',studyId:selected?.study_definition_id,
      intent:{seed_run_id:seedRunId,operation_id:'research-context:'+crypto.randomUUID(),actor_id:actorId,
        decided_at:new Date().toISOString(),...(selected?{expected_revision:selected.revision,snapshot_sha256:selected.revision_sha256}:{})}};
    const controller=new AbortController();request.current=controller;execute(packet,false,controller);
  }
  if(!pending&&!loading&&!error&&selected?.matches_selected_inputs===true)return <ProtocolWritingDesk projectId={projectId} seedRunId={seedRunId}
    studyDefinitionId={selected.study_definition_id} actorId={actorId} api={api} proposal={proposal} onNavigationGuardChange={onNavigationGuardChange}/>;
  return <section className="pvi-proposal" aria-label="本次方案写作">
    <h2>继续方案设计</h2>
    {notice&&<p role="status">{notice}</p>}{error&&<p role="alert">{error}</p>}
    {(loading||busy)&&<p role="status">正在读取本次研究记录。</p>}
    {pending?<button type="button" disabled={busy||loading} onClick={()=>pending.notExecuted?save():setRefresh(v=>v+1)}>
      {pending.notExecuted?'配置恢复后继续保存原选择':'核对本次保存'}</button>:!loading&&<>
      {studies.length>1&&<label>选择要继续的研究<select value={selectedId||''} onChange={event=>{
        setSelectedId(event.target.value);try{localStorage.setItem(selectionKey,JSON.stringify(event.target.value));}catch{}
      }}><option value="">请选择已有研究</option>{studies.map((study,index)=><option key={study.study_definition_id} value={study.study_definition_id}>
        {study.input_context?.user_brief?.slice(0,60)||`已有研究 ${index+1}`} · 第{study.revision}版
      </option>)}</select></label>}
      {selected&&<p>本次资料与当前研究不同。更新后保留已有研究内容，受影响的确认需要重新查看。</p>}
      <button type="button" disabled={busy||Boolean(error)||!actorId||(studies.length>0&&!selected)} onClick={save}>
        {selected?'使用本次资料继续':'开始本次方案写作'}</button>
      {error&&<button type="button" onClick={()=>setRefresh(v=>v+1)}>重新读取研究</button>}
    </>}
  </section>;
}
export function StudyContextWorkspace(props){return <ContextSession key={JSON.stringify([props.projectId,props.seedRunId])} {...props}/>;}
