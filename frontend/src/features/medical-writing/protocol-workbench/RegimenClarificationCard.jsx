import {useEffect,useRef,useState} from 'react';
import './RegimenProposalCard.css';

function questionsOf(proposal){
  return (proposal?.questions||[]).map((raw,index)=>typeof raw==='string'
    ? {question_id:`legacy:${index}`,question:raw,recommended_answer:'',options:[]}
    : raw).filter(item=>item?.question_id&&item?.question);
}
function restored(key){try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}}
function publicMessage(error){const text=error?.detail?.message||error?.message;return typeof text==='string'&&/[\u3400-\u9fff]/u.test(text)?text:'本次补答结果尚未确认，原答案已保留。';}

function Session({projectId,studyDefinitionId,actorId,runId,proposal,api,onConfirmed}){
  const questions=questionsOf(proposal);
  const key='protocol-v3:regimen-answers:'+JSON.stringify([projectId,studyDefinitionId,runId]);
  const original=restored(key);
  const [intent,setIntent]=useState(original);
  const [answers,setAnswers]=useState(()=>original?.answers||Object.fromEntries(questions.map(item=>[
    item.question_id,item.recommended_answer||item.options?.[0]||'',
  ])));
  const [study,setStudy]=useState(null),[receipt,setReceipt]=useState(null);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
  const [notExecuted,setNotExecuted]=useState(()=>Boolean(original&&restored(key+':not-executed')===original.operation_id));
  const alive=useRef(true),flight=useRef(false),request=useRef(null),apiRef=useRef(api),reported=useRef(false);apiRef.current=api;
  function accept(value,source){
    if(value?.study_definition_id!==studyDefinitionId||!value.effective_decision?.decision_record_id
      ||!value.revision_sha256||!Number.isInteger(value.revision)||value.revision<source.expected_revision+1){
      throw new Error('补答保存回执尚未核对清楚，原答案已保留。');
    }
    setReceipt(value);setError('');
  }
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();};},[]);
  useEffect(()=>{
    const controller=new AbortController();
    async function load(){
      try{
        if(intent&&!notExecuted){
          const value=await apiRef.current.recoverRegimenAnswers(projectId,runId,intent,{signal:controller.signal});
          if(!controller.signal.aborted)accept(value,intent);
        }else{
          const value=await apiRef.current.getStudyDefinition(projectId,studyDefinitionId,{signal:controller.signal});
          if(controller.signal.aborted)return;
          if(value?.definition?.study_definition_id!==studyDefinitionId||!value.revision_sha256
            ||!Number.isInteger(value.definition.revision))throw new Error('当前研究版本尚未读取完整。');
          setStudy(value);setError('');
        }
      }catch(reason){if(!controller.signal.aborted)setError(publicMessage(reason));}
    }
    load();return()=>controller.abort();
  },[projectId,studyDefinitionId,runId,refresh]);
  useEffect(()=>{
    if(receipt&&!reported.current){reported.current=true;onConfirmed?.(receipt);}
  },[receipt,onConfirmed]);
  async function confirm(){
    if(flight.current||!actorId||(!study&&!notExecuted)||questions.some(item=>!answers[item.question_id]?.trim()))return;
    const next=notExecuted?intent:{study_definition_id:studyDefinitionId,
      operation_id:'regimen-answers:'+crypto.randomUUID(),expected_revision:study.definition.revision,
      snapshot_sha256:study.revision_sha256,actor_id:actorId,decided_at:new Date().toISOString(),
      reason:'确认给药设计待决问题的补答',answers};
    try{localStorage.setItem(key,next?JSON.stringify(next):'');localStorage.removeItem(key+':not-executed');}
    catch{setError('浏览器未能保留本次答案，请恢复存储后再继续。');return;}
    flight.current=true;setBusy(true);setIntent(next);setNotExecuted(false);setError('');
    const controller=new AbortController();request.current=controller;
    try{
      const value=await apiRef.current.adoptRegimenAnswers(projectId,runId,next,{signal:controller.signal});
      if(alive.current&&!controller.signal.aborted)accept(value,next);
    }catch(reason){
      if(!alive.current||controller.signal.aborted)return;
      setError(publicMessage(reason));
      if(reason?.status===424){setNotExecuted(true);try{localStorage.setItem(key+':not-executed',JSON.stringify(next.operation_id));}catch{}}
      else if([400,404,409,422].includes(reason?.status)){try{localStorage.removeItem(key);setIntent(null);setStudy(null);setRefresh(value=>value+1);}catch{}}
    }finally{flight.current=false;if(alive.current&&!controller.signal.aborted)setBusy(false);}
  }
  if(!questions.length)return null;
  return <section className='rpc-card rpc-clarifications' aria-label='补充给药设计信息'>
    <header className='rpc-heading'><div className='rpc-title-row'><h2>补充给药设计信息</h2><span className='rpc-tag'>需确认</span></div>
      <p className='rpc-status'>AI已尽量预选推荐答案；确认后将结合这些答案继续完善建议。</p></header>
    {questions.map((item,index)=><fieldset className='rpc-question' key={item.question_id} disabled={busy||Boolean(intent)}>
      <legend>{index+1}. {item.question}</legend>
      {item.recommended_answer&&<p><strong>推荐：</strong>{item.recommended_answer}</p>}
      {item.options?.length?<label>选择答案<select value={item.options.includes(answers[item.question_id])?answers[item.question_id]:'custom'} onChange={event=>setAnswers(value=>({...value,[item.question_id]:event.target.value==='custom'?'':event.target.value}))}>
        {item.options.map(option=><option key={option} value={option}>{option}</option>)}<option value='custom'>自行填写</option>
      </select></label>:null}
      {(!item.options?.length||!item.options.includes(answers[item.question_id]))&&<label>你的答案<textarea value={answers[item.question_id]||''} onChange={event=>setAnswers(value=>({...value,[item.question_id]:event.target.value}))}/></label>}
    </fieldset>)}
    {receipt&&<p role='status'>补答已保存，可以继续完善给药建议。</p>}
    {error&&<p className='rpc-error' role='alert'>{error}</p>}
    {!receipt&&<div className='rpc-actions'><button type='button' className='rpc-confirm' disabled={busy||!actorId||(!study&&!notExecuted)||Boolean(intent&&!notExecuted)||questions.some(item=>!answers[item.question_id]?.trim())} onClick={confirm}>
      {notExecuted?'继续保存原答案':'确认补答'}
    </button></div>}
    {intent&&!receipt&&!busy&&!notExecuted&&<button type='button' onClick={()=>setRefresh(value=>value+1)}>核对本次补答</button>}
  </section>;
}

export function RegimenClarificationCard(props){
  return <Session key={JSON.stringify([props.projectId,props.studyDefinitionId,props.runId])} {...props}/>;
}
