/* C03 scratch vitest config: extends the frozen frontend vite config (react
 * plugin, workbench define) but points the test root at frontend/ so bare
 * imports resolve, and includes only this run's scratch test files. */
import { fileURLToPath } from "node:url";
import base from "../../../frontend/vite.config.mjs";

const frontendRoot = fileURLToPath(new URL("../../../frontend/", import.meta.url));
const scratch = fileURLToPath(new URL("./", import.meta.url));

export default {
  ...base,
  root: frontendRoot,
  test: {
    environment: "jsdom",
    include: [`${scratch}*.test.jsx`],
  },
};
