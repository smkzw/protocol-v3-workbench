import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, readdirSync } from "node:fs";
import {
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
} from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const frontendRoot = resolve(dirname(scriptPath), "..");
const SUPPORTED_RUNNERS = new Set(["vitest", "node"]);
const TEST_SUFFIXES = new Map([
  [".test.jsx", "vitest"],
  [".test.mjs", "node"],
]);
const IGNORED_DIRECTORIES = new Set([
  ".git",
  ".npm-cache",
  ".vite",
  ".cache",
  "coverage",
  "dist",
  "node_modules",
  "output",
  "runtime",
]);
const EXPLICIT_NODE_QC_PATHS = [
  "tests/monitoring_child_read_contract_qc.mjs",
  "tests/monitoring_source_only_ui_qc.mjs",
];
const EXCLUDED_CONTROLLED_QC_PATHS = [
  "tests/monitoring_content_confirmation_qc.mjs",
  "tests/monitoring_real_projects_actions_qc.mjs",
  "tests/monitoring_real_projects_qc.mjs",
  "tests/monitoring_upload_qc.mjs",
];
const EXCLUDED_CONTROLLED_QC_REASON =
  "requires live service, browser and/or runtime data; protected E2E gate only";
const EXCLUDED_STALE_QC_PATHS = [
  "tests/monitoring_unavailable_state_qc.mjs",
];
const EXCLUDED_STALE_QC_REASON =
  "protected medical-monitoring baseline QC is stale against baseline source; monitoring owner adjudication required";

function fail(message) {
  throw new Error(`[protocol-v3-test-inventory] ${message}`);
}

function isTestCandidate(name) {
  return /\.test\.[^.]+$/.test(name);
}

function runnerForPath(path) {
  if (EXPLICIT_NODE_QC_PATHS.includes(path)) return "node";
  for (const [suffix, runner] of TEST_SUFFIXES) {
    if (path.endsWith(suffix)) return runner;
  }
  fail(`unknown runner for test file: ${path}`);
}

function scanTestFiles(root, directory = root, result = []) {
  for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.isDirectory() && IGNORED_DIRECTORIES.has(entry.name)) continue;
    const absolutePath = join(directory, entry.name);
    if (entry.isDirectory()) {
      scanTestFiles(root, absolutePath, result);
      continue;
    }
    if (entry.isSymbolicLink() && isTestCandidate(entry.name)) {
      fail(`test symlink is not an executable inventory entry: ${relative(root, absolutePath)}`);
    }
    if (!entry.isFile() || !isTestCandidate(entry.name)) continue;
    const path = relative(root, absolutePath).split("\\").join("/");
    result.push({ path, runner: runnerForPath(path) });
  }
  return result;
}

function countPaths(paths) {
  const counts = new Map();
  for (const path of paths) counts.set(path, (counts.get(path) || 0) + 1);
  return counts;
}

function comparePaths(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

export function buildRunnerCommands(tests) {
  const pathsFor = (runner) => tests
    .filter((test) => test.runner === runner)
    .map((test) => test.path);
  const vitestPaths = pathsFor("vitest");
  const nodePaths = pathsFor("node");
  return {
    vitest: {
      runner: "vitest",
      command: "vitest",
      args: [
        "run",
        "--config",
        "vite.config.mjs",
        "--environment",
        "jsdom",
        ...vitestPaths,
      ],
      paths: vitestPaths,
    },
    node: {
      runner: "node",
      command: process.execPath,
      args: ["--test", ...nodePaths],
      paths: nodePaths,
    },
  };
}

export function validateTestInventory(tests, commands = buildRunnerCommands(tests)) {
  if (!Array.isArray(tests)) fail("inventory tests must be an array");
  const paths = tests.map((test) => test.path);
  const duplicatePaths = [...countPaths(paths).entries()]
    .filter(([, count]) => count > 1)
    .map(([path]) => path);
  if (duplicatePaths.length) {
    fail(`duplicate test paths: ${duplicatePaths.join(", ")}`);
  }

  const knownPaths = new Set();
  for (const test of tests) {
    if (!test || typeof test.path !== "string") fail("test entry has no path");
    if (isAbsolute(test.path) || test.path.startsWith("../") || test.path.includes("\\")) {
      fail(`test path must be a normalized frontend-relative path: ${test.path}`);
    }
    const expectedRunner = runnerForPath(test.path);
    if (test.runner !== expectedRunner || !SUPPORTED_RUNNERS.has(test.runner)) {
      fail(`runner mismatch for ${test.path}: expected ${expectedRunner}, got ${test.runner}`);
    }
    knownPaths.add(test.path);
  }
  const sortedPaths = [...paths].sort(comparePaths);
  if (paths.some((path, index) => path !== sortedPaths[index])) {
    fail("test inventory is not deterministically sorted");
  }

  const commandRunners = Object.keys(commands);
  for (const runner of commandRunners) {
    if (!SUPPORTED_RUNNERS.has(runner)) fail(`unknown runner command: ${runner}`);
    if (!Array.isArray(commands[runner]?.paths)) {
      fail(`runner command has no path list: ${runner}`);
    }
  }
  for (const runner of SUPPORTED_RUNNERS) {
    if (!commands[runner]) fail(`missing runner command: ${runner}`);
  }

  const collectedPaths = new Set();
  for (const runner of SUPPORTED_RUNNERS) {
    const runnerPaths = commands[runner].paths;
    for (const path of runnerPaths) {
      if (!knownPaths.has(path)) fail(`runner collected an unknown test: ${path}`);
      if (runnerForPath(path) !== runner) {
        fail(`runner collected ${path} under ${runner}`);
      }
      if (collectedPaths.has(path)) fail(`test collected by multiple runners: ${path}`);
      collectedPaths.add(path);
    }
  }
  const uncollected = paths.filter((path) => !collectedPaths.has(path));
  if (uncollected.length) fail(`uncollected tests: ${uncollected.join(", ")}`);
  if (collectedPaths.size !== knownPaths.size) {
    fail("runner collection does not cover the discovered inventory");
  }
  return true;
}

export function collectTestInventory(root = frontendRoot) {
  const tests = scanTestFiles(root);
  for (const path of EXPLICIT_NODE_QC_PATHS) {
    const absolute = resolve(root, path);
    if (!existsSync(absolute) || !lstatSync(absolute).isFile() || lstatSync(absolute).isSymbolicLink()) {
      fail(`explicit Node QC path is missing or not a regular file: ${path}`);
    }
    tests.push({ path, runner: "node" });
  }
  for (const path of EXCLUDED_CONTROLLED_QC_PATHS) {
    const absolute = resolve(root, path);
    if (!existsSync(absolute) || !lstatSync(absolute).isFile() || lstatSync(absolute).isSymbolicLink()) {
      fail(`controlled QC exclusion is missing or not a regular file: ${path}`);
    }
  }
  for (const path of EXCLUDED_STALE_QC_PATHS) {
    const absolute = resolve(root, path);
    if (!existsSync(absolute) || !lstatSync(absolute).isFile() || lstatSync(absolute).isSymbolicLink()) {
      fail(`stale QC exclusion is missing or not a regular file: ${path}`);
    }
  }
  tests.sort((a, b) => comparePaths(a.path, b.path));
  if (!tests.some(({ runner }) => runner === "vitest")) {
    fail("no Vitest JSX tests were discovered");
  }
  if (!tests.some(({ runner }) => runner === "node")) {
    fail("no direct Node tests were discovered");
  }
  const commands = buildRunnerCommands(tests);
  validateTestInventory(tests, commands);
  return {
    schema_version: "protocol-v3-test-inventory.v1",
    root: "frontend",
    ignored_directories: [...IGNORED_DIRECTORIES].sort(),
    explicit_node_paths: [...EXPLICIT_NODE_QC_PATHS],
    excluded_controlled_qc_paths: [...EXCLUDED_CONTROLLED_QC_PATHS],
    excluded_controlled_qc_reason: EXCLUDED_CONTROLLED_QC_REASON,
    excluded_stale_qc_paths: [...EXCLUDED_STALE_QC_PATHS],
    excluded_stale_qc_reason: EXCLUDED_STALE_QC_REASON,
    counts: {
      total: tests.length,
      vitest: commands.vitest.paths.length,
      node: commands.node.paths.length,
    },
    tests,
    commands,
  };
}

function commandForRunner(runner, descriptor) {
  if (runner === "node") return { command: process.execPath, args: descriptor.args };
  const entry = resolve(frontendRoot, "node_modules/vitest/vitest.mjs");
  if (!existsSync(entry)) {
    fail(`Vitest is not installed at ${entry}; run npm ci from the clean frontend root`);
  }
  return { command: process.execPath, args: [entry, ...descriptor.args] };
}

function runRunner(runner, inventory) {
  const descriptor = inventory.commands[runner];
  const executable = commandForRunner(runner, descriptor);
  process.stderr.write(`[protocol-v3-test-inventory] runner=${runner} tests=${descriptor.paths.length}\n`);
  const result = spawnSync(executable.command, executable.args, {
    cwd: frontendRoot,
    env: process.env,
    stdio: "inherit",
  });
  if (result.error) fail(`${runner} runner failed to start: ${result.error.message}`);
  if (result.status !== 0) {
    process.exitCode = result.status ?? 1;
    return false;
  }
  return true;
}

function parseArgs(args) {
  const options = { mode: "check", runner: null, json: false };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--check") options.mode = "check";
    else if (arg === "--json") options.json = true;
    else if (arg === "--paths") {
      options.mode = "paths";
      options.runner = args[++index];
    } else if (arg === "--run") {
      options.mode = "run";
      options.runner = args[++index];
    } else if (arg === "--help") {
      options.mode = "help";
    } else {
      fail(`unknown argument: ${arg}`);
    }
  }
  if (["paths", "run"].includes(options.mode)
      && !["vitest", "node", "all"].includes(options.runner)) {
    fail(`runner must be vitest, node, or all; got ${options.runner || "missing"}`);
  }
  return options;
}

export function main(args = process.argv.slice(2)) {
  const options = parseArgs(args);
  if (options.mode === "help") {
    process.stdout.write([
      "Usage: node tests/protocol_v3_test_inventory.mjs [--check|--json|--paths <runner>|--run <runner|all>]",
      "Supported test suffixes: .test.jsx -> Vitest/jsdom; .test.mjs -> direct Node --test.",
    ].join("\n") + "\n");
    return 0;
  }
  const inventory = collectTestInventory();
  if (options.mode === "paths") {
    process.stdout.write(`${inventory.commands[options.runner].paths.join("\n")}\n`);
    return 0;
  }
  if (options.mode === "run") {
    const runners = options.runner === "all" ? ["vitest", "node"] : [options.runner];
    for (const runner of runners) {
      if (!runRunner(runner, inventory)) return process.exitCode ?? 1;
    }
    return 0;
  }
  if (options.json) {
    process.stdout.write(`${JSON.stringify(inventory, null, 2)}\n`);
  } else {
    process.stdout.write([
      `protocol-v3-test-inventory: ${inventory.counts.total} tests discovered`,
      `  vitest/jsdom: ${inventory.counts.vitest}`,
      `  node --test: ${inventory.counts.node}`,
      "  coverage: complete; duplicates: none; unknown runners: none",
    ].join("\n") + "\n");
  }
  return 0;
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
