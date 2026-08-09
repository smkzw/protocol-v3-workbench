import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createMedicalMonitoringApi } from "./medicalMonitoringApi.mjs";

let passed = 0;
function check(condition, message) {
  if (!condition) throw new Error(message);
  passed += 1;
}

const featureDir = fileURLToPath(new URL(".", import.meta.url));
const productionFiles = readdirSync(featureDir)
  .filter((name) => /\.(mjs|jsx)$/.test(name) && !name.endsWith(".test.mjs"))
  .map((name) => join(featureDir, name));
const clientActorLiteral = /actor\s*:\s*["']medical_manager["']/;
for (const file of productionFiles) {
  check(
    !clientActorLiteral.test(readFileSync(file, "utf8")),
    `feature production source must not hard-code a client actor: ${file}`,
  );
}

const calls = [];
const api = createMedicalMonitoringApi({
  fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  },
});
await api.decideMonitoringAiCandidate("project-1", "candidate-1", {
  decision: "accepted",
  actor: "medical_manager",
  reason: "仅用于证明客户端字段会被丢弃。",
});
const body = JSON.parse(calls[0].options.body);
check(body.decision === "accepted", "preserves the domain decision payload");
check(!("actor" in body), "strips a transitional client actor before POST");

console.log(`medicalMonitoringServerIdentity: ${passed} passed`);
