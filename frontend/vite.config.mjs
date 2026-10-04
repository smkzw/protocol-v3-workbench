import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// R27 批一（已立案脚枪排雷）：默认代理曾指向 live 8910（医学监查共享
// runtime）。本子系统固定为 5301；显式 VITE_API_PROXY_TARGET 仍可覆盖。
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:5301";
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

// NEW-4（R27 第1轮末修订）：期望指纹必须可在任意时刻对当前源码树重算。
// define 注入（prod bundle + 请求头）仍用 vite 启动时的快照 runtimeExpectation，
// 但 dev 中间件 /runtime-build.json 改为逐请求调用本函数现算——否则 vite 启动
// 后的代码变更永远不反映到前端期望值上（R27 现场：横幅"期望 api-a8a3… vs
// 运行后端 api-c743…"刷新无效，根因即此快照）。
function buildRuntimeExpectation() {
  return {
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
}

const runtimeExpectation = buildRuntimeExpectation();

function runtimeBuildManifestPlugin() {
  return {
    name: "workbench-runtime-build-manifest",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if ((request.url || "").split("?", 1)[0] !== "/runtime-build.json") {
          next();
          return;
        }
        // NEW-4：按当前源码树逐请求现算（见 buildRuntimeExpectation 注释）。
        let payload;
        try {
          payload = buildRuntimeExpectation();
        } catch (error) {
          response.statusCode = 500;
          response.setHeader("Content-Type", "application/json; charset=utf-8");
          response.setHeader("Cache-Control", "no-store");
          response.end(JSON.stringify({ detail: `runtime fingerprint failed: ${error.message}` }));
          return;
        }
        response.statusCode = 200;
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        response.setHeader("Cache-Control", "no-store");
        response.end(`${JSON.stringify(payload, null, 2)}\n`);
      });
    },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "runtime-build.json",
        source: `${JSON.stringify(runtimeExpectation, null, 2)}\n`,
      });
    },
  };
}

// 0927V1 G7 harness (tests/protocol-writing-desk-functional.*): dev-only
// middleware that serves the synthetic fixture DOCX for the fixture snapshot
// URL, so the embedded Office editor loads real content in the component
// acceptance harness without touching any backend. Registered before the
// proxy so it wins for this one fixture path; production builds unaffected.
function g7FixtureDocxPlugin() {
  return {
    name: "g7-fixture-docx",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (!(request.url || "").includes("/office-draft/snapshots/g7-fixture-snapshot/content")) {
          next();
          return;
        }
        response.statusCode = 200;
        response.setHeader("Content-Type",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        response.end(readFileSync(join(frontendDir, "public", "genoffice-fixture", "g7-sample.docx")));
      });
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
  plugins: [runtimeBuildManifestPlugin(), g7FixtureDocxPlugin(), react()],
});
