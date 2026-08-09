import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import test from "node:test";

import {
  buildRunnerCommands,
  collectTestInventory,
  validateTestInventory,
} from "./protocol_v3_test_inventory.mjs";

test("the frontend inventory discovers every supported test exactly once", () => {
  const inventory = collectTestInventory();

  assert.ok(inventory.tests.length > 0);
  assert.equal(
    new Set(inventory.tests.map(({ path }) => path)).size,
    inventory.tests.length,
  );
  assert.ok(inventory.tests.some(({ runner }) => runner === "vitest"));
  assert.ok(inventory.tests.some(({ runner }) => runner === "node"));
  assert.deepEqual(
    inventory.tests.map(({ path }) => path),
    [...inventory.tests].map(({ path }) => path).sort(),
  );
  assert.deepEqual(
    inventory.tests
      .filter(({ runner }) => runner === "vitest")
      .map(({ path }) => path),
    inventory.commands.vitest.paths,
  );
  assert.deepEqual(
    inventory.tests
      .filter(({ runner }) => runner === "node")
      .map(({ path }) => path),
    inventory.commands.node.paths,
  );
  assert.deepEqual(inventory.explicit_node_paths, [
    "tests/monitoring_child_read_contract_qc.mjs",
    "tests/monitoring_source_only_ui_qc.mjs",
  ]);
  assert.deepEqual(inventory.excluded_controlled_qc_paths, [
    "tests/monitoring_content_confirmation_qc.mjs",
    "tests/monitoring_real_projects_actions_qc.mjs",
    "tests/monitoring_real_projects_qc.mjs",
    "tests/monitoring_upload_qc.mjs",
  ]);
  assert.ok(inventory.excluded_controlled_qc_reason.includes("live service"));
  assert.deepEqual(inventory.excluded_stale_qc_paths, [
    "tests/monitoring_unavailable_state_qc.mjs",
  ]);
  assert.ok(inventory.excluded_stale_qc_reason.includes("stale"));
  const monitoringQcOnDisk = readdirSync(new URL(".", import.meta.url))
    .filter((name) => name.startsWith("monitoring_") && name.endsWith("_qc.mjs"))
    .map((name) => `tests/${name}`)
    .sort();
  assert.deepEqual(
    [
      ...inventory.explicit_node_paths,
      ...inventory.excluded_controlled_qc_paths,
      ...inventory.excluded_stale_qc_paths,
    ].sort(),
    monitoringQcOnDisk,
  );
  for (const path of inventory.excluded_controlled_qc_paths) {
    assert.ok(!inventory.tests.some((item) => item.path === path));
  }
  for (const path of inventory.excluded_stale_qc_paths) {
    assert.ok(!inventory.tests.some((item) => item.path === path));
  }
});

test("the inventory validator rejects duplicate, unknown, or uncollected tests", () => {
  assert.throws(
    () => validateTestInventory([
      { path: "src/example.test.mjs", runner: "node" },
      { path: "src/example.test.mjs", runner: "node" },
    ]),
    /duplicate/i,
  );
  assert.throws(
    () => validateTestInventory([
      { path: "src/example.test.jsx", runner: "node" },
    ]),
    /runner/i,
  );
  assert.throws(
    () => validateTestInventory([
      { path: "src/example.test.js", runner: "unknown" },
    ]),
    /unknown runner/i,
  );
  assert.throws(
    () => validateTestInventory([
      { path: "src/example.test.mjs", runner: "node" },
    ], {
      vitest: { paths: [] },
      node: { paths: [] },
    }),
    /uncollected/i,
  );
});

test("runner commands remain explicit and separate", () => {
  const tests = [
    { path: "src/a.test.jsx", runner: "vitest" },
    { path: "src/b.test.mjs", runner: "node" },
  ];
  const commands = buildRunnerCommands(tests);

  assert.equal(commands.vitest.command, "vitest");
  assert.deepEqual(commands.vitest.paths, ["src/a.test.jsx"]);
  assert.deepEqual(commands.node.paths, ["src/b.test.mjs"]);
  assert.ok(commands.vitest.args.includes("--environment"));
  assert.ok(commands.vitest.args.includes("jsdom"));
  assert.ok(commands.node.args.includes("--test"));
  validateTestInventory(tests, commands);
});
