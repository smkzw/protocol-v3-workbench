import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scratch = dirname(fileURLToPath(import.meta.url));
const workspace = resolve(scratch, "../../../../");
const frontend = resolve(workspace, "frontend");
const require = createRequire(resolve(frontend, "package.json"));
const { defineConfig } = await import(pathToFileURL(require.resolve("vitest/config")).href);
const react = (await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href)).default;

export default defineConfig({
  plugins: [react()],
  root: frontend,
  server: { fs: { allow: [workspace] } },
  resolve: {
    alias: {
      "@scratch-workbench": resolve(frontend, "src/features/medical-writing/protocol-workbench"),
      "@scratch-fixture": resolve(frontend, "tests/fixtures/regimen-card-fixture.json"),
      react: resolve(frontend, "node_modules/react"),
      "react-dom": resolve(frontend, "node_modules/react-dom"),
      "@testing-library/react": resolve(frontend, "node_modules/@testing-library/react"),
    },
  },
  test: {
    environment: "jsdom",
    dir: scratch,
    include: ["probe_regimen_adoption_frontend.test.js"],
  },
});
