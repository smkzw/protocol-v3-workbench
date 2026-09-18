import React, {useState, useEffect} from "react";
import {RegimenProposalCard} from "../src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx";
import regimenFixture from "./fixtures/regimen-card-fixture.json";
import contextFixture from "./fixtures/study-context-fixture.json";
import adoptionFixture from "./fixtures/regimen-adoption-fixture.json";
import recoveryFixture from "./fixtures/regimen-recovery-fixture.json";
import {RegimenAdoptionCard} from "../src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.jsx";
import {createProtocolWorkspaceApi} from "../src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs";
import {createRoot} from "react-dom/client";
import {ProtocolIntakeWorkspace} from "../src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.jsx";
import {installApiContractFetch} from "../src/runtimeReadiness.js";
import "../src/styles.css";
installApiContractFetch(window);
const referenceMode = new URLSearchParams(location.search).get("reference") === "saved";
const contextMode = new URLSearchParams(location.search).get("context") === "fixture";
const projectId = contextMode ? contextFixture.project_id : referenceMode ? "project-real-reference-intake-20260913" : "project-intake-browser-fixture";
if (contextMode) {
  const key="protocol-v3:intake:"+projectId;
  if(!localStorage.getItem(key))localStorage.setItem(key,JSON.stringify({runId:contextFixture.seed_run_id,brief:contextFixture.user_brief}));
}
if (referenceMode) {
  const key = "protocol-v3:intake:" + projectId;
  if (!localStorage.getItem(key)) localStorage.setItem(key,JSON.stringify({runId:"research-intake:5794359d7bf86bb0bc4cec5c35965f6c3f79ac462b02d24e95133a27c3050799"}));
  const designKey = "protocol-v3:regimen:" + JSON.stringify([projectId, "research-intake:5794359d7bf86bb0bc4cec5c35965f6c3f79ac462b02d24e95133a27c3050799"]);
  if (!localStorage.getItem(designKey)) localStorage.setItem(designKey, JSON.stringify({runId:"regimen-design:e072c81b3d5c801e220eec6732125d6bc5978bcbeedd2c5022e9936346b3ff03"}));
}
const adoptionApi = {...createProtocolWorkspaceApi(),sourceDownloadUrl:()=>""};
function AdoptionFixtureView() {
  const fixture = new URLSearchParams(location.search).get("scenario") === "unknown" ? recoveryFixture : adoptionFixture;
  const [state,setState]=useState(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController();
    adoptionApi.getRegimenDesign(fixture.project_id,fixture.run_id,{signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted)setState(value);})
      .catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});
    return()=>controller.abort();
  },[]);
  return <><aside style={{padding:"10px 24px",background:"#fff3d6",fontSize:14}}>采用验收环境 · 全部数值为合成资料 · 实际API与独立SQLite保存 · 不代表真实研究</aside>
    {error&&<p role="alert">{error}</p>}
    {state?.validation?.proposal&&<main style={{padding:"24px 12px"}}><RegimenAdoptionCard
      projectId={fixture.project_id} studyDefinitionId={fixture.study_definition_id}
      actorId={fixture.actor_id} runId={fixture.run_id} proposal={state.validation.proposal} api={adoptionApi}/></main>}
  </>;
}
function FunctionalView() {
  const [clicked, setClicked] = useState(false);
  const params = new URLSearchParams(location.search);
  const regimenMode = params.get("regimen") === "fixture";
  // URL-parameterized project/actor: drive the REAL component + REAL backend
  // (isolated SQLite, real model profile) without editing this harness.
  const urlProject = params.get("project");
  const urlActor = params.get("actor");
  if (urlProject) {
    const actor = urlActor || "medical_manager";
    const api = createProtocolWorkspaceApi();
    return <ProtocolIntakeWorkspace projectId={urlProject} actorId={actor} api={api} studyDefinitionId={params.get("study") || undefined} />;
  }
  if (new URLSearchParams(location.search).get("regimen") === "adoption") return <AdoptionFixtureView/>;
  if (regimenMode) return <>
    <aside style={{padding:"10px 24px",background:"#fff3d6",fontSize:14}}>组件验收环境 · 给药数值全部为合成测试资料 · 不采用研究事实</aside>
    <main style={{padding:"24px 12px"}}><RegimenProposalCard proposal={regimenFixture} onConfirm={async () => setClicked(true)} />
    {clicked ? <p style={{fontSize:14}}>已记录模拟点击，未写入研究事实。</p> : null}</main>
  </>;
  return <><aside style={{padding:"10px 24px",background:"#fff3d6",fontSize:14}}>{contextMode ? "合成资料验收 · 来源与两次测试生成已预存 · 本页验证研究关联和采用 · 不是真实研究" : referenceMode ? "只读验收页 · 已保存的真实GLM参考整理 · 非当前项目事实" : "功能验证环境 · 独立资料库 · 整理回复为测试数据"}</aside><ProtocolIntakeWorkspace projectId={projectId} actorId={contextMode ? contextFixture.actor_id : undefined} /></>;
}
createRoot(document.getElementById("root")).render(<React.StrictMode><FunctionalView /></React.StrictMode>);
