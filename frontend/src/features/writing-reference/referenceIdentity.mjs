export function alignedArtifactId(artifacts, currentArtifactId, nctId) {
  const items = Array.isArray(artifacts) ? artifacts : [];
  const currentArtifact = items.find((item) => item.artifact_id === currentArtifactId);
  if (currentArtifact?.nct_id === nctId) return currentArtifactId;
  const nextArtifact = items.find((item) => item.nct_id === nctId && item.source_current)
    || items.find((item) => item.nct_id === nctId);
  return nextArtifact?.artifact_id || "";
}
