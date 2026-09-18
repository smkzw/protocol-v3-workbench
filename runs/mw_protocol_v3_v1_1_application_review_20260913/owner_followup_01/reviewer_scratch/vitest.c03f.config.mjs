/* C03 followup scratch vitest config: frozen frontend vite config (react
 * plugin), test root at frontend/ so bare imports resolve; includes only
 * this run's scratch tests. */
import { fileURLToPath } from "node:url";
import base from "../../../../frontend/vite.config.mjs";

const frontendRoot = fileURLToPath(new URL("../../../../frontend/", import.meta.url));
const scratch = fileURLToPath(new URL("./", import.meta.url));

export default {
  ...base,
  root: frontendRoot,
  test: {
    environment: "jsdom",
    include: [`${scratch}*.test.jsx`],
  },
};
