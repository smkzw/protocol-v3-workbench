import { sourceFunctions } from '../source_excerpts/cancel_pipeline.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const rows=[];
for(const mode of ['network_failure','nonterminal_ack','terminal_ack','project_changed']) {
  const calls=[];
  const ref={current:'p'};
  let confirmCount=0;
  const s={projectId:'p',activeProjectRef:ref,setBusy:v=>calls.push(['busy',v]),
    setPipelineStatus:v=>calls.push(['pipeline',v({})]),setPipelinePollNonce:()=>{},
    setMessage:v=>calls.push(['message',v]),setImpactCancelArmed:()=>{},
    confirmImpact:async()=>{confirmCount++;calls.push(['confirm-attempt']);},
    fetch:async()=>{
      if(mode==='network_failure') throw new Error('synthetic network failure');
      if(mode==='project_changed') ref.current='other-project';
      return {pipeline:{stage:mode==='terminal_ack'?'cancelled':'running'}};
    },readJson:async r=>r};
  await sourceFunctions(s).cancelPipelineThenSubmit();
  assert.equal(confirmCount,1);
  rows.push({id:`CANCEL-${rows.length+1}`,case:mode,kind:mode==='terminal_ack'?'control':'reproduced',confirm_attempts:confirmCount,calls});
}
fs.writeFileSync(new URL('../evidence/cancel_probes.json',import.meta.url),JSON.stringify({scope:'Two source function bodies, simulated callbacks/fetch. Proves confirm is attempted, not that backend accepts any mutation.',tests:rows},null,2));
console.log('4 scenario assertions passed; 3 demonstrate unconditional confirm attempts, not backend writes.');
