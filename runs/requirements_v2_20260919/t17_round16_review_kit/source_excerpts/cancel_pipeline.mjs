// Original two function bodies from MedicalWritingAuthoringJourneySetup.jsx
// commit 455b37ee4530628736bd6b37b622796f13e9498f, windows 700–965 / 2180–2370.
// Lexical dependencies are provided by a factory ONLY for isolated testing.
export function sourceFunctions(scope) {
  const { projectId, activeProjectRef, setBusy, setPipelineStatus, setPipelinePollNonce,
    setMessage, setImpactCancelArmed, confirmImpact, fetch, readJson } = scope;
  const cancelResearchPipeline = async () => {
    const requestProjectId = projectId;
    setBusy("pipeline-cancel");
    try {
      const result = await fetch(`/api/projects/${requestProjectId}/medical-writing/research-pipeline/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "medical_manager" }),
      }).then(readJson);
      if (activeProjectRef.current !== requestProjectId) return;
      setPipelineStatus((current) => ({ ...(current || {}), pipeline: result.pipeline }));
      setPipelinePollNonce((current) => current + 1);
    } catch (error) {
      if (activeProjectRef.current === requestProjectId) setMessage(`取消研究流水线失败：${error.message}`);
    } finally {
      if (activeProjectRef.current === requestProjectId) setBusy("");
    }
  };
  const cancelPipelineThenSubmit = async () => {
    await cancelResearchPipeline();
    setImpactCancelArmed(false);
    await confirmImpact();
  };
  return {cancelResearchPipeline, cancelPipelineThenSubmit};
}
