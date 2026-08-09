import assert from "node:assert/strict";
import test from "node:test";

import { alignedArtifactId } from "./referenceIdentity.mjs";

const artifacts = [
  { artifact_id: "artifact-a-old", nct_id: "NCTA", source_current: false },
  { artifact_id: "artifact-a-current", nct_id: "NCTA", source_current: true },
  { artifact_id: "artifact-b", nct_id: "NCTB", source_current: true },
];

test("candidate selection replaces a cross-study artifact with the current study artifact", () => {
  assert.equal(
    alignedArtifactId(artifacts, "artifact-b", "NCTA"),
    "artifact-a-current",
  );
});

test("candidate selection preserves an artifact already bound to the same study", () => {
  assert.equal(
    alignedArtifactId(artifacts, "artifact-a-old", "NCTA"),
    "artifact-a-old",
  );
});

test("candidate selection clears artifact state when the study has no prepared document", () => {
  assert.equal(alignedArtifactId(artifacts, "artifact-b", "NCTC"), "");
});
