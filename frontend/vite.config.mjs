import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8910";
const frontendDir = dirname(fileURLToPath(import.meta.url));
const workbenchRoot = resolve(frontendDir, "..");
const runtimeContract = JSON.parse(readFileSync(
  join(workbenchRoot, "packages/contracts/workbench_contracts/runtime_contract.json"),
  "utf8",
));

function sourceFingerprint(sourceRoot, extensions, prefix, digestPrefixLength, additionalFiles = []) {
  const files = [];
  const visit = (directory) => {
    readdirSync(directory, { withFileTypes: true }).forEach((entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (entry.isFile() && extensions.includes(extname(entry.name))) files.push(path);
    });
  };
  visit(sourceRoot);
  additionalFiles.forEach((path) => files.push(path));
  const digest = createHash("sha256");
  files.sort().forEach((path) => {
    digest.update(relative(sourceRoot, path).split("\\").join("/"));
    digest.update("\0");
    digest.update(readFileSync(path));
    digest.update("\0");
  });
  return `${prefix}-${digest.digest("hex").slice(0, digestPrefixLength)}`;
}

const fingerprint = runtimeContract.build_fingerprint;
const runtimeExpectation = {
  runtimeContractSchema: runtimeContract.schema_version,
  apiContractVersion: runtimeContract.api_contract_version,
  clientContractHeader: runtimeContract.client_contract_header,
  expectedBackendBuildId: sourceFingerprint(
    join(workbenchRoot, fingerprint.backend_source_root),
    fingerprint.backend_extensions,
    "api",
    fingerprint.digest_prefix_length,
  ),
  frontendBuildId: sourceFingerprint(
    join(workbenchRoot, fingerprint.frontend_source_root),
    fingerprint.frontend_extensions,
    "web",
    fingerprint.digest_prefix_length,
    fingerprint.frontend_additional_files.map((path) => join(workbenchRoot, path)),
  ),
};

function runtimeBuildManifestPlugin() {
  const source = `${JSON.stringify(runtimeExpectation, null, 2)}\n`;
  return {
    name: "workbench-runtime-build-manifest",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if ((request.url || "").split("?", 1)[0] !== "/runtime-build.json") {
          next();
          return;
        }
        response.statusCode = 200;
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        response.setHeader("Cache-Control", "no-store");
        response.end(source);
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "runtime-build.json", source });
    },
  };
}

export default defineConfig({
  define: {
    __WORKBENCH_RUNTIME_EXPECTATION__: JSON.stringify(runtimeExpectation),
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    proxy: {
      "/api": apiProxyTarget,
    },
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  preview: {
    proxy: {
      "/api": apiProxyTarget,
    },
  },
  plugins: [runtimeBuildManifestPlugin(), react()],
});
